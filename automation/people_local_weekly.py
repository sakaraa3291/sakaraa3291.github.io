"""Refresh the private Windows analysis snapshots after the existing GitHub update."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import jra_pdf_people
import jra_trainer_registry
import nar_download
import nar_people
from people import FIRST, query, resolve_state
from people_state import (JST, MASTER, PAYOUT, PEOPLE, audit, by_runner, observations,
                          write_json, write_observations)


ROOT = Path(__file__).resolve().parents[1]
GITHUB = 'https://github.com/sakaraa3291/sakaraa3291.github.io.git'
RAW = 'https://raw.githubusercontent.com/sakaraa3291/sakaraa3291.github.io'
HASH = re.compile(r'[0-9a-f]{40}')
ASSETS = (MASTER, PAYOUT)


def public_revision():
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0')
    text = subprocess.run(['git', 'ls-remote', '--exit-code', GITHUB, 'refs/heads/main'],
                          check=True, capture_output=True, text=True, timeout=50, env=env).stdout
    parts = text.strip().split('\t')
    if len(parts) != 2 or not HASH.fullmatch(parts[0]) or parts[1] != 'refs/heads/main':
        raise ValueError('unrecognized GitHub main reference')
    return parts[0]


def from_public_main(local, stage, offline, cached=None):
    import requests

    local_manifest = json.loads((local / 'manifest.json').read_text(encoding='utf-8'))
    if offline:
        ref = 'offline local checkout'
        manifest = local_manifest
    else:
        ref = public_revision()
        base = f'{RAW}/{ref}/automation/state/'
        response = requests.get(base + 'manifest.json', timeout=25, allow_redirects=False)
        if response.status_code != 200:
            raise ValueError(f'public manifest HTTP {response.status_code}')
        manifest = response.json()
    for name in ASSETS:
        path = stage / name
        expected = manifest['files'][name]
        if expected == local_manifest['files'][name] and nar_people.file_sha(local / name) == expected:
            shutil.copyfile(local / name, path)
        elif not offline and cached and (cached / name).is_file() and nar_people.file_sha(cached / name) == expected:
            shutil.copyfile(cached / name, path)
        elif offline:
            raise ValueError(f'local checked-out base checksum mismatch: {name}')
        else:
            with requests.get(base + name, timeout=(15, 120), stream=True, allow_redirects=False) as response:
                if response.status_code != 200:
                    raise ValueError(f'public state HTTP {response.status_code}: {name}')
                with path.open('xb') as dst:
                    for block in response.iter_content(1024 * 1024):
                        if dst.tell() + len(block) > 256 * 1024 * 1024:
                            raise ValueError(f'public state too large: {name}')
                        dst.write(block)
        if nar_people.file_sha(path) != expected:
            raise ValueError(f'base state checksum mismatch: {name}')
    return ref, manifest


def refresh_jra(local, runs, offline):
    work = runs / 'jra-official'
    source, output = work / 'source', work / 'state'
    output.mkdir(parents=True, exist_ok=True)
    month = datetime.now(JST).strftime('%Y-%m')
    roster = source / 'roster' / month
    # Reuse the initial verified roster collected in the download directory this month.
    active = source / 'trainer.html'
    if active.is_file() and datetime.fromtimestamp(active.stat().st_mtime, JST).strftime('%Y-%m') == month:
        roster = source
    status = resolve_state(output)
    with TemporaryDirectory(prefix='staging-', dir=output) as tmp:
        stage = Path(tmp) / 'snapshot'
        stage.mkdir()
        ref, manifest = from_public_main(local, stage, offline, status)
        extras = [path for path in (runs / 'archive-observations.csv.gz', runs / 'live-observations.csv.gz') if path.is_file()]
        signature = {'version': 2, 'base': {name: manifest['files'][name] for name in ASSETS},
                     'through': manifest['through'], 'roster_month': month,
                     'extras': {p.name: nar_people.file_sha(p) for p in extras}}
        pointer = status / 'manifest.json'
        if pointer.is_file():
            old = json.loads(pointer.read_text(encoding='utf-8'))
            if (old.get('local_input') == signature and nar_people.file_sha(status / PEOPLE) == old.get('supplement_sha256')
                and all(nar_people.file_sha(status / name) == manifest['files'][name] for name in ASSETS)):
                return {'source_revision': ref, 'through': manifest['through'], 'status': 'reused',
                        'observations': old['local_observations'], 'snapshot': status.name}
        if not offline:
            downloads = jra_pdf_people.fetch(source, jra_pdf_people.targets(stage / MASTER))
            if downloads['errors'] or downloads['cached'] + downloads['downloaded'] != downloads['target_meetings']:
                raise ValueError('JRA official downloads are incomplete; see download-report.json')
            jra_trainer_registry.download(roster)
        pdf, extraction = jra_pdf_people.extract(stage / MASTER, stage / PAYOUT, source)
        write_json(work / 'latest-extraction.json', extraction)
        if extraction['failed_meetings'] or extraction['counts'].get('missing_pdf') or extraction['target_meetings'] != extraction['meetings_on_index']:
            raise ValueError('JRA official result reads are incomplete; see latest-extraction.json')
        registry, counts = jra_trainer_registry.links(stage / MASTER, roster, pdf)
        write_json(work / 'latest-trainer-coverage.json', counts)
        extracted, linked = Path(tmp) / 'pdf.csv.gz', Path(tmp) / 'trainer.csv.gz'
        write_observations(extracted, pdf)
        write_observations(linked, registry)
        records = observations([*extras, extracted, linked])
        supplement = by_runner(records)
        audit_report, pending = audit(stage / MASTER, supplement)
        write_json(stage / 'coverage.json', audit_report)
        write_json(stage / 'pending.json', pending)
        write_json(stage / 'people-summary.json', query(stage / MASTER, stage / PAYOUT, supplement,
                                                         start=FIRST.isoformat(), end=manifest['through'], group='total',
                                                         by=('venue', 'surface', 'distance'),
                                                         filters=(('organization', ('中央',)),), limit=500))
        write_observations(stage / PEOPLE, records)
        sha = nar_people.file_sha(stage / PEOPLE)
        snapshot = hashlib.sha256((json.dumps(signature, sort_keys=True) + '\n' + sha).encode()).hexdigest()[:24]
        write_json(stage / 'manifest.json', manifest | {'local_input': signature, 'source_revision': ref,
                                                        'supplement_sha256': sha, 'local_observations': len(records)})
        if not (output / snapshot).exists():
            stage.replace(output / snapshot)
        else:
            old = json.loads((output / snapshot / 'manifest.json').read_text(encoding='utf-8'))
            if old.get('local_input') != signature or nar_people.file_sha(output / snapshot / PEOPLE) != sha:
                raise ValueError('existing JRA snapshot disagrees with verified inputs')
        write_json(output / 'current.json', {'snapshot': snapshot})
        return {'source_revision': ref, 'through': manifest['through'], 'status': 'complete',
                'observations': len(records), 'snapshot': snapshot}


def refresh_nar(local, runs, yesterday, offline):
    work = runs / 'nar-official'
    source = work / 'source'
    downloaded = None
    if not offline:
        downloaded = nar_download.download(source, FIRST, yesterday)
        if downloaded['failures'] or downloaded['cached'] + downloaded['downloaded'] != downloaded['expected']:
            raise ValueError('NAR monthly downloads are incomplete; see downloads.json')
    result = nar_people.build(source, work / 'state', FIRST, yesterday, ROOT / 'prediction-data', local / MASTER)
    return {k: v for k, v in result.items() if k != 'sources'} | {'download': downloaded, 'status': 'complete'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', type=Path, default=ROOT / 'automation' / 'runs')
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    runs = args.runs.resolve()
    runs.mkdir(parents=True, exist_ok=True)
    report = {'started_at': datetime.now(JST).isoformat()}
    lock = runs / '.private-weekly.lock'
    lock.touch(exist_ok=False)
    try:
        local = ROOT / 'automation' / 'state'
        cutoff = (datetime.now(JST) - timedelta(hours=2)).date() - timedelta(days=1)
        for name, step in [('nar', lambda: refresh_nar(local, runs, cutoff, args.offline)),
                           ('jra', lambda: refresh_jra(local, runs, args.offline))]:
            try:
                report[name] = step()
            except Exception as exc:
                report[name] = {'status': 'failed', 'error': str(exc)}
            write_json(runs / 'private-weekly.json', report)
        report['finished_at'] = datetime.now(JST).isoformat()
        write_json(runs / 'private-weekly.json', report)
        print(json.dumps(report, ensure_ascii=False))
        return any(report[name]['status'] == 'failed' for name in ('nar', 'jra'))
    finally:
        lock.unlink()


if __name__ == '__main__':
    raise SystemExit(main())
