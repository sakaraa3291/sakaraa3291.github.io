"""Audit and query jockey/trainer race results from a checked-out GitHub revision."""

import argparse
import bisect
import json
import math
import re
import unicodedata
from calendar import monthrange
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

from people_state import (MASTER, PAYOUT, PEOPLE, audit, by_runner, integer, jra_archive,
                          observations, read_csv, start_status, values_for, write_json,
                          write_observations)

ROOT = Path(__file__).resolve().parent
FIRST = date(2021, 1, 1)
STYLES = ('逃げ', '先行', '差し', '追込')
BET_TYPES = {'単勝': 'win', '複勝': 'place'}
GROUPS = {'jockey': ('jockey_id',), 'trainer': ('trainer_id',),
          'pair': ('jockey_id', 'trainer_id'), 'horse': ('horse_id',), 'total': (),
          'jockey-label': ('jockey_label', 'jockey_affiliation'),
          'trainer-label': ('trainer_label', 'trainer_affiliation'),
          'pair-label': ('jockey_label', 'jockey_affiliation', 'trainer_label', 'trainer_affiliation')}
FILTERS = ('year', 'organization', 'venue', 'distance', 'surface', 'course', 'course_variant',
           'going', 'class', 'popularity', 'gate', 'style', 'jockey_id', 'trainer_id', 'horse_id',
           'jockey_affiliation', 'trainer_affiliation', 'jockey_label', 'trainer_label', 'prior_style')


def payout_tables(path):
    tables = defaultdict(dict)
    for row in read_csv(path):
        kind = BET_TYPES.get(row['券種'])
        if not kind:
            continue
        rid = row['race_id']
        horse, amount = integer(row['組み合わせ']), integer(row['払戻金'].replace(',', '').replace('円', ''))
        if not horse or not amount:
            raise ValueError(f'invalid {kind} payout: {rid}')
        table = tables[rid, kind]
        if horse in table and table[horse] != amount:
            raise ValueError(f'conflicting {kind} payout: {rid}/{horse}')
        table[horse] = amount
    return tables


def percent(n, d):
    return round(100 * n / d, 2) if d else None


def previous_form(master, end):
    history = defaultdict(list)
    for row in read_csv(master):
        if FIRST.isoformat() <= row['日付'] <= end and row['馬ID'] and start_status(row) == 'started':
            history[row['馬ID']].append((row['日付'], row['脚質'], integer(row['着順']) or 0))
    for rows in history.values():
        rows.sort()
    return history


def prior_values(rows, day):
    end = bisect.bisect_left(rows, (day, '', 0))
    last_five = rows[max(0, end - 5):end]
    styles = Counter(style for _, style, _ in last_five if style in STYLES)
    best = styles.most_common(2)
    style = best[0][0] if best and (len(best) == 1 or best[0][1] > best[1][1]) else ''
    return style, len(last_five), sum(1 <= rank <= 3 for _, _, rank in last_five)


def dimensions(row, values, prior_style):
    distance = integer(row['距離'])
    variant = values['course']
    return {
        'year': row['日付'][:4], 'organization': row['中央地方'], 'venue': row['競馬場'],
        'distance': str(distance or ''), 'surface': row['馬場'], 'course_variant': variant,
        'course': f"{row['競馬場']}|{row['馬場']}|{distance}" if distance else '',
        'going': row['馬場状態'], 'class': row['クラス'],
        'popularity': str(integer(values['popularity']) or ''), 'gate': str(integer(values['gate']) or ''),
        'style': row['脚質'], 'prior_style': prior_style, 'horse_id': row['馬ID'],
        'jockey_id': values['jockey_id'], 'trainer_id': values['trainer_id'],
        'jockey_label': values['jockey_name'], 'trainer_label': values['trainer_name'],
        'jockey_affiliation': values['jockey_affiliation'], 'trainer_affiliation': values['trainer_affiliation'],
    }


def early_position(row):
    if row['馬場'] == '障害':
        return None, None, None
    match = re.fullmatch(r'\d+(?:-\d+)*', row['通過順'].strip())
    if not match:
        return None, None, None
    sequence = [int(n) for n in match[0].split('-')]
    # One recorded point can be the last turn. Do not call it early position.
    if len(sequence) < 2 or sequence[0] < 1:
        return None, None, None
    runners = integer(row['出走頭数'])
    fraction = (sequence[0] - 1) / (runners - 1) if runners and 2 <= runners and sequence[0] <= runners else None
    return sequence[0], fraction, len(sequence)


def add_start(stats, row, dims, tables, prior_n, prior_top3):
    stats['starts'] += 1
    rank = integer(row['着順'])
    if rank:
        stats[rank if rank <= 3 else 'outside'] += 1
    elif row['着順'] in {'中止', '競走中止', '失格'}:
        stats['outside'] += 1
    else:
        stats['unknown_finish'] += 1
    for kind in BET_TYPES.values():
        table = tables.get((row['race_id'], kind))
        if table:
            stats[f'{kind}_bets'] += 1
            stats[f'{kind}_yen'] += table.get(integer(row['馬番']), 0)
    if dims['style'] in STYLES:
        stats[dims['style']] += 1
    position, fraction, calls = early_position(row)
    if position is not None:
        stats['early_n'] += 1
        stats['early_rank_sum'] += position
        stats['early_lead'] += position == 1
        stats[f'calls_{calls}'] += 1
    if fraction is not None:
        stats['early_normalized_n'] += 1
        stats['early_fraction_sum'] += fraction
    stats['prior_starts'] += prior_n
    stats['prior_top3'] += prior_top3
    for metric, column in (('race_first_3f', '前半3F'), ('race_last_3f', '後半3F')):
        value = row.get(column, '').strip()
        if value and re.fullmatch(r'\d+(?:\.\d+)?', value) and math.isfinite(float(value)):
            stats[f'{metric}_n'] += 1
            stats[f'{metric}_sum'] += float(value)


def summarize(stats):
    starts = stats['starts']
    finished = starts - stats['unknown_finish']
    style_n = sum(stats[s] for s in STYLES)
    return {
        'starts': starts, 'first': stats[1], 'second': stats[2], 'third': stats[3],
        'outside_top3': stats['outside'], 'unknown_finish': stats['unknown_finish'],
        'finish_rate_sample': finished, 'win_pct': percent(stats[1], finished),
        'top2_pct': percent(stats[1] + stats[2], finished),
        'top3_pct': percent(stats[1] + stats[2] + stats[3], finished),
        **{kind: {'sample': stats[f'{kind}_bets'], 'missing': starts - stats[f'{kind}_bets'],
                  'return_yen': stats[f'{kind}_yen'],
                  'return_pct': percent(stats[f'{kind}_yen'], stats[f'{kind}_bets'] * 100)}
           for kind in BET_TYPES.values()},
        'style_sample': style_n, 'style_missing': starts - style_n,
        'styles': {s: {'count': stats[s], 'pct': percent(stats[s], style_n)} for s in STYLES},
        'early_sample': stats['early_n'], 'early_missing': starts - stats['early_n'],
        'early_mean_rank': round(stats['early_rank_sum'] / stats['early_n'], 2) if stats['early_n'] else None,
        'early_lead_pct': percent(stats['early_lead'], stats['early_n']),
        'early_normalized_sample': stats['early_normalized_n'],
        'early_mean_field_pct': percent(stats['early_fraction_sum'], stats['early_normalized_n']),
        'recorded_call_count': {k[6:]: v for k, v in stats.items() if isinstance(k, str) and k.startswith('calls_')},
        'prior_form_sample': stats['prior_starts'],
        'prior_form_top3_pct': percent(stats['prior_top3'], stats['prior_starts']),
        **{metric: {'sample': stats[f'{metric}_n'], 'mean_sec': round(stats[f'{metric}_sum'] / stats[f'{metric}_n'], 2)
                    if stats[f'{metric}_n'] else None}
           for metric in ('race_first_3f', 'race_last_3f')},
    }


def query(master, payout, supplemental, *, start, end, group, by=(), filters=(), limit=25, prior=False):
    names = {role: defaultdict(Counter) for role in ('jockey', 'trainer')}
    stats = defaultdict(Counter)
    coverage = Counter()
    range_by_org = {}
    group_fields = tuple(dict.fromkeys((*GROUPS[group], *by)))
    history = previous_form(master, end) if prior else {}
    tables = payout_tables(payout)
    payout_hits = defaultdict(set)
    races_seen = set()
    for row in read_csv(master):
        day = row['日付']
        if not FIRST.isoformat() <= day <= end:
            continue
        horse_no = integer(row['馬番'])
        races_seen.add(row['race_id'])
        state = start_status(row)
        if state == 'started':
            for kind in BET_TYPES.values():
                table = tables.get((row['race_id'], kind), {})
                if horse_no in table:
                    payout_hits[row['race_id'], kind].add(horse_no)
        fills = Counter()
        values = values_for(row, supplemental.get((row['race_id'], horse_no), []), fills)
        if state == 'started':
            for role in names:
                person_id, name = values[f'{role}_id'], values[f'{role}_name']
                if person_id and name:
                    names[role][person_id][name] += 1
        if day < start:
            continue
        org = row['中央地方']
        lo, hi = range_by_org.get(org, (day, day))
        range_by_org[org] = min(lo, day), max(hi, day)
        style, prior_n, prior_top3 = prior_values(history.get(row['馬ID'], []), day) if prior else ('', 0, 0)
        dims = dimensions(row, values, style)
        if any(dims[f] not in selected for f, selected in filters):
            continue
        coverage[state] += 1
        if state != 'started':
            continue
        coverage.update(f'missing:{f}' for f, v in dims.items() if not v and (prior or f != 'prior_style'))
        if any(not dims[f] for f in GROUPS[group]):
            coverage['missing_group_label' if group.endswith('-label') else 'missing_group_id'] += 1
            continue
        result = stats[tuple(dims[f] for f in group_fields)]
        add_start(result, row, dims, tables, prior_n, prior_top3)
    # Never silently score a corrupted payout table as a loss for all unmatched horses.
    bad = [k for k, winners in tables.items() if k[0] in races_seen and payout_hits[k] != winners.keys()]
    if bad:
        raise ValueError(f'payout includes unverified starters: {bad[:5]}')
    rows = []
    for values, bucket in sorted(stats.items(), key=lambda item: (-item[1]['starts'], item[0]))[:limit]:
        row = dict(zip(group_fields, values))
        for role, directory in names.items():
            options = directory.get(row.get(f'{role}_id'), Counter())
            if options:
                row[f'{role}_name'] = sorted(options, key=lambda n: (-options[n], n))[0]
        rows.append(row | summarize(bucket))
    return {'from': start, 'through': end, 'observed_range_by_organization': range_by_org,
            'group': group, 'group_identity': 'published label and affiliation' if group.endswith('-label') else 'ids',
            'by': list(by), 'filters': dict(filters), 'coverage': coverage,
            'groups_found': len(stats), 'groups_returned': len(rows), 'results': rows}


def window(available, start=None, end=None, period='all', before=None):
    end = min(end or available, available, before - timedelta(days=1) if before else available)
    if not start and period != 'all':
        months = {'1m': 1, '6m': 6, '1y': 12}[period]
        year, month = divmod(end.year * 12 + end.month - 1 - months, 12)
        start = date(year, month + 1, min(end.day, monthrange(year, month + 1)[1])) + timedelta(days=1)
    start = max(start or FIRST, FIRST)
    if end < start:
        raise ValueError('empty or inverted date range')
    return start.isoformat(), end.isoformat()


def lookup(master, supplement, role, label, end):
    def normalize(name):
        return ''.join(unicodedata.normalize('NFKC', name).split())

    matches = defaultdict(Counter)
    for row in read_csv(master):
        if row['日付'] > end:
            continue
        values = values_for(row, supplement.get((row['race_id'], integer(row['馬番'])), []), Counter())
        name, person_id = values[f'{role}_name'], values[f'{role}_id']
        if person_id and normalize(label) in normalize(name):
            matches[person_id][name] += 1
    return matches


def resolve_state(path):
    if (path / 'manifest.json').is_file() or not (path / 'current.json').is_file():
        return path
    selected = json.loads((path / 'current.json').read_text(encoding='utf-8')).get('snapshot', '')
    if not isinstance(selected, str) or not re.fullmatch(r'[0-9a-f]{24}', selected):
        raise ValueError('invalid local snapshot pointer')
    return path / selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, default=ROOT / 'state')
    parser.add_argument('--people', type=Path, help='Override the default supplementary observation file')
    sub = parser.add_subparsers(dest='action', required=True)
    ask = sub.add_parser('query')
    ask.add_argument('--group', choices=GROUPS, default='jockey')
    ask.add_argument('--period', choices=('all', '1y', '6m', '1m'), default='all')
    for flag in ('from', 'to', 'before'):
        ask.add_argument(f'--{flag}', dest=f'{flag}_date', type=date.fromisoformat)
    ask.add_argument('--as-observed', action='store_true', help='With --before, omit observations retrieved on/after the target day')
    ask.add_argument('--by', action='append', default=[], choices=FILTERS)
    ask.add_argument('--where', action='append', default=[], metavar='FIELD=VALUE')
    ask.add_argument('--limit', type=int, default=25, choices=range(1, 1001), metavar='1..1000')
    ask.add_argument('--prior-form', action='store_true')
    report = sub.add_parser('audit')
    report.add_argument('--out', type=Path)
    report.add_argument('--pending', type=Path)
    reuse = sub.add_parser('reuse-archive')
    reuse.add_argument('--archive', type=Path, default=ROOT.parent / 'prediction-data')
    reuse.add_argument('--out', required=True, type=Path)
    find = sub.add_parser('lookup')
    find.add_argument('--role', choices=('jockey', 'trainer'), required=True)
    find.add_argument('--name', required=True)
    args = parser.parse_args()
    state = resolve_state(args.state)
    supplement = args.people or state / PEOPLE
    paths = [supplement] if supplement.is_file() else []
    cutoff = json.loads((state / 'manifest.json').read_text(encoding='utf-8'))['through']
    if args.action == 'reuse-archive':
        if args.out.resolve() in {(state / n).resolve() for n in (MASTER, PAYOUT, 'manifest.json', 'horse_pedigree.csv')}:
            parser.error('output would replace protected state')
        records = jra_archive(args.archive, state / MASTER)
        write_observations(args.out, records)
        print(json.dumps(Counter(r['evidence'] for r in records), ensure_ascii=False))
        return
    if args.action == 'audit':
        records = observations(paths)
        result, pending = audit(state / MASTER, by_runner(records))
        payouts = payout_tables(state / PAYOUT)
        result |= {'manifest_through': cutoff, 'supplement_rows': len(records),
                   'pending_races': len(pending),
                   'payout_races': Counter(kind for _, kind in payouts)}
        if args.pending:
            write_json(args.pending, pending)
        if args.out:
            write_json(args.out, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if args.action == 'lookup':
        if not args.name.strip():
            parser.error('a name or part of a name is required')
        result = lookup(state / MASTER, by_runner(observations(paths)), args.role, args.name, cutoff)
        print(json.dumps({'through': cutoff, 'matches': result}, ensure_ascii=False, indent=2))
        return
    if args.as_observed and not args.before_date:
        parser.error('--as-observed requires --before')
    selected = defaultdict(list)
    for condition in args.where:
        field, sep, value = condition.partition('=')
        if not sep or field not in FILTERS:
            parser.error(f'invalid filter: {condition}')
        selected[field].append(value)
    start, end = window(date.fromisoformat(cutoff), args.from_date, args.to_date, args.period, args.before_date)
    before = args.before_date.isoformat() if args.as_observed else None
    result = query(state / MASTER, state / PAYOUT, by_runner(observations(paths), before),
                   start=start, end=end, group=args.group, by=args.by, filters=tuple(selected.items()),
                   limit=args.limit, prior=args.prior_form or 'prior_style' in (*args.by, *selected))
    result.update(manifest_through=cutoff, before_observation_date=before)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
