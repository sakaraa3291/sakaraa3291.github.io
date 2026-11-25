"""Link official JRA trainer profiles to exact names and independently recorded affiliations."""

import argparse
import json
import re
import time
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from jra_pdf_people import AGENT, JRA_VENUE_CODES, condensed
from people_state import (JST, atomic_write, integer, observation, observations, read_csv,
                          start_status, write_json, write_observations)


BASE = 'https://www.jra.go.jp'
ACTIVE = BASE + '/datafile/meikan/trainer.html'
RETIRED = BASE + '/datafile/meikan/retirement.html'
SEARCH = BASE + '/JRADB/accessC.html'
GROUP = re.compile(r"return doAction\('/JRADB/accessC\.html',\s*'(pw05cnlH1([A-Z])/[A-Z0-9]{2})'\)")
PROFILE = re.compile(r"doAction\('/JRADB/accessC\.html',\s*'(pw05cmk(\d{6})/[A-Z0-9]{2})'\)")
REGION = {'東': '美浦', '西': '栗東'}


def groups(content):
    doc = BeautifulSoup(content, 'html.parser')
    codes = {m[2]: m[1] for a in doc.select('a[onclick]') if (m := GROUP.search(a['onclick']))}
    if set(codes) != set('AKSTNHMYRW'):
        raise ValueError('wrong/incomplete official trainer selector')
    return codes


def profiles(content, retired=False):
    doc = BeautifulSoup(content, 'html.parser')
    found = []
    for a in doc.select('a[onclick]'):
        m = PROFILE.search(a['onclick'])
        if not m:
            continue
        text = condensed(a.get_text())
        until = None
        if retired:
            h = a.find_previous(['h3', 'h4'])
            region = condensed(h.get_text()) if h else ''
            match = re.fullmatch(r'(.+?)\((\d{4})年(\d{1,2})月(\d{1,2})日引退\)', text)
            if not match or region not in REGION.values():
                raise ValueError(f'invalid retirement record for {m[2]}')
            text = match[1]
            until = date(int(match[2]), int(match[3]), int(match[4]))
        else:
            region, text = text[:2], text[2:]
            if region not in REGION.values() or not text:
                raise ValueError(f'invalid active trainer record for {m[2]}')
        found.append((text, region, until, f'jra:{m[2]}', f'{SEARCH}?{urlencode({"CNAME": m[1]})}'))
    if not found:
        title = condensed(doc.title.get_text()) if doc.title else ''
        if retired or title != '調教師選択JRA' or '該当するデータがありません' not in condensed(doc.get_text()):
            raise ValueError('no JRA profile identifiers in response')
    return found


def download(source):
    import requests
    from urllib.robotparser import RobotFileParser

    source.mkdir(parents=True, exist_ok=True)
    with requests.Session() as session:
        session.headers['User-Agent'] = AGENT
        policy = session.get(BASE + '/robots.txt', timeout=20, allow_redirects=False)
        if policy.status_code != 200:
            raise ValueError(f'JRA robots.txt HTTP {policy.status_code}')
        rules = RobotFileParser()
        rules.parse(policy.text.splitlines())
        if not all(rules.can_fetch(AGENT, url) for url in (ACTIVE, RETIRED, SEARCH)):
            raise ValueError('JRA robots.txt denies trainer directories')
        delay = max(1.5, rules.crawl_delay(AGENT) or 0)

        def request(url, params=None):
            time.sleep(delay)
            if params:
                response = session.post(url, data=params, headers={'Referer': ACTIVE}, timeout=25, allow_redirects=False)
            else:
                response = session.get(url, timeout=25, allow_redirects=False)
            if response.status_code != 200:
                raise ValueError(f'JRA trainer directory HTTP {response.status_code}')
            return response.content

        for url, name, parse in ((ACTIVE, 'trainer.html', groups), (RETIRED, 'retirement.html', lambda data: profiles(data, True))):
            path = source / name
            if not path.exists():
                data = request(url)
                parse(data)
                atomic_write(path, data)
        for group, code in groups((source / 'trainer.html').read_bytes()).items():
            path = source / f'trainer-group-{group}.html'
            if not path.exists():
                data = request(SEARCH, {'CNAME': code})
                profiles(data)
                atomic_write(path, data)


def load_registry(source):
    roster = {}
    paths = [(source / 'retirement.html', True)]
    paths.extend((source / f'trainer-group-{group}.html', False)
                 for group in groups((source / 'trainer.html').read_bytes()))
    for path, retired in paths:
        stamp = datetime.fromtimestamp(path.stat().st_mtime, JST).isoformat(timespec='seconds')
        for name, area, end, identifier, url in profiles(path.read_bytes(), retired):
            record = (name, area, end, identifier, url, stamp)
            if identifier in roster and roster[identifier][:4] != record[:4]:
                raise ValueError(f'conflicting official trainer: {identifier}')
            roster[identifier] = record
    return roster.values()


def exact_affiliation(raw):
    found = re.fullmatch(r'\[([東西])]\s*(.+)', condensed(raw))
    return (found[2], REGION[found[1]]) if found else None


def links(master, source, pdf_observations):
    registry = load_registry(source)
    identities = defaultdict(list)
    for name, region, *rest in registry:
        identities[name, region].append(rest)
    pdf_names = {(record['race_id'], integer(record['horse_no'])): record['trainer_name']
                 for record in pdf_observations if record['evidence'] == 'jra_pdf' and record['trainer_name']}
    prior = defaultdict(list)
    counts = Counter()
    if pdf_names:
        for row in read_csv(master):
            known = exact_affiliation(row['調教師'])
            if known and row['馬ID'] and start_status(row) == 'started':
                prior[row['馬ID']].append((row['日付'], known))
    result = []
    for row in read_csv(master):
        rid, day, horse = row['race_id'], row['日付'], row['馬ID']
        if row['中央地方'] != '中央' or rid[4:6] not in JRA_VENUE_CODES or not horse or start_status(row) != 'started':
            continue
        no = integer(row['馬番'])
        known = exact_affiliation(row['調教師'])
        method = 'master_name_affiliation'
        if not known and (name := pdf_names.get((rid, no))):
            history = {(old_day, old_key) for old_day, old_key in prior[horse] if old_day < day}
            latest = max((d for d, _ in history), default='')
            current = {key for d, key in history if d == latest and key[0] == name}
            if len(current) == 1:
                known = current.pop()
                method = 'pdf_name_affiliation_from_same_horse'
        if not known:
            counts['no_independent_affiliation'] += 1
            continue
        candidates = [(last, identifier, url, stamp) for last, identifier, url, stamp in identities.get(known, [])
                      if last is None or day <= last.isoformat()]
        if len(candidates) != 1:
            counts['not_unique_or_directory_missing'] += 1
            continue
        _, identifier, url, stamp = candidates[0]
        result.append(observation(rid, no, horse, day, url, stamp, 'jra_trainer_profile', {'trainer_id': identifier}))
        counts[method] += 1
    return result, dict(counts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--fetch', action='store_true')
    parser.add_argument('--master', type=Path, required=True)
    parser.add_argument('--pdf', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if {args.out.resolve(), args.report.resolve()} & {args.master.resolve(), args.pdf.resolve()}:
        parser.error('output would replace an input')
    if args.fetch:
        download(args.source)
    result, counts = links(args.master, args.source, observations([args.pdf]))
    write_observations(args.out, result)
    write_json(args.report, counts)
    print(json.dumps(counts, ensure_ascii=False))


if __name__ == '__main__':
    main()
