"""Verified supplementary result observations, separate from the legacy master."""

import csv
import gzip
import io
import json
import os
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import parse_qs, urlsplit

MASTER = 'keiba_master.csv.gz'
PAYOUT = 'payout.csv.gz'
PEOPLE = 'people_observations.csv.gz'
FIELDS = {
    'jockey_id': '騎手ID', 'jockey_name': '騎手', 'jockey_affiliation': '騎手所属',
    'trainer_id': '調教師ID', 'trainer_name': '調教師', 'trainer_affiliation': '調教師所属',
    'gate': '枠番', 'popularity': '人気', 'win_odds': '単勝', 'course': 'コース区分',
}
COLUMNS = ['race_id', 'horse_no', 'horse_id', 'date', 'source', 'observed_at', 'evidence', *FIELDS]
ID = re.compile(r'[0-9A-Za-z]+')
JST = timezone(timedelta(hours=9))
JRA_PDF_EVIDENCE = {'jra_pdf', 'jra_pdf_odds_order'}
JRA_TRAINER_EVIDENCE = 'jra_trainer_profile'


def jra_profile_id(source):
    if source.netloc != 'www.jra.go.jp' or source.path != '/JRADB/accessC.html' or source.fragment:
        return None
    query = parse_qs(source.query)
    token = query.get('CNAME', [])
    if set(query) != {'CNAME'} or len(token) != 1:
        return None
    found = re.fullmatch(r'pw05cmk(\d{6})/[A-Z0-9]{2}', token[0])
    return f'jra:{found[1]}' if found else None


def valid_observation_source(evidence, source):
    if source.scheme != 'https' or source.username or source.password:
        return False
    if evidence in JRA_PDF_EVIDENCE:
        return (source.netloc == 'www.jra.go.jp' and not source.query and not source.fragment
                and bool(re.fullmatch(r'/datafile/seiseki/report/\d{4}/\d{4}-\d+[a-z]+\d+\.pdf', source.path)))
    if evidence == JRA_TRAINER_EVIDENCE:
        return bool(jra_profile_id(source))
    return (evidence in {'result', 'prior_result', 'final_odds'}
            and source.hostname in {'race.netkeiba.com', 'db.netkeiba.com'})


def read_csv(path):
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt', encoding='utf-8-sig', newline='') as f:
        yield from csv.DictReader(f)


def integer(value):
    match = re.fullmatch(r'([0-9]+)(?:\.0+)?', str(value or '').strip())
    return int(match[1]) if match else None


def key(row):
    return row['race_id'], integer(row['horse_no'])


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as f:
        temp = Path(f.name)
        try:
            f.write(data)
        except BaseException:
            f.close()
            temp.unlink(missing_ok=True)
            raise
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def write_json(path, value):
    atomic_write(path, (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


def write_observations(path, records):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, COLUMNS, lineterminator='\n')
    writer.writeheader()
    writer.writerows(sorted(records, key=lambda r: (*key(r), r['evidence'], r['source'])))
    data = stream.getvalue().encode('utf-8')
    atomic_write(path, gzip.compress(data, mtime=0) if path.suffix == '.gz' else data)


def observations(paths):
    records = {}
    for path in paths:
        seen = set()
        for row in read_csv(path):
            if set(row) != set(COLUMNS) or None in row.values():
                raise ValueError(f'invalid observation columns: {path}')
            source = urlsplit(row['source'])
            identity = (*key(row), row['evidence'], row['source'])
            when = datetime.fromisoformat(row['observed_at'])
            trainer_profile = row['evidence'] == JRA_TRAINER_EVIDENCE
            if (not re.fullmatch(r'\d{12}', row['race_id'])
                or not key(row)[1] or not ID.fullmatch(row['horse_id'])
                or not valid_observation_source(row['evidence'], source) or when.utcoffset() is None
                or when.astimezone(JST).date() < date.fromisoformat(row['date'])
                or (row['evidence'] in JRA_PDF_EVIDENCE and (row['jockey_id'] or row['trainer_id']))
                or (trainer_profile and (row['trainer_id'] != jra_profile_id(source)
                                         or any(row[f] for f in FIELDS if f != 'trainer_id')))
                or (not trainer_profile and any(row[f] and not ID.fullmatch(row[f]) for f in ('jockey_id', 'trainer_id')))):
                raise ValueError(f'invalid observation: {identity}')
            if identity in seen:
                raise ValueError(f'duplicate observation: {identity}')
            seen.add(identity)
            old = records.get(identity)
            if old and (old['horse_id'], old['date']) != (row['horse_id'], row['date']):
                raise ValueError(f'observation identity changed: {identity}')
            if not old:
                records[identity] = row
            elif (previous_time := datetime.fromisoformat(old['observed_at'])) <= when:
                updates = {f: row[f] for f in FIELDS if row[f] and row[f] != old[f]}
                if previous_time == when and any(old[f] for f in updates):
                    raise ValueError(f'conflicting observation at the same time: {identity}')
                if any(old[f] and f in updates for f in ('jockey_id', 'trainer_id')):
                    raise ValueError(f'observed person ID changed: {identity}')
                if updates:
                    records[identity] = old | updates | {'observed_at': row['observed_at']}
    return records.values()


def by_runner(records, before=None):
    by_key = defaultdict(list)
    for row in records:
        if before is None or datetime.fromisoformat(row['observed_at']).astimezone(JST).date().isoformat() < before:
            by_key[key(row)].append(row)
    return by_key


def values_for(master, records, counts):
    values = {field: master.get(col, '').strip() if col else '' for field, col in FIELDS.items()}
    evidence = defaultdict(set)
    direct = defaultdict(set)
    official = defaultdict(set)
    for row in records:
        if (row['horse_id'], row['date']) != (master['馬ID'], master['日付']):
            raise ValueError(f'observation does not match master horse/date: {key(row)}')
        for role in ('jockey', 'trainer'):
            field = f'{role}_id'
            if row[field] and values[field] and row[field] != values[field]:
                raise ValueError(f'{field} disagrees with master for {key(row)}')
        for field in FIELDS:
            if row[field]:
                evidence[field].add(row[field])
                if row['evidence'] != 'jra_pdf_odds_order':
                    direct[field].add(row[field])
                if row['evidence'] in {'jra_pdf', JRA_TRAINER_EVIDENCE}:
                    official[field].add(row[field])
    for field, candidates in evidence.items():
        candidates = official[field] or direct[field] or candidates
        if not values[field] and len(candidates) == 1:
            values[field] = next(iter(candidates))
            counts[field] += 1
        elif len(candidates) > 1 and (not values[field] or field.endswith('_id')):
            counts[f'conflict:{field}'] += 1
    if not values['trainer_affiliation']:
        label = re.match(r'^\[([東西地外])\]', values['trainer_name'])
        if label:
            values['trainer_affiliation'] = {'東': '美浦', '西': '栗東', '地': '地方', '外': '海外'}[label[1]]
    return values


def jra_archive(root, master):
    """Reuse final odds and exact prior-result IDs. Exclude declared riders/trainers."""
    odds, prior = {}, {}
    for path in sorted(root.glob('*/races/*.json')):
        race = json.loads(path.read_text(encoding='utf-8'))
        if race['organization'] != 'JRA':
            continue
        d, rid = race['target_date'], race['race_id']
        odds_source = race.get('odds_source') or {}
        for horse in race['horses']:
            if horse.get('id_namespace') != 'netkeiba' or not horse.get('horse_id'):
                continue
            hid, no = horse['horse_id'], horse['horse_number']
            if odds_source.get('status') == 'result' and horse.get('entry_status') == 'active':
                if integer(horse.get('popularity')) and horse.get('win_odds'):
                    values = dict(popularity=str(horse['popularity']), win_odds=str(horse['win_odds']))
                    odds[rid, no] = (d, hid, odds_source, values)
            for result in horse.get('past_performances', []):
                if not all(result.get(k) for k in ('race_id', 'date', 'rank', 'jockey_id', 'jockey_name', 'source_url')):
                    continue
                prior.setdefault((result['race_id'], hid), []).append((result, horse.get('history_fetched_at') or race['fetched_at']))
    records = []
    for row in read_csv(master):
        if not integer(row['着順']):
            continue
        rid, no, hid, d = row['race_id'], integer(row['馬番']), row['馬ID'], row['日付']
        match = odds.get((rid, no))
        if match and (d, hid) == match[:2] and (not row['人気'] or not row['単勝']):
            source = match[2]
            records.append(observation(rid, no, hid, d, source['source_url'], source['fetched_at'], 'final_odds', match[3]))
        if row['騎手ID'] and row['騎手']:
            continue
        matches = [(r, stamp) for r, stamp in prior.get((rid, hid), [])
                   if r['date'] == d and integer(r['rank']) == integer(row['着順'])
                   and (not row['騎手ID'] or r['jockey_id'] == row['騎手ID'])
                   and stamp[:10] > d]
        if len({(r['jockey_id'], r['jockey_name']) for r, _ in matches}) == 1:
            result, stamp = min(matches, key=lambda pair: pair[1])
            values = dict(jockey_id=result['jockey_id'], jockey_name=result['jockey_name'])
            records.append(observation(rid, no, hid, d, result['source_url'], stamp, 'prior_result', values))
    return records


def observation(rid, no, horse_id, day, source, observed_at, evidence, values):
    return dict.fromkeys(COLUMNS, '') | dict(race_id=rid, horse_no=str(no), horse_id=horse_id,
                                            date=day, source=source, observed_at=observed_at,
                                            evidence=evidence) | values


def audit(master, supplemental):
    summary = defaultdict(Counter)
    dates, races, keys, pending = {}, {}, set(), defaultdict(Counter)
    known_names, missing_names = set(), defaultdict(Counter)
    for row in read_csv(master):
        day, org, rid = row['日付'], row['中央地方'], row['race_id']
        k = rid, integer(row['馬番'])
        if k in keys:
            raise ValueError(f'duplicate master race/horse: {k}')
        keys.add(k)
        if rid in races and races[rid] != (org, day):
            raise ValueError(f'master race has conflicting dates or organizations: {rid}')
        races[rid] = (org, day)
        lo, hi = dates.get(org, (day, day))
        dates[org] = min(lo, day), max(hi, day)
        out = summary[org]
        out['rows'] += 1
        state = start_status(row)
        out[state] += 1
        filled = Counter()
        values = values_for(row, supplemental.get(k, []), filled)
        if values['jockey_id']:
            if values['jockey_name']:
                known_names.add(values['jockey_id'])
            else:
                missing_names[org, state][values['jockey_id']] += 1
        for field, col in FIELDS.items():
            if not col or not row.get(col):
                out[f'original_missing:{field}'] += 1
            if not values[field]:
                out[f'{state}_missing:{field}'] += 1
                if state == 'started':
                    pending[rid][field] += 1
        out.update({f'filled:{f}': n for f, n in filled.items()})
    if supplemental.keys() - keys:
        raise ValueError('supplemental data contains races/horse numbers absent from master')
    for (org, state), counts in missing_names.items():
        summary[org][f'{state}_jockey_name_alias_available'] = sum(counts[p] for p in known_names)
    for org, _ in races.values():
        summary[org]['races'] += 1
    return {'date_range': dates, 'counts': summary}, pending


def start_status(row):
    rank = row['着順'].strip()
    if rank in {'取消', '除外', '競走除外', '出走取消', '取'}:
        return 'nonstarter'
    if integer(rank) or rank in {'中止', '競走中止', '失格'} or row.get('タイム') or row.get('通過順'):
        return 'started'
    return 'unresolved_start'
