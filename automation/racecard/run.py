"""python -m automation.racecard.run --target-date YYYY-MM-DD [--apply]."""
from __future__ import annotations

import argparse
import copy
import ctypes
import hashlib
import json
import os
import shutil
import tempfile
import traceback
from datetime import datetime
from pathlib import Path

from .core import JST, canonical, digest, reconcile, require, target_date, validate_race
from .sources import Fetcher, apply_odds, jra_discover, nar_calendar, nar_list, parse_jra, parse_jra_history, parse_nar, page, nar_params, NAR

ROOT = Path(__file__).resolve().parents[2]


def supplement_history(races, root, target):
    """Use v4.2 only by horse ID AND race ID; fill rest-slot gaps without network."""
    import csv
    import gzip
    horses = {h['horse_id']: h for r in races if r['organization'] == 'JRA' for h in r['horses']}
    records = {hid: [] for hid in horses}
    with gzip.open(root / 'automation/state/keiba_master.csv.gz', 'rt', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            hid = row['馬ID']
            day = row['日付'].replace('/', '-')[:10]
            if hid in records and day < str(target) and row['着順'] not in ('除', '除外', '取消', '取', ''):
                records[hid].append(row)
    for hid, horse in horses.items():
        runs = {r['race_id']: r for r in horse['past_performances']}
        for row in sorted(records[hid], key=lambda x: x['日付'], reverse=True)[:5]:
            rid = row['race_id']
            if rid in runs:
                runs[rid]['jockey_id'] = row['騎手ID'] or None
                continue
            runs[rid] = dict(race_id=rid, date=row['日付'].replace('/', '-')[:10], race_name=row['レース名'],
                             venue=row['競馬場'], rank=row['着順'], jockey_id=row['騎手ID'] or None,
                             jockey_name=row['騎手'] or None, source_url=f'https://db.netkeiba.com/race/{rid}/',
                             raw=json.dumps(row, ensure_ascii=False), source_name='v4.2 persistent master (ID join)',
                             passage=row['通過順'] or None,
                             last_3f=float(row['上がり3F']) if row['上がり3F'] else None)
        horse['past_performances'] = sorted(runs.values(), key=lambda x: (x['date'], x['race_id']), reverse=True)[:5]
        if horse['past_performances']:
            horse['history_availability'] = 'available'
        horse['history_join'] = 'netkeiba horse_id + race_id; no name joins'


def read(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value) + b'\n')


def read_cache(path):
    state = read(path, {'schema_version': 1, 'horses': {}})
    validate_cache(state)
    return state


def validate_cache(state):
    require(isinstance(state, dict) and type(state.get('schema_version')) is int
            and state['schema_version'] == 1, 'unsupported cache schema')
    require(isinstance(state.get('horses'), dict), 'invalid cache horses')


def enrich(race, root):
    version = read(root / 'data-version.json')
    state = read(root / 'automation/state/manifest.json')
    hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
              for name in ('lapdata.json', 'pedigree_stats.json')}
    require(all(version['files'][k] == v == state['production'][k] for k, v in hashes.items()), 'v4.2 dataset hash mismatch')
    race['derived_from'] = dict(dataset_id=version['dataset_id'], data_through=state['through'],
                                lapdata_sha256=hashes['lapdata.json'], pedigree_sha256=hashes['pedigree_stats.json'])
    # Condition context is labelled by its exact existing key, not a horse-name join.
    prefix = f'{race["venue"]}|{dict(turf="芝", dirt="ダート", jump="障害")[race["surface"]]}|{race["distance_m"]}|'
    race['dataset_context'] = {'condition_prefix': prefix,
        'lap_conditions': {k: v for k, v in read(root / 'lapdata.json')['cond'].items() if k.startswith(prefix)} or None,
        'pedigree_conditions': {k: v for k, v in read(root / 'pedigree_stats.json')['stats'].items() if k.startswith(prefix)} or None,
        'selection': 'Candidate conditions for this venue/surface/distance; keys retain class and going. No horse-level name join.',
        'contains_target_or_later_results': state['through'] >= race['target_date']}


def collect_jra(fetch, target, cache, stamp):
    url = f'https://race.sp.netkeiba.com/?pid=race_list&kaisai_date={target:%Y%m%d}'
    ids = jra_discover(fetch.get(url), target)
    races = []
    for rid in ids:
        html = fetch.get(f'https://race.netkeiba.com/race/shutuba.html?race_id={rid}')
        observed = datetime.now(JST).isoformat(timespec='seconds')
        race = parse_jra(html, rid, target, observed)
        odds, odds_url = fetch.odds(rid)
        apply_odds(race, odds, odds_url)
        keys = [f'netkeiba:{h["horse_id"]}:{target}:{stamp[:10]}' for h in race['horses']]
        if not all(k in cache for k in keys):
            history = parse_jra_history(fetch.get(f'https://race.netkeiba.com/race/shutuba_past.html?race_id={rid}'), race)
            for hid, value in history.items():
                cache[f'netkeiba:{hid}:{target}:{stamp[:10]}'] = value
        for h, key in zip(race['horses'], keys):
            h.update(copy.deepcopy(cache[key]))
        races.append(race)
    # A changing meeting list cannot produce a complete-looking partial publication.
    require(jra_discover(fetch.get(url), target) == ids, 'JRA meeting manifest changed during fetch')
    return races, dict(status='complete', race_count=len(races), source_url=url, fetched_at=stamp)


def collect_nar(fetch, target, cache, stamp):
    url = f'{NAR}/KeibaWeb/MonthlyConveneInfo/MonthlyConveneInfoTop?k_year={target.year}&k_month={target.month}'
    meetings = nar_calendar(fetch.get(url), target)
    races = []
    for meeting in meetings:
        html = fetch.get(meeting['url'])
        items = nar_list(html, meeting, target)
        soup = page(html)
        anchors = soup.select('a[href*="DebaTable"]')
        from urllib.parse import urljoin
        # Race navigation on an independently fetched card catches a missing final list row.
        first_url = urljoin(NAR, anchors[0]['href'])
        first_html = fetch.get(first_url)
        nav = page(first_html).select('a[href*="DebaTable"]')
        expected = {int(nar_params(urljoin(NAR, a['href']), target)['k_raceNo']) for a in anchors}
        actual = {int(nar_params(urljoin(NAR, a['href']), target)['k_raceNo']) for a in nav}
        require(actual == expected, f'NAR partial race list: {meeting["venue"]}')
        for item in items:
            card = first_html if item['url'] == first_url else fetch.get(item['url'])
            race = parse_nar(card, item, target, datetime.now(JST).isoformat(timespec='seconds'))
            # NAR includes history with the card: no additional horse-history requests.
            for h in race['horses']:
                key = f'nar:{h["horse_id"]}:{target}'
                value = {k: h[k] for k in ('past_performances', 'history_availability', 'history_source_url', 'history_fetched_at', 'pedigree')}
                if key in cache and digest(cache[key]) == digest(value):
                    h.update(copy.deepcopy(cache[key]))
                else:
                    cache[key] = value
            races.append(race)
    require(nar_calendar(fetch.get(url), target) == meetings, 'NAR calendar changed during fetch')
    return races, dict(status='complete', race_count=len(races), meeting_count=len(meetings), source_url=url, fetched_at=stamp)


def build(root, target, fetch, stamp, reusable_cache=None):
    state = read_cache(root / 'automation/racecard-state/cache.json')
    cache = {}
    if reusable_cache is not None:
        validate_cache(reusable_cache)
        cache.update(copy.deepcopy(reusable_cache['horses']))
    # Committed observations are authoritative when a restored cache overlaps.
    cache.update(copy.deepcopy(state['horses']))
    races, sources, errors = [], {}, []
    for org, collector in [('JRA', collect_jra), ('NAR', collect_nar)]:
        try:
            found, report = collector(fetch, target, cache, stamp)
            races.extend(found)
            sources[org] = report
            print(json.dumps({'source': org, **report}, ensure_ascii=False), flush=True)
        except Exception as exc:
            errors.append(f'{org}: {exc}')
            print(json.dumps({'source': org, 'status': 'failed', 'error': str(exc)}, ensure_ascii=False), flush=True)
            traceback.print_exc()
    require(not errors, '; '.join(errors))
    supplement_history(races, root, target)
    old_index = read(root / f'prediction-data/{target}/index.json', {})
    old_ids = {r['race_id'] for r in old_index.get('races', [])}
    require(old_ids <= {r['race_id'] for r in races}, 'previous race disappeared without explicit cancellation')
    for race in races:
        old = read(root / f'prediction-data/{target}/races/{race["race_id"]}.json')
        enrich(race, root)
        reconcile(race, old)
        validate_race(race)
    require(len({r['race_id'] for r in races}) == len(races), 'duplicate race ID')
    return sorted(races, key=lambda r: r['race_id']), sources, dict(schema_version=1, horses=cache)


def prepare(root, target, races, sources, stamp):
    """Validate the entire candidate before any production file is touched."""
    production = root / 'prediction-data'
    candidate = Path(tempfile.mkdtemp(prefix='.racecard-candidate-', dir=root))
    if production.exists():
        shutil.copytree(production, candidate, dirs_exist_ok=True)
    rows = []
    for race in races:
        validate_race(race)
        path = f'{target}/races/{race["race_id"]}.json'
        old = read(production / path)
        if old and digest(old) == digest(race):
            race = old  # Keep the observation times of the last material observation.
        else:
            race['content_sha256'] = digest(race)
        write(candidate / path, race)
        rows.append({k: race[k] for k in ('race_id', 'venue', 'race_number', 'race_name', 'organization', 'grade', 'start_time', 'race_status')} |
                    {'url': f'prediction-data/{path}', 'sha256': hashlib.sha256((candidate / path).read_bytes()).hexdigest()})
    index = dict(schema_version=1, target_date=str(target), generated_at=stamp,
                 status='complete' if rows else 'no_target_races', race_count=len(rows),
                 jra_race_count=sum(r['organization'] == 'JRA' for r in races),
                 nar_jpn_race_count=sum(r['organization'] == 'NAR' for r in races), sources=sources,
                 races=rows, timezone='Asia/Tokyo',
                 usage='Compare target_date with requested JST date. Never treat an older date as today. fetched_at is the last material observation, not a heartbeat.')
    old = read(production / f'{target}/index.json')
    if old and digest(index) == digest(old):
        index = old
    write(candidate / f'{target}/index.json', index)
    latest = read(production / 'latest.json')
    # Historical manual replays must not move latest backwards.
    if not latest or latest['target_date'] <= str(target):
        write(candidate / 'latest.json', index)
    write(candidate / 'schema.json', read(Path(__file__).with_name('schema.json')))
    validate_tree(candidate)
    return candidate


def validate_tree(root):
    for index_path in [root / 'latest.json', *root.glob('????-??-??/index.json')]:
        index = read(index_path)
        require(index['schema_version'] == 1, 'unsupported index schema')
        require(index['race_count'] == len(index['races']) == index['jra_race_count'] + index['nar_jpn_race_count'], 'index count mismatch')
        require(index['status'] == ('complete' if index['races'] else 'no_target_races'), 'index status mismatch')
        require(set(index['sources']) == {'JRA', 'NAR'} and all(s['status'] == 'complete' for s in index['sources'].values()), 'partial source status')
        for entry in index['races']:
            expected = f'prediction-data/{index["target_date"]}/races/{entry["race_id"]}.json'
            require(entry['url'] == expected, 'unsafe race path')
            path = root / entry['url'].removeprefix('prediction-data/')
            require(hashlib.sha256(path.read_bytes()).hexdigest() == entry['sha256'], 'detail hash mismatch')
            race = read(path)
            require(race['target_date'] == index['target_date'] and race['race_id'] == entry['race_id'], 'index identity mismatch')
            validate_race(race)


def tree_hash(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()} if root.exists() else {}


def publish(candidate, production):
    """Linux atomic directory exchange: readers see the complete old or complete new tree."""
    if not production.exists():
        os.replace(candidate, production)
        return
    libc = ctypes.CDLL(None, use_errno=True)
    rename = libc.renameat2
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    if rename(-100, os.fsencode(candidate), -100, os.fsencode(production), 2) != 0:
        raise OSError(ctypes.get_errno(), 'atomic prediction directory exchange failed')
    shutil.rmtree(candidate)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--target-date', default='')
    ap.add_argument('--schedule', default='')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--diagnostics', type=Path, default=Path('/tmp/racecard-run'))
    ap.add_argument('--cache-file', type=Path)
    args = ap.parse_args()
    target = target_date(args.target_date, schedule=args.schedule)
    stamp = datetime.now(JST).isoformat(timespec='seconds')
    fetch = Fetcher(args.diagnostics)
    races, sources, cache = build(ROOT, target, fetch, stamp, read_cache(args.cache_file) if args.cache_file else None)
    candidate = prepare(ROOT, target, races, sources, stamp)
    changed = tree_hash(candidate) != tree_hash(ROOT / 'prediction-data')
    if changed and args.apply:
        publish(candidate, ROOT / 'prediction-data')
        cache_path = ROOT / 'automation/racecard-state/cache.json'
        temp = cache_path.with_suffix('.tmp')
        write(temp, cache)
        os.replace(temp, cache_path)
    else:
        shutil.rmtree(candidate)
    if args.cache_file:
        # Actions cache persists successful fetches even when no Git commit is needed.
        write(args.cache_file, cache)
    status = 'UPDATED' if changed and args.apply else 'VALIDATED' if changed else 'NO_CHANGES'
    report = dict(status=status, target_date=str(target), race_count=len(races), fetched_pages=fetch.count, changed=changed and args.apply)
    write(args.diagnostics / 'report.json', report)
    print(json.dumps(report), flush=True)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write(f'changed={str(changed and args.apply).lower()}\ntarget_date={target}\n')


if __name__ == '__main__':
    main()
