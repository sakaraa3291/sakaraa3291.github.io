"""Build a local-only analysis state from official NAR monthly race ZIPs."""

import argparse
import csv
import gzip
import hashlib
import io
import json
import re
import unicodedata
from collections import Counter, defaultdict
from calendar import monthrange
from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit
from zipfile import ZipFile

from nar_download import FIRST_ODDS, GUIDE, download, months, zip_members
from people import query
from people_state import JST, MASTER, PAYOUT, integer, read_csv, start_status, write_json


SCHEMA_VERSION = 4
MASTER_COLUMNS = ('race_id', '日付', '中央地方', '競馬場', '馬場', '距離', '馬場状態', 'クラス', '枠番',
                  '馬番', '馬名', '馬ID', '騎手', '騎手ID', '騎手所属', '調教師', '調教師ID', '調教師所属',
                  '着順', 'タイム', '通過順', '脚質', '出走頭数', '人気', '単勝', 'コース区分', '前半3F', '後半3F')
PAYOUT_COLUMNS = ('race_id', '券種', '組み合わせ', '払戻金')
RACE_KEYS = ('競馬場', '競走年月日', 'レース番号')
REQUIRED = {
    'racelist': {*RACE_KEYS, '競走種類名称', '芝ダート区分', '回り', '距離', '馬場', '頭数', '上がり3F',
                 *(f'{label}{i}' for label in ('コーナー名称', 'コーナー通過順') for i in range(1, 9)),
                 *(f'ハロンタイム{i}' for i in range(1, 16))},
    'horselist': {*RACE_KEYS, '枠番', '馬番', '馬名', '生年月日', '騎手名', '調教師', '騎手所属', '調教師所属', '着順', 'タイム', '人気'},
    'payback': {*RACE_KEYS, '単勝組番', '単勝払戻金(円)',
                *(f'{label}{i}{ending}' for i in range(1, 4) for label, ending in [('複勝組番', ''), ('複勝払戻金', '(円)')])},
}


def compact(text):
    return ''.join(unicodedata.normalize('NFKC', str(text or '')).split())


def source_rows(archive, member, kind):
    with archive.open(member) as binary, io.TextIOWrapper(binary, encoding='utf-8-sig', newline='') as handle:
        reader = csv.reader(handle)
        headers = [compact(h) for h in next(reader)]
        if len(headers) != len(set(headers)) or not REQUIRED[kind] <= set(headers):
            raise ValueError(f'unexpected layout in {member.filename}')
        for number, line in enumerate(reader, 2):
            if len(line) != len(headers):
                raise ValueError(f'wrong field count in {member.filename}:{number}')
            yield dict(zip(headers, (text.strip() for text in line)))


def race_key(row):
    venue, raw_day, raw_number = (row[k] for k in RACE_KEYS)
    number = integer(raw_number)
    if not venue or not re.fullmatch(r'\d{8}', raw_day) or not number or number > 12:
        raise ValueError(f'invalid NAR race: {venue}, {raw_day}, {raw_number}')
    return compact(venue), date.fromisoformat(raw_day), number


def race_id(key):
    venue, day, number = key
    return f'nar-{day:%Y%m%d}-{venue}-{number:02d}'


def ranks(value):
    """Use one competition rank for riders in a tied corner group."""
    text = compact(value)
    tokens = re.findall(r'\([\d,*]+\)|\d+', text)
    if re.sub(r'\([\d,*]+\)|\d+|[,=+*\-]', '', text):
        return {}
    result = {}
    for token in tokens:
        numbers = [int(num) for num in re.findall(r'\d+', token)]
        if not numbers or len(set(numbers)) != len(numbers) or any(num in result or not 0 < num < 100 for num in numbers):
            return {}
        result.update(dict.fromkeys(numbers, len(result) + 1))
    return result


def course_data(row):
    corners = [ranks(row[f'コーナー通過順{i}']) for i in range(1, 9) if row[f'コーナー名称{i}']]
    corners = [r for r in corners if r]
    distance = integer(row['距離'])
    parts = [compact(row[f'ハロンタイム{i}']) for i in range(1, 16)]
    expected = distance // 200 if distance and distance % 200 == 0 else 0
    fractions = []
    if 3 <= expected <= len(parts) and not any(parts[expected:]) and all(re.fullmatch(r'\d+\.\d+', p) for p in parts[:expected]):
        fractions = [float(p) for p in parts[:expected]]
    early = f'{sum(fractions[:3]):.1f}' if fractions else ''
    return corners, early


def approved_card_values(root):
    """Use already saved, post-race NAR pages, with an exact runner/result check later."""
    if root is None:
        return {}
    cards = {}
    for path in sorted(root.glob('*/races/nar-*.json')):
        race = json.loads(path.read_text(encoding='utf-8'))
        source = urlsplit(race.get('source_url') or '')
        if race.get('organization') != 'NAR' or source.hostname != 'www.keiba.go.jp' or source.scheme != 'https':
            continue
        day = date.fromisoformat(race['target_date'])
        fetched = datetime.fromisoformat(race['fetched_at']).astimezone(JST)
        if fetched.date() <= day:
            continue
        key = (compact(race['venue']), day, race['race_number'])
        for horse in race['horses']:
            if horse.get('id_namespace') == 'nar' and horse.get('entry_status') == 'active':
                cards[key, horse['horse_number']] = horse
    return cards


def legacy_nar_runners(path, start, through):
    results = {}
    if path is None:
        return results
    duplicate_keys = set()
    for row in read_csv(path):
        if row['中央地方'] != '地方' or not start.isoformat() <= row['日付'] <= through.isoformat():
            continue
        day = date.fromisoformat(row['日付'])
        number, position = integer(row['馬番']), integer(row['着順'])
        rid = row['race_id']
        if (not re.fullmatch(r'\d{12}', rid) or rid[:4] != day.strftime('%Y') or rid[6:10] != day.strftime('%m%d')
            or not number or not position or not 1 <= int(rid[-2:]) <= 12):
            continue
        venue = compact(row['競馬場']).replace('帯広(ば)', '帯広ば')
        index = ((venue, day, int(rid[-2:])), number)
        values = (position, compact(row['馬名']), compact(row['騎手']), row['馬ID'], row['騎手ID'],
                  integer(row.get('人気')), compact(row.get('単勝')))
        if index in results and results[index] != values:
            duplicate_keys.add(index)
        results[index] = values
    for index in duplicate_keys:
        del results[index]
    return results


def monthly_win_odds(path, month, expected_keys):
    if path is None:
        return {}
    values = {}
    with ZipFile(path) as archive:
        parts = zip_members(archive, month, 'odds')
        for part in parts.values():
            with archive.open(part) as binary, io.TextIOWrapper(binary, encoding='utf-8-sig', newline='') as source:
                reader = csv.reader(source)
                columns = [compact(s) for s in next(reader)]
                required = (*RACE_KEYS, '賭式', '番号1', 'オッズ', '人気')
                if len(columns) != len(set(columns)) or not set(required) <= set(columns):
                    raise ValueError(f'unexpected NAR odds columns: {part.filename}')
                bet_col = columns.index('賭式')
                for row in reader:
                    if len(row) != len(columns):
                        raise ValueError(f'invalid NAR odds row: {part.filename}')
                    if row[bet_col] != '単勝' and compact(row[bet_col]) != '単勝':
                        continue
                    item = dict(zip(columns, row))
                    key = race_key(item)
                    if key not in expected_keys:
                        continue
                    num, popularity = integer(item['番号1']), integer(item['人気'])
                    odds = compact(item['オッズ'])
                    if not num or not re.fullmatch(r'\d+(?:\.\d+)?', odds) or float(odds) < 1:
                        continue
                    key = (key, num)
                    value = (odds, popularity)
                    if values.setdefault(key, value) != value:
                        raise ValueError(f'conflicting official win odds: {key}')
    return values


def runner_record(key, raw, detail, corners, early, card, legacy, official_odds, counts):
    venue, day, _ = key
    number, gate = integer(raw['馬番']), integer(raw['枠番'])
    if not number:
        raise ValueError(f'unidentified runner for {race_id(key)}')
    rank = compact(raw['着順'])
    rank = {'取': '取消', '除': '除外', '止': '競走中止', '失': '失格'}.get(rank, rank)
    finish_time = compact(raw['タイム']) if rank and rank not in {'取消', '除外'} else ''
    authority = [positions[number] for positions in corners if number in positions]
    passage = '-'.join(map(str, authority))
    started = start_status({'着順': rank, 'タイム': finish_time, '通過順': passage})
    style = ''
    headcount = integer(detail['頭数'])
    if len(authority) >= 2 and headcount and integer(rank):
        start = authority[0]
        style = '逃げ' if start == 1 else ('先行' if start <= headcount / 3 else
                                         '差し' if start <= 2 * headcount / 3 else '追込')
    horse, jockey, trainer = (compact(raw[field]) for field in ('馬名', '騎手名', '調教師'))
    ids = {'馬ID': '', '騎手ID': '', '調教師ID': ''}
    popularity = integer(raw['人気'])
    win_odds = ''
    if legacy and (integer(rank), horse) == legacy[:2] and horse:
        prior_jockey = legacy[2]
        if legacy[3].isascii() and legacy[3].isalnum():
            ids['馬ID'] = f'netkeiba:{legacy[3]}'
            counts['linked:legacy_馬ID'] += 1
        if (legacy[4].isascii() and legacy[4].isalnum() and jockey
            and (prior_jockey == jockey or (len(jockey) >= 3 and prior_jockey.startswith(jockey)))):
            ids['騎手ID'] = f'netkeiba:{legacy[4]}'
            counts['linked:legacy_騎手ID'] += 1
        if popularity and legacy[5] == popularity and re.fullmatch(r'\d+(?:\.\d+)?', legacy[6]) and float(legacy[6]) >= 1:
            win_odds = legacy[6]
    if (card and integer(rank) and popularity and card.get('popularity') == popularity
        and compact(card.get('horse_name')) == horse and card.get('gate_number') == gate):
        for field, key_name, actual in [('馬ID', 'horse', horse), ('騎手ID', 'jockey', jockey), ('調教師ID', 'trainer', trainer)]:
            identifier = str(card.get(f'{key_name}_id') or '')
            if (not ids[field] and identifier.isascii() and identifier.isdigit() and actual
                and compact(card.get(f'{key_name}_name')) == actual):
                ids[field] = f'nar:{identifier}'
                counts[f'linked:{field}'] += 1
    if official_odds and started == 'started' and (not popularity or not official_odds[1] or official_odds[1] == popularity):
        win_odds = official_odds[0]
        counts['linked:official_単勝'] += 1
        if not popularity and official_odds[1]:
            popularity = official_odds[1]
            counts['linked:official_人気'] += 1
    elif win_odds:
        counts['linked:legacy_単勝'] += 1
    if official_odds and popularity and official_odds[1] and official_odds[1] != popularity:
        counts['odds:popularity_conflict'] += 1
    if started == 'started' and not win_odds:
        counts['rows:started_missing_win_odds'] += 1
    counts[f'rows:{started}'] += 1
    counts['rows:rank_missing'] += not bool(rank)
    counts['rows:popularity_missing'] += not bool(popularity)
    return {'race_id': race_id(key), '日付': day.isoformat(), '中央地方': '地方', '競馬場': venue,
            '馬場': compact(detail['芝ダート区分']) or ('ばんえい' if venue == '帯広ば' else ''),
            '距離': detail['距離'], '馬場状態': detail['馬場'], 'クラス': detail['競走種類名称'], '枠番': gate or '',
            '馬番': number, '馬名': horse, '騎手': jockey, '騎手所属': compact(raw['騎手所属']),
            '調教師': trainer, '調教師所属': compact(raw['調教師所属']), '着順': rank, 'タイム': finish_time,
            '通過順': passage, '脚質': style, '出走頭数': headcount or '',
            '人気': popularity or '', '単勝': win_odds, 'コース区分': compact(detail['回り']), '前半3F': early,
            '後半3F': detail['上がり3F'], **ids}


def normalized_month(path, month, start, through, cards, legacy, odds_path, master, payout, counts):
    with ZipFile(path) as archive:
        files = zip_members(archive, month)
        # The two CSVs can include upcoming cards. Confirmed finish or payout is required.
        races = {}
        for row in source_rows(archive, files['racelist'], 'racelist'):
            key = race_key(row)
            if key[1].replace(day=1) == month and start <= key[1] <= through:
                if key in races:
                    raise ValueError(f'duplicate race {key}')
                races[key] = row
        win_odds = monthly_win_odds(odds_path, month, races)
        payouts = defaultdict(dict)
        incomplete_types = defaultdict(set)
        for row in source_rows(archive, files['payback'], 'payback'):
            key = race_key(row)
            if key not in races:
                continue
            types = [('単勝', '単勝組番', '単勝払戻金(円)')]
            types += [('複勝', f'複勝組番{i}', f'複勝払戻金{i}(円)') for i in range(1, 4)]
            for bet, horse, amount in types:
                n, yen = integer(row[horse]), integer(row[amount])
                if n and yen:
                    old = payouts[key].setdefault((bet, n), yen)
                    if old != yen:
                        raise ValueError(f'conflicting NAR payout {key}/{bet}/{n}')
                elif n or yen:
                    counts['payout:incomplete_line'] += 1
                    incomplete_types[key].add(bet)
        horses = defaultdict(list)
        for row in source_rows(archive, files['horselist'], 'horselist'):
            key = race_key(row)
            if key in races:
                horses[key].append(row)
        last_result = None
        for key, detail in sorted(races.items(), key=lambda item: (item[0][1], item[0][0], item[0][2])):
            declared = horses[key]
            if not payouts[key] and not any(integer(r['着順']) for r in declared):
                counts['races:unconfirmed'] += 1
                continue
            corners, early = course_data(detail)
            runners = [runner_record(key, r, detail, corners, early, cards.get((key, integer(r['馬番']))),
                                     legacy.get((key, integer(r['馬番']))), win_odds.get((key, integer(r['馬番']))), counts)
                       for r in declared]
            if not runners or len(runners) != len({r['馬番'] for r in runners}):
                raise ValueError(f'missing or duplicate starters in {key}')
            confirmed = {r['馬番'] for r in runners if start_status(r) == 'started'}
            missing_types = incomplete_types[key] | {bet for bet, no in payouts[key] if no not in confirmed}
            counts['races:confirmed'] += 1
            last_result = key[1]
            for bet in ('単勝', '複勝'):
                if bet not in missing_types and any(typ == bet for typ, _ in payouts[key]):
                    counts[f'payout_races:{bet}'] += 1
            counts['payout:unverified_cut'] += len(missing_types)
            for (bet, no), yen in sorted(payouts[key].items()):
                if bet not in missing_types:
                    payout.writerow({'race_id': race_id(key), '券種': bet, '組み合わせ': no, '払戻金': yen})
                    counts['payout_rows'] += 1
            master.writerows(runners)
        return last_result


def file_sha(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def odds_inputs(source, start, through):
    catalog = source / 'downloads.json' if source else None
    if not catalog or not catalog.is_file() or through < FIRST_ODDS:
        return {}
    records = json.loads(catalog.read_text(encoding='utf-8'))
    selected = {}
    for month in months(max(start, FIRST_ODDS), through):
        label = month.strftime('%Y-%m')
        archive = records.get(label, {}).get('archive')
        if archive:
            path = source / f'{label}.zip'
            if archive['kind'] != 'odds' or not path.is_file() or archive['sha256'] != file_sha(path):
                raise ValueError(f'invalid NAR odds archive {label}')
            selected[month] = (path, archive)
    return selected


def build(source, output, start, through, cards_dir=None, legacy_master=None, odds_source=None):
    if not date(2021, 1, 1) <= start <= through < datetime.now(JST).date():
        raise ValueError('use completed JST dates starting in 2021')
    catalog = json.loads((source / 'downloads.json').read_text(encoding='utf-8'))
    paths = []
    for month in months(start, through):
        label = month.strftime('%Y-%m')
        path = source / f'{label}.zip'
        evidence = catalog.get(label, {}).get('archive')
        if not evidence or not path.is_file() or evidence['sha256'] != file_sha(path):
            raise ValueError(f'missing or invalid archived month {label}')
        last = date(month.year, month.month, monthrange(month.year, month.month)[1])
        if evidence['covered_through'] < min(through, last).isoformat():
            raise ValueError(f'archived month does not reach cutoff {label}')
        paths.append((month, path, evidence))
    output.mkdir(parents=True, exist_ok=True)
    lock = output / '.build.lock'
    lock.touch(exist_ok=False)
    try:
        cards = {(key, number): card for (key, number), card in approved_card_values(cards_dir).items()
                 if start <= key[1] <= through}
        odds = odds_inputs(odds_source, start, through)
        legacy_sha = file_sha(legacy_master) if legacy_master else None
        inputs = [SCHEMA_VERSION, start.isoformat(), through.isoformat(), legacy_sha, [e['sha256'] for _, _, e in paths],
                  {m.isoformat(): v[1]['sha256'] for m, v in odds.items()},
                  [(race_id(key), number, card) for (key, number), card in sorted(cards.items())]]
        tag = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()[:24]
        snapshot = output / tag
        pointer = output / 'current.json'
        if snapshot.exists():
            report = json.loads((snapshot / 'manifest.json').read_text(encoding='utf-8'))
            if any(report['files'].get(name) != file_sha(snapshot / name) for name in (MASTER, PAYOUT)):
                raise ValueError(f'corrupt existing NAR snapshot {tag}')
            if not pointer.exists() or json.loads(pointer.read_text(encoding='utf-8')) != {'snapshot': tag}:
                write_json(pointer, {'snapshot': tag})
            return report | {'snapshot': tag, 'reused': True}
        legacy = legacy_nar_runners(legacy_master, start, through)
        counts = Counter()
        last_result = None
        with TemporaryDirectory(prefix='staging-', dir=output) as temp:
            staging = Path(temp) / 'snapshot'
            staging.mkdir()
            with gzip.open(staging / MASTER, 'wt', encoding='utf-8', newline='') as mf, \
                 gzip.open(staging / PAYOUT, 'wt', encoding='utf-8', newline='') as pf:
                master = csv.DictWriter(mf, MASTER_COLUMNS, lineterminator='\n')
                payout = csv.DictWriter(pf, PAYOUT_COLUMNS, lineterminator='\n')
                master.writeheader()
                payout.writeheader()
                for month, path, _ in paths:
                    odds_path = odds[month][0] if month in odds else None
                    last_result = normalized_month(path, month, start, through, cards, legacy, odds_path, master, payout, counts) or last_result
            if last_result is None:
                raise ValueError('no confirmed NAR results in requested period')
            report = {'schema_version': SCHEMA_VERSION, 'from': start.isoformat(), 'through': last_result.isoformat(),
                      'requested_through': through.isoformat(), 'months': len(paths), 'stats': dict(counts),
                      'source_guide': GUIDE, 'sources': [{**e, 'month': m.strftime('%Y-%m')} for m, _, e in paths],
                      'odds_sources': [{**e, 'month': m.strftime('%Y-%m')} for m, (_, e) in odds.items()],
                      'files': {name: file_sha(staging / name) for name in (MASTER, PAYOUT)},
                      'legacy_master_sha256': legacy_sha}
            write_json(staging / 'manifest.json', report)
            write_json(staging / 'people-summary.json', query(staging / MASTER, staging / PAYOUT, {},
                                                             start=start.isoformat(), end=last_result.isoformat(),
                                                             group='total', by=('venue', 'surface', 'distance'), limit=500))
            staging.replace(snapshot)
            write_json(pointer, {'snapshot': tag})
        return report | {'snapshot': tag, 'reused': False}
    finally:
        lock.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cards', type=Path)
    parser.add_argument('--legacy-master', type=Path)
    parser.add_argument('--odds-source', type=Path)
    parser.add_argument('--from', dest='start', type=date.fromisoformat, default=date(2021, 1, 1))
    parser.add_argument('--through', type=date.fromisoformat, default=datetime.now(JST).date() - timedelta(days=1))
    parser.add_argument('--sync', action='store_true')
    parser.add_argument('--run-log', type=Path)
    args = parser.parse_args()
    result = {'started_at': datetime.now(JST).isoformat(), 'status': 'running'}
    try:
        if args.sync:
            result['download'] = download(args.source, args.start, args.through)
            if result['download']['failures']:
                raise ValueError('official download is incomplete')
        report = build(args.source, args.output, args.start, args.through, args.cards, args.legacy_master, args.odds_source)
        report = {k: v for k, v in report.items() if k not in ('sources', 'odds_sources')}
        result.update(status='complete', build=report)
        print(json.dumps(report, ensure_ascii=False))
    except (OSError, ValueError) as exc:
        result.update(status='failed', error=str(exc))
        raise
    finally:
        if args.run_log:
            write_json(args.run_log, result | {'finished_at': datetime.now(JST).isoformat()})


if __name__ == '__main__':
    main()
