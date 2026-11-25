"""Prepare supplemental state for the existing weekly transaction, or import saved result HTML."""

import argparse
import json
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.robotparser import RobotFileParser
from zoneinfo import ZoneInfo

from people import query
from people_state import (MASTER, PAYOUT, PEOPLE, atomic_write, audit, by_runner, observations,
                          read_csv, write_json, write_observations)

SUMMARY = 'people-summary.json'
JST = ZoneInfo('Asia/Tokyo')
TOOLS = Path(__file__).resolve().parent / 'keiba_update_pkg' / 'tools'
RETRY_FIELDS = {'jockey_id', 'jockey_name', 'trainer_id', 'trainer_name', 'gate', 'popularity', 'win_odds'}
RETRY_AGENT = 'KeibaResultMaintenance/1.0 (+https://github.com/sakaraa3291/sakaraa3291.github.io)'


def result_dates(master, ids):
    return {r['race_id']: r['日付'] for r in read_csv(master) if r['race_id'] in ids}


def saved_results(paths, expected):
    sys.path.insert(0, str(TOOLS))
    from bs4 import BeautifulSoup
    from fetch_netkeiba_delta import BASE, decode_html, parse_meta, parse_people, parse_results

    records, failures = [], {}
    for path in paths:
        rid = path.stem
        try:
            if rid not in expected:
                raise ValueError('race ID does not exist in the result master')
            soup = BeautifulSoup(decode_html(path.read_bytes()), 'lxml')
            meta = parse_meta(soup, rid, {})
            if meta['date'] != expected[rid]:
                raise ValueError('result date does not match the master')
            _, entries = parse_results(soup, rid)
            stamp = datetime.fromtimestamp(path.stat().st_mtime, JST).isoformat(timespec='seconds')
            parsed = parse_people(soup, rid, meta, entries, stamp, BASE.format(race_id=rid))
            if not parsed:
                raise ValueError('no matching result rows in saved page')
            records.extend(parsed)
        except (OSError, ValueError, KeyError, AttributeError) as exc:
            failures[rid] = str(exc)
    return records, failures


def retries_to_do(master, pending, attempted, new_ids, cutoff, limit):
    recent = (date.fromisoformat(cutoff) - timedelta(days=28)).isoformat()
    candidates = {rid for rid, fields in pending.items() if RETRY_FIELDS & fields.keys()} - attempted.keys() - new_ids
    jra_codes = {f'{n:02}' for n in range(1, 11)}
    eligible = {(r['日付'], r['race_id']) for r in read_csv(master)
                if r['race_id'] in candidates and r['中央地方'] == '中央'
                and r['race_id'][4:6] in jra_codes
                and recent <= r['日付'] <= cutoff}
    return [rid for _, rid in sorted(eligible, reverse=True)[:limit]]


def retry_results(ids, master, work, log, previous_path):
    """One supplemental refetch per recent incomplete race. Stop on access restrictions."""
    import requests
    sys.path.insert(0, str(TOOLS))
    from fetch_netkeiba_delta import BASE

    if not ids:
        return
    records = list(observations([previous_path])) if previous_path.is_file() else []
    expected = result_dates(master, set(ids))
    session = requests.Session()
    session.headers['User-Agent'] = RETRY_AGENT
    robots_url = 'https://race.netkeiba.com/robots.txt'
    try:
        policy = session.get(robots_url, timeout=20, allow_redirects=False)
        if policy.status_code != 200:
            raise ValueError(f'robots.txt HTTP {policy.status_code}; stopped')
        robots = RobotFileParser(robots_url)
        robots.parse(policy.text.splitlines())
        if not robots.can_fetch(RETRY_AGENT, BASE.format(race_id=ids[0])):
            raise ValueError('robots.txt denies result URL; stopped')
    except (requests.RequestException, ValueError) as exc:
        write_json(work / 'people-retry-policy.json', {'status': 'blocked', 'reason': str(exc)})
        return
    interval = max(2, robots.crawl_delay(RETRY_AGENT) or 0)
    with TemporaryDirectory(dir=work) as directory:
        for rid in ids:
            url = BASE.format(race_id=rid)
            if not robots.can_fetch(RETRY_AGENT, url):
                break
            time.sleep(interval)
            log[rid] = {'observed_at': datetime.now(JST).isoformat(timespec='seconds'), 'outcome': 'request_started'}
            write_json(work / 'people-retry-log.json', log)
            try:
                response = session.get(url, timeout=20, allow_redirects=False)
                outcome = f'HTTP_{response.status_code}'
                if response.status_code == 200:
                    path = Path(directory) / f'{rid}.html'
                    atomic_write(path, response.content)
                    new, failures = saved_results([path], expected)
                    records.extend(new)
                    write_observations(previous_path, records)
                    outcome = failures.get(rid, 'parsed')
            except requests.RequestException as exc:
                outcome = type(exc).__name__
            log[rid] = {'observed_at': datetime.now(JST).isoformat(timespec='seconds'), 'outcome': outcome}
            write_json(work / 'people-retry-log.json', log)
            if outcome in {'HTTP_401', 'HTTP_403', 'HTTP_429', 'HTTP_503'}:
                break


def build_snapshot(state, master, payout, cutoff, inputs, dest, retry_log=None):
    """Validate before staging either file. The caller commits both in the existing Git transaction."""
    previous = state / PEOPLE
    paths = ([previous] if previous.is_file() else []) + [path for path in inputs if path.is_file()]
    records = observations(paths)
    supplement = by_runner(records)
    coverage, pending = audit(master, supplement)
    stats = {}
    for group, by in (('jockey', ()), ('trainer', ()), ('pair', ()),
                      ('total', ('organization', 'venue', 'distance', 'surface'))):
        stats[group] = query(master, payout, supplement, start='2021-01-01', end=cutoff,
                             group=group, by=by, limit=500 if by else 25)
    recent_pending = Counter()
    from_recent = (date.fromisoformat(cutoff) - timedelta(days=6)).isoformat()
    recent = {r['race_id'] for r in read_csv(master) if from_recent <= r['日付'] <= cutoff}
    for rid in recent:
        recent_pending.update(pending.get(rid, {}))
    summary = {'schema_version': 1, 'through': cutoff, 'observations': len(records),
               'coverage': coverage, 'pending_races': len(pending),
               'recent_missing_starts': recent_pending, 'retries': retry_log or {}, 'results': stats}
    write_observations(dest / PEOPLE, records)
    write_json(dest / SUMMARY, summary)
    return summary, pending


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    weekly = sub.add_parser('weekly')
    weekly.add_argument('--state', required=True, type=Path)
    weekly.add_argument('--work', required=True, type=Path)
    weekly.add_argument('--retry-limit', type=int, choices=range(13), default=0, metavar='0..12')
    historical = sub.add_parser('import-results')
    historical.add_argument('--state', required=True, type=Path)
    historical.add_argument('--input', required=True, type=Path)
    historical.add_argument('--out', required=True, type=Path)
    historical.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    if args.action == 'import-results':
        paths = sorted(args.input.glob('*.html'))
        if not paths:
            parser.error('missing <race_id>.html files')
        expected = result_dates(args.state / MASTER, {path.stem for path in paths})
        records, failures = saved_results(paths, expected)
        out = args.out
        protected = {(args.state / name).resolve() for name in (MASTER, PAYOUT, 'manifest.json', 'horse_pedigree.csv')}
        if {out.resolve(), args.report.resolve()} & protected:
            parser.error('output would replace protected state')
        if out.resolve() == args.report.resolve():
            parser.error('report and observation output must differ')
        out.parent.mkdir(parents=True, exist_ok=True)
        lock = out.with_name(out.name + '.lock')
        lock.mkdir()
        try:
            with TemporaryDirectory(dir=out.parent) as directory:
                batch = Path(directory) / 'batch.csv.gz'
                write_observations(batch, records)
                merged = observations(([out] if out.is_file() else []) + [batch])
                audit(args.state / MASTER, by_runner(merged))
                write_observations(out, merged)
            write_json(args.report, {'received': len(paths), 'parsed': len(paths) - len(failures),
                                     'observations': len(merged), 'failures': failures})
        finally:
            lock.rmdir()
        return bool(failures)
    work = args.work
    result = json.loads((work / 'result.json').read_text(encoding='utf-8'))
    if result['status'] != 'UPDATE_READY':
        print('NO_CHANGES: supplementary state unchanged')
        return 0
    candidate = work / 'state'
    delta = work / 'delta' / 'people_delta.csv'
    retry = work / 'people-retry.csv.gz'
    previous_summary = args.state / SUMMARY
    retry_log = json.loads(previous_summary.read_text(encoding='utf-8')).get('retries', {}) if previous_summary.is_file() else {}
    checkpoint = work / 'people-retry-log.json'
    if checkpoint.is_file():
        retry_log.update(json.loads(checkpoint.read_text(encoding='utf-8')))
    if args.retry_limit:
        paths = [path for path in (args.state / PEOPLE, delta, retry) if path.is_file()]
        _, pending = audit(candidate / MASTER, by_runner(observations(paths)))
        new_ids = {r['race_id'] for r in read_csv(work / 'target.csv')}
        ids = retries_to_do(candidate / MASTER, pending, retry_log, new_ids, result['through'], args.retry_limit)
        retry_results(ids, candidate / MASTER, work, retry_log, retry)
    summary, pending = build_snapshot(args.state, candidate / MASTER, candidate / PAYOUT,
                                      result['through'], [delta, retry], work / 'people-candidate', retry_log)
    write_json(work / 'people-pending.json', pending)
    print(json.dumps({'through': summary['through'], 'observations': summary['observations'],
                      'pending_races': summary['pending_races']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
