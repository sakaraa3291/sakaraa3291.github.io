#!/usr/bin/env python3
"""Reconstruct race IDs from JRA's independent annual result-PDF index.

Requires requests, beautifulsoup4 and PyMuPDF. Network is opt-in; cached evidence
is reused. No existing-master input is accepted: it must not define the universe.
"""
from __future__ import annotations
import argparse
import concurrent.futures
import gzip
import hashlib
import json
import re
import time
import unicodedata
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

VENUES = dict(zip(
    ['sapporo','hakodate','fukushima','niigata','tokyo','nakayama','chukyo','kyoto','hanshin','kokura'],
    ['札幌','函館','福島','新潟','東京','中山','中京','京都','阪神','小倉']))
CODES = {v: f'{i:02}' for i, v in enumerate(VENUES, 1)}
INDEX = 'https://www.jra.go.jp/datafile/seiseki/report/{year}.html'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def index_meetings(content, year):
    soup = BeautifulSoup(content.decode('cp932'), 'html.parser')
    if f'{year}年' not in soup.get_text() or '年度別全成績' not in soup.get_text():
        raise ValueError('wrong/incomplete annual results index')
    found = {}
    for a in soup.select('a[href]'):
        match = re.search(r'/(\d{4})-(\d+)([a-z]+)(\d+)\.pdf$', '/' + a['href'])
        if not match:
            continue
        y, meeting, venue, day = match.groups()
        if int(y) != year or venue not in CODES:
            raise ValueError(f'invalid meeting link: {a["href"]}')
        key = f'{y}{CODES[venue]}{int(meeting):02}{int(day):02}'
        url = urljoin(INDEX.format(year=year), a['href'])
        if key in found and found[key]['url'] != url:
            raise ValueError(f'conflicting meeting: {key}')
        found[key] = dict(meeting_id=key, year=year, venue=VENUES[venue],
                          meeting=int(meeting), day=int(day), url=url)
    if not found:
        raise ValueError('no meetings in official index')
    return list(found.values())


def validate_meeting(races, meeting, adjudications=None):
    """Require evidence for every slot, including interior AND trailing gaps.

    Eleven/seven results are not inherently incomplete: specific cancellations
    can explain the absent slots. Master membership is never evidence here.
    """
    adjudications = adjudications or {}
    prefix = meeting['meeting_id']
    expected = {prefix + f'{n:02}' for n in range(1, 13)}
    ids = [r['race_id'] for r in races]
    if len(ids) != len(set(ids)) or not set(ids) <= expected:
        raise ValueError(f'duplicate/invalid result headers: {prefix}')
    cancelled = {r['race_id'] for r in adjudications.get('cancelled', [])
                 if r.get('source_url') and r.get('reason')}
    images = [r for r in adjudications.get('image_verified', [])
              if r['race_id'] in expected and r.get('source_url') == meeting['url']
              and r.get('evidence')]
    corrected = list(races) + [r for r in images if r['race_id'] not in ids]
    result_ids = {r['race_id'] for r in corrected if r['result_status'] == 'result'}
    if result_ids & cancelled:
        raise ValueError(f'result/cancellation conflict: {prefix}')
    missing = expected - {r['race_id'] for r in corrected} - cancelled
    if missing:
        raise ValueError(f'unresolved result slots: {sorted(missing)}')
    if not corrected or len({r['date'] for r in corrected}) != 1:
        raise ValueError(f'empty/mixed result dates: {prefix}')
    return sorted(corrected, key=lambda r: r['race_id'])


def parse_result_text(text, meeting, adjudications=None):
    # Strip whitespace only for header matching; preserve raw extraction as evidence.
    t = re.sub(r'\s+', '', unicodedata.normalize('NFKC', text))
    # Result headers have a five-digit running race number, date, weather, meeting day.
    pat = re.compile(r'(\d{5})(\d{1,2})月(\d{1,2})日.{0,65}?第(\d{1,2})競走')
    matches = list(pat.finditer(t))
    races = []
    for i, m in enumerate(matches):
        serial, month, day, number = m.groups()
        number = int(number)
        if not 1 <= number <= 12:
            raise ValueError(f'invalid race number {number}')
        date = f'{meeting["year"]}-{int(month):02}-{int(day):02}'
        body = t[m.end():matches[i+1].start() if i+1 < len(matches) else len(t)]
        races.append(dict(race_id=meeting['meeting_id']+f'{number:02}', date=date,
                          venue=meeting['venue'], source_url=meeting['url'],
                          source_serial=serial,
                          result_status='cancelled' if '競走取りやめ' in body[:1000] or '競走取止' in body[:1000] else 'result'))
    if not races or len({r['race_id'] for r in races}) != len(races):
        raise ValueError(f'empty/duplicate result headers: {meeting["meeting_id"]}')
    if len({r['date'] for r in races}) != 1:
        raise ValueError(f'mixed result dates: {meeting["meeting_id"]}')
    return validate_meeting(races, meeting, adjudications)


def collect_meeting(args):
    meeting, cache_dir, network, *extra = args
    adjudications = extra[0] if extra else None
    cache = Path(cache_dir)
    raw = cache / (meeting['meeting_id'] + '.pdf')
    extracted = cache / (meeting['meeting_id'] + '.txt.gz')
    record = cache / (meeting['meeting_id'] + '.json')
    try:
        # Reparse cached text: a prior 'verified' flag must not bypass new checks.
        if record.exists() and extracted.exists():
            result = json.loads(record.read_text())
            with gzip.open(extracted, 'rt', encoding='utf-8') as f:
                text = f.read()
            if digest(text.encode()) != result['text_sha256']:
                raise ValueError('cached text checksum mismatch')
            result['races'] = parse_result_text(text, meeting, adjudications)
            result['status'] = 'verified'
            result['verification_rule'] = 'all_12_slots_evidenced_v2'
            return result
        if not raw.exists():
            if not network:
                raise ValueError('PDF not cached; use --fetch')
            import requests
            # Exactly two attempts, second host is an alternate official route.
            last = None
            for url in [meeting['url'], meeting['url'].replace('www.jra.go.jp', 'jra.jp')]:
                try:
                    response = requests.get(url, timeout=45)
                    response.raise_for_status()
                    if not response.content.startswith(b'%PDF-'):
                        raise ValueError('response is not a PDF')
                    raw.write_bytes(response.content)
                    break
                except Exception as e:
                    last = e
            else:
                raise last
            time.sleep(.15)
        import pymupdf
        with pymupdf.open(raw) as doc:
            text = '\n'.join(page.get_text() for page in doc)
        with gzip.open(extracted, 'wt', encoding='utf-8') as f:
            f.write(text)
        races = parse_result_text(text, meeting, adjudications)
        result = dict(**meeting, pdf_sha256=digest(raw.read_bytes()),
                      text_sha256=digest(text.encode()), races=races, status='verified')
        record.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
        return result
    except Exception as e:
        return dict(**meeting, status='unresolved', error=str(e))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--cache', type=Path, required=True)
    ap.add_argument('--from-date', default='2021-01-02')
    ap.add_argument('--to-date', default='2026-09-22')
    ap.add_argument('--fetch', action='store_true')
    ap.add_argument('--workers', type=int, default=4)
    a = ap.parse_args()
    rules_path = a.out / 'population_rules.json'
    rules = json.loads(rules_path.read_text()) if rules_path.exists() else {}
    a.out.mkdir(parents=True, exist_ok=True)
    a.cache.mkdir(parents=True, exist_ok=True)
    evidence = a.out / 'evidence'
    evidence.mkdir(exist_ok=True)
    meetings, sources = [], []
    for year in range(int(a.from_date[:4]), int(a.to_date[:4])+1):
        path = evidence / f'{year}.html'
        if not path.exists():
            if not a.fetch:
                raise SystemExit(f'missing index: {path}')
            import requests
            r = requests.get(INDEX.format(year=year), timeout=30)
            r.raise_for_status()
            path.write_bytes(r.content)
        meetings.extend(index_meetings(path.read_bytes(), year))
        sources.append(dict(url=INDEX.format(year=year), sha256=digest(path.read_bytes())))
    print(json.dumps({'indexed_meetings': len(meetings)}), flush=True)
    results = []
    with concurrent.futures.ProcessPoolExecutor(a.workers) as pool:
        for i, result in enumerate(pool.map(collect_meeting, [(m,str(a.cache),a.fetch,rules) for m in meetings]), 1):
            results.append(result)
            if i % 50 == 0 or result['status'] != 'verified':
                print(json.dumps({'processed': i, 'meeting': result['meeting_id'],
                                  'status': result['status'], 'error': result.get('error')}), flush=True)
    obj = dict(from_date=a.from_date, to_date=a.to_date, sources=sources, meetings=results)
    (a.out/'official_sources.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
    races = [r for m in results for r in m.get('races', []) if a.from_date <= r['date'] <= a.to_date]
    import pandas as pd
    pd.DataFrame(races).sort_values(['date','race_id']).to_csv(a.out/'canonical_races.csv',index=False)
    unresolved = [r for r in results if r['status'] != 'verified']
    print(json.dumps({'races': len(races), 'unresolved_meetings':len(unresolved)}))
    return 2 if unresolved else 0


if __name__ == '__main__':
    raise SystemExit(main())
