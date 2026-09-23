"""Verify every published detail/hash and freshly reconcile one actual source race."""
import argparse
import hashlib
import json
import tempfile
from datetime import date, datetime
from pathlib import Path

import requests

from .core import JST, require, validate_race
from .run import ROOT, read
from .sources import Fetcher, parse_jra, parse_nar


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', required=True)
    ap.add_argument('--target-date', required=True)
    args = ap.parse_args()
    base = args.url.rstrip('/') + '/'
    public_index = f'prediction-data/{args.target_date}/index.json'
    local_index = read(ROOT / public_index)
    paths = ['prediction-data/latest.json', public_index, *[r['url'] for r in local_index['races']]]
    for path in paths:
        response = requests.get(base + path, params={'verify': datetime.now(JST).timestamp()}, timeout=60)
        response.raise_for_status()
        require(response.content == (ROOT / path).read_bytes(), f'public bytes mismatch: {path}')
        if '/races/' in path:
            validate_race(response.json())
    report = {'status': 'verified', 'target_date': args.target_date, 'public_files_verified': len(paths)}
    if local_index['races']:
        # Prefer the NAR primary source when this target has a Jpn race.
        entry = next((r for r in local_index['races'] if r['organization'] == 'NAR'), local_index['races'][0])
        published = read(ROOT / entry['url'])
        fetch = Fetcher(Path(tempfile.mkdtemp(prefix='racecard-reconcile-')))
        html = fetch.get(published['source_url'])
        day = date.fromisoformat(args.target_date)
        stamp = datetime.now(JST).isoformat()
        if published['organization'] == 'JRA':
            actual = parse_jra(html, published['source_race_id'], day, stamp)
        else:
            item = dict(url=published['source_url'], venue=published['venue'], race_number=published['race_number'],
                        grade=published['grade'], count=published['declared_entry_count'],
                        start=published['start_time'][11:16], course=str(published['distance_m']))
            actual = parse_nar(html, item, day, stamp)
        fields = ['race_id', 'target_date', 'venue', 'race_number', 'start_time', 'distance_m', 'race_status']
        require(all(published[k] == actual[k] for k in fields), 'source race changed since publication')
        keys = ['horse_id', 'horse_number', 'horse_name', 'jockey_id', 'jockey_name', 'carried_weight', 'entry_status']
        require([{k: h[k] for k in keys} for h in published['horses']] ==
                [{k: h[k] for k in keys} for h in actual['horses']], 'public/source entries mismatch')
        report.update(source_reconciliation='PASS', race_id=published['race_id'], source_url=published['source_url'],
                      horse_count=len(actual['horses']), compared_race_fields=fields, compared_horse_fields=keys)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
