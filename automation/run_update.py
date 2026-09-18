#!/usr/bin/env python3
"""Fail-closed hosted runner. Only --apply copies validated candidates; never pushes."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = Path(__file__).parent / 'keiba_update_pkg'
STATE_FILES = ('keiba_master.csv.gz', 'payout.csv.gz', 'horse_pedigree.csv')
PUBLIC_FILES = ('lapdata.json', 'pedigree_stats.json', 'data-version.json')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run_tool(name, *args):
    subprocess.run([sys.executable, str(PACKAGE / 'tools' / name), *map(str, args)], check=True)


def check_baseline(repo, state):
    manifest = read_json(state / 'manifest.json')
    version = read_json(repo / 'data-version.json')
    config = read_json(PACKAGE / 'config/pwa_static.json')
    require(version['app_version'] == config['app_version'] == '3.8.0', 'app version changed')
    require(version['dataset_id'] == config['dataset_id'], 'dataset ID changed')
    for name in ('lapdata.json', 'pedigree_stats.json', 'courses.json', 'elevation.json'):
        require(digest(repo / name) == version['files'][name], f'production hash mismatch: {name}')
        require(read_json(repo / name)['meta']['dataset_id'] == version['dataset_id'], f'dataset mismatch: {name}')
    for name in ('courses', 'elevation'):
        require(digest(repo / f'{name}.json') == config[f'{name}_sha256'], f'static file changed: {name}')
    lap = read_json(repo / 'lapdata.json')
    ped = read_json(repo / 'pedigree_stats.json')
    require(lap['meta']['to'] == ped['meta']['audit']['to'] == manifest['through'],
            f"state/production cutoff mismatch: state={manifest['through']}, lap={lap['meta']['to']}, pedigree={ped['meta']['audit']['to']}")
    for name in STATE_FILES:
        require(digest(state / name) == manifest['files'][name], f'state hash mismatch: {name}')
    for name in ('lapdata.json', 'pedigree_stats.json'):
        require(digest(repo / name) == manifest['production'][name], f'state belongs to different production: {name}')
    return manifest


def check_candidate(repo, state, work, cutoff):
    import pandas as pd
    read = lambda p: pd.read_csv(p, dtype=str, low_memory=False).fillna('')
    require((work / 'UPDATE_READY').is_file(), 'UPDATE_READY missing')
    release = work / 'release'
    run_tool('validate_release_candidate.py', '--release-dir', release,
             '--baseline-lap', repo / 'lapdata.json', '--to-date', cutoff,
             '--dataset-id', read_json(repo / 'data-version.json')['dataset_id'])
    version = read_json(release / 'data-version.json')
    for name in ('courses.json', 'elevation.json'):
        require(version['files'][name] == digest(repo / name), 'static hash changed')
    old = read_json(repo / 'lapdata.json')
    new = read_json(release / 'lapdata.json')
    for key, value in old['meta'].get('audit', {}).items():
        if key != 'incremental_grade_update':
            require(new['meta']['audit'].get(key) == value, f'manual audit changed: {key}')
    target = read(work / 'target.csv')
    ids = set(target.race_id)
    require(ids and target.date.between(old['meta']['to'], cutoff, inclusive='right').all(), 'invalid candidate dates')
    run_tool('validate_delta_complete.py', '--target', work / 'target.csv',
             '--delta-dir', work / 'delta', '--base-pedigree', state / STATE_FILES[2], '--strict')
    for name in STATE_FILES[:2]:
        before, after = read(state / name), read(work / 'state' / name)
        require(after.iloc[:len(before)].reset_index(drop=True).equals(before), f'history/order changed: {name}')
        added = after.iloc[len(before):]
        require(set(added.race_id) == ids and not ids & set(before.race_id), f'race coverage mismatch: {name}')
    master = read(work / 'state' / STATE_FILES[0])
    require(master['日付'].max() <= cutoff, 'future master rows')
    require(new['meta']['to'] == cutoff, 'candidate cutoff mismatch')
    # State and public JSON will be committed together, making retries transactional in Git.
    return {'schema_version': 1, 'through': cutoff,
            'files': {name: digest(work / 'state' / name) for name in STATE_FILES},
            'production': {name: digest(release / name) for name in PUBLIC_FILES[:2]}}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo', type=Path, default=ROOT)
    ap.add_argument('--state', type=Path)
    ap.add_argument('--workdir', type=Path, required=True)
    ap.add_argument('--to-date', default='')
    ap.add_argument('--apply', action='store_true')
    a = ap.parse_args()
    require(not sys.flags.optimize, 'Python optimization disables legacy validator assertions')
    repo = a.repo.resolve()
    state = (a.state or repo / 'automation/state').resolve()
    work = a.workdir.resolve()
    require(not work.exists(), 'use a new workdir for each invocation')
    work.mkdir(parents=True)
    today = datetime.now(ZoneInfo('Asia/Tokyo')).date()
    cutoff = date.fromisoformat(a.to_date) if a.to_date else today - timedelta(days=1)
    require(cutoff < today, 'cutoff must be a completed day in Asia/Tokyo')
    manifest = check_baseline(repo, state)
    report = {'status': 'NO_CHANGES', 'through': manifest['through'], 'requested_to': cutoff.isoformat()}
    if cutoff.isoformat() > manifest['through']:
        run_tool('run_incremental_update.py', '--master', state / STATE_FILES[0],
                 '--payout', state / STATE_FILES[1], '--pedigree', state / STATE_FILES[2],
                 '--baseline-lap', repo / 'lapdata.json', '--to-date', cutoff.isoformat(),
                 '--workdir', work, '--release-config', PACKAGE / 'config/pwa_static.json')
        if (work / 'UPDATE_READY').exists():
            effective_to = read_json(work / 'update_report.json')['to']
            require(manifest['through'] < effective_to <= cutoff.isoformat(), 'invalid effective cutoff')
            next_manifest = check_candidate(repo, state, work, effective_to)
            report = {'status': 'UPDATE_READY', 'through': effective_to, 'applied': a.apply}
            if a.apply:
                for name in PUBLIC_FILES:
                    shutil.copyfile(work / 'release' / name, repo / name)
                for name in STATE_FILES:
                    shutil.copyfile(work / 'state' / name, state / name)
                write_json(state / 'manifest.json', next_manifest)
        else:
            require((work / 'NO_CHANGES').exists(), 'runner produced no terminal result')
    write_json(work / 'result.json', report)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write(f"changed={str(report['status'] == 'UPDATE_READY' and a.apply).lower()}\n")
    print(json.dumps(report))

if __name__ == '__main__':
    main()
