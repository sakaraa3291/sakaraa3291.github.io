"""Use JRA's official result PDFs to supplement missing local race facts."""

import argparse
import json
import re
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from audit_jra_sources import CODES, INDEX, index_meetings
from people_state import (JST, atomic_write, integer, observation, read_csv, start_status,
                          write_json, write_observations)


AGENT = 'KeibaResultMaintenance/1.0 (+https://github.com/sakaraa3291/sakaraa3291.github.io)'
REPORT_HOST = 'www.jra.go.jp'
REPORT_PATH = re.compile(r'/datafile/seiseki/report/(?:\d{4}\.html|\d{4}/\d{4}-\d+[a-z]+\d+\.pdf)')
NEEDED = ('騎手', '調教師', '枠番', '人気', '単勝')
JRA_VENUE_CODES = set(CODES.values())
HEADER = re.compile(r'\d{5}(\d{1,2})月(\d{1,2})日.{0,75}?第(\d{1,2})競走')
COLUMNS = {'gate': (0, 8), 'horse_name': (19, 92.25), 'jockey_name': (126, 173),
           'trainer_name': (213, 244), 'win_odds': (357, 383), 'popularity': (383, 390)}


def targets(master):
    wanted = {}
    for row in read_csv(master):
        if row['中央地方'] != '中央' or start_status(row) != 'started':
            continue
        if row['race_id'][4:6] not in JRA_VENUE_CODES:
            continue
        if all(row[column].strip() for column in NEEDED):
            continue
        meeting_id = row['race_id'][:10]
        wanted[meeting_id] = wanted.get(meeting_id, 0) + 1
    return wanted


def report_url(url):
    parsed = urlsplit(url)
    if parsed.netloc != REPORT_HOST or parsed.scheme != 'https' or parsed.query or parsed.fragment:
        raise ValueError(f'unexpected JRA report URL: {url}')
    if not REPORT_PATH.fullmatch(parsed.path):
        raise ValueError(f'unexpected JRA report path: {url}')
    return parsed


def cached_meetings(source, wanted):
    found = {}
    for year in sorted({int(key[:4]) for key in wanted}):
        path = source / f'{year}.html'
        if not path.is_file():
            continue
        for meeting in index_meetings(path.read_bytes(), year):
            if meeting['meeting_id'] in wanted:
                report_url(meeting['url'])
                found[meeting['meeting_id']] = meeting
    return found


def fetch(source, wanted):
    import requests

    source.mkdir(parents=True, exist_ok=True)
    lock = source / '.download.lock'
    lock.touch(exist_ok=False)
    try:
        results = {'target_meetings': len(wanted), 'downloaded': 0, 'cached': 0, 'errors': {}}
        with requests.Session() as session:
            session.headers['User-Agent'] = AGENT
            policy = session.get(f'https://{REPORT_HOST}/robots.txt', timeout=25, allow_redirects=False)
            if policy.status_code != 200:
                raise ValueError(f'JRA robots.txt HTTP {policy.status_code}')
            rules = RobotFileParser()
            rules.parse(policy.text.splitlines())
            interval = max(1.5, rules.crawl_delay(AGENT) or 0)
            last_request = None

            def request(url):
                nonlocal last_request
                report_url(url)
                if not rules.can_fetch(AGENT, url):
                    raise ValueError(f'JRA robots.txt denies report: {url}')
                if last_request is not None:
                    time.sleep(max(0, interval - (time.monotonic() - last_request)))
                last_request = time.monotonic()
                result = session.get(url, timeout=(10, 45), allow_redirects=False)
                result.raise_for_status()
                if result.status_code != 200 or len(result.content) > 20 * 1024 * 1024:
                    raise ValueError(f'unexpected HTTP response for {url}')
                return result.content

            for year in sorted({int(key[:4]) for key in wanted}):
                index = source / f'{year}.html'
                if not index.is_file():
                    data = request(INDEX.format(year=year))
                    index_meetings(data, year)
                    atomic_write(index, data)
            found = cached_meetings(source, wanted)
            current_year = datetime.now(JST).year
            if any(int(key[:4]) == current_year for key in set(wanted) - set(found)):
                data = request(INDEX.format(year=current_year))
                index_meetings(data, current_year)
                atomic_write(source / f'{current_year}.html', data)
                found = cached_meetings(source, wanted)
            for key in sorted(set(wanted) - set(found)):
                results['errors'][key] = 'meeting absent from official indexes'
            for key, item in sorted(found.items(), reverse=True):
                path = source / Path(report_url(item['url']).path).name
                if path.is_file() and path.read_bytes().startswith(b'%PDF-'):
                    results['cached'] += 1
                    continue
                try:
                    data = request(item['url'])
                    if not data.startswith(b'%PDF-'):
                        raise ValueError('response is not a PDF')
                    atomic_write(path, data)
                    results['downloaded'] += 1
                except (OSError, ValueError, requests.RequestException) as exc:
                    results['errors'][key] = str(exc)
                    response = getattr(exc, 'response', None)
                    if response is not None and response.status_code in {401, 403, 429, 503}:
                        break
                write_json(source / 'download-report.json', results)
                if results['downloaded'] % 10 == 0 or key in results['errors']:
                    print(json.dumps({'meeting': key, **results}, ensure_ascii=False), flush=True)
        write_json(source / 'download-report.json', results)
        return results
    finally:
        lock.unlink()


def condensed(value):
    return ''.join(unicodedata.normalize('NFKC', value).split())


def cell(chars, left, low, high):
    return condensed(''.join(ch for x, _, ch in sorted(chars) if left + low <= x < left + high and ch.isprintable()))


def page_results(page, meeting):
    blocks = page.get_text('blocks')
    headers = [(b, m) for b in blocks if (m := HEADER.search(condensed(b[4])))]
    if not headers:
        return
    chars = [(c['origin'][0], c['origin'][1], c['c']) for b in page.get_text('rawdict')['blocks']
             for line in b.get('lines', []) for s in line['spans'] for c in s['chars']]
    for header, match in headers:
        day = f'{meeting["year"]}-{int(match[1]):02d}-{int(match[2]):02d}'
        number = int(match[3])
        if not 1 <= number <= 12:
            continue
        left, start = header[0], header[3]
        cutoff = min((b[1] for b in blocks if left <= b[0] < left + 100 and b[1] > start
                      and any(label in condensed(b[4]) for label in ('売得金', '払戻金', '票数'))), default=page.rect.height)
        running = [(x, y, c) for x, y, c in chars if left <= x < left + 395 and start < y < cutoff]
        numbers = defaultdict(list)
        for x, y, char in running:
            if left + 8 <= x < left + 19 and char.isascii() and char.isdigit():
                numbers[round(y, 1)].append((x, char))
        raw_header = condensed(header[4])
        m = re.search(r'\((?:芝|ダート|障害)・(右|左|直)([^()]*)\)', raw_header)
        course = m[1] + (m[2].replace('・', '') if m and re.fullmatch(r'[・内外ABCD]*', m[2]) else '') if m else ''
        for y, digits in numbers.items():
            no = integer(''.join(char for _, char in sorted(digits)))
            if not no or not 1 <= no <= 18:
                continue
            row_chars = [(x, yy, c) for x, yy, c in running if abs(y - yy) <= 1.35]
            row = {key: cell(row_chars, left, *limits) for key, limits in COLUMNS.items()}
            if not row['horse_name'] or not any('\u3040' <= c < '\u3100' for c in row['horse_name']):
                continue
            row['jockey_name'] = row['jockey_name'].lstrip('☆△▲◇★注')
            row['trainer_name'] = row['trainer_name'].lstrip('☆△▲◇★注')
            row['gate'] = row['gate'] if (integer(row['gate']) or 0) in range(1, 9) else ''
            row['win_odds'] = row['win_odds'] if re.fullmatch(r'\d+\.\d', row['win_odds']) else ''
            row['popularity'] = row['popularity'] if (integer(row['popularity']) or 0) in range(1, 19) else ''
            yield meeting['meeting_id'] + f'{number:02d}', day, no, row | {'course': course}


def win_popularity(path):
    ranks = defaultdict(dict)
    for row in read_csv(path):
        if row['券種'] == '単勝' and (no := integer(row['組み合わせ'])) and (rank := integer(row.get('人気'))):
            ranks[row['race_id']][no] = rank
    return ranks


def extract(master, payout, source):
    import pymupdf

    wanted = targets(master)
    index = cached_meetings(source, wanted)
    runners = defaultdict(dict)
    counts, errors = Counter(), {}
    for r in read_csv(master):
        if r['race_id'][:10] in wanted and r['中央地方'] == '中央' and start_status(r) == 'started':
            runners[r['race_id']][integer(r['馬番'])] = r
    payout_ranks = win_popularity(payout)
    records = []
    for meeting_id, item in sorted(index.items()):
        path = source / Path(report_url(item['url']).path).name
        if not path.is_file():
            counts['missing_pdf'] += 1
            continue
        stamp = datetime.fromtimestamp(path.stat().st_mtime, JST).isoformat(timespec='seconds')
        by_race = defaultdict(dict)
        try:
            with pymupdf.open(path) as doc:
                for page in doc:
                    for rid, day, number, row in page_results(page, item):
                        expected = runners[rid].get(number)
                        if expected is None:
                            continue
                        if day != expected['日付'] or item['venue'] != expected['競馬場'] or row['horse_name'] != condensed(expected['馬名']):
                            counts['unmatched_pdf_row'] += 1
                            continue
                        rows = by_race[rid]
                        if number in rows and rows[number] != row:
                            raise ValueError(f'conflicting JRA PDF runner {rid}/{number}')
                        rows[number] = row
        except (OSError, ValueError, RuntimeError) as e:
            errors[meeting_id] = str(e)
            continue
        counts['parsed_pdfs'] += 1
        for rid, found in by_race.items():
            if not found:
                continue
            all_odds = found.keys() == runners[rid].keys() and all(row['win_odds'] for row in found.values())
            ranks = {}
            if all_odds:
                odds = {n: float(r['win_odds']) for n, r in found.items()}
                ranks = {n: 1 + sum(other < value for other in odds.values()) for n, value in odds.items()
                         if sum(other == value for other in odds.values()) == 1}
                anchors = {n: v for n, v in payout_ranks.get(rid, {}).items() if n in ranks}
                if not anchors or any(ranks[n] != value for n, value in anchors.items()):
                    ranks.clear()
                    counts['races:unverified_odds_order'] += 1
            for no, row in found.items():
                original = runners[rid][no]
                fields = {dst: row[dst] for dst, src in [('jockey_name', '騎手'), ('trainer_name', '調教師'),
                                                         ('win_odds', '単勝'), ('popularity', '人気'), ('gate', '枠番')]
                          if row[dst] and not original[src]}
                if row['course']:
                    fields['course'] = row['course']
                if fields and original['馬ID']:
                    records.append(observation(rid, no, original['馬ID'], original['日付'], item['url'], stamp, 'jra_pdf', fields))
                    counts.update(fields.keys())
                if not original['人気'] and not row['popularity'] and no in ranks and original['馬ID']:
                    records.append(observation(rid, no, original['馬ID'], original['日付'], item['url'], stamp,
                                               'jra_pdf_odds_order', {'popularity': str(ranks[no])}))
                    counts['popularity_derived'] += 1
    return records, {'target_meetings': len(wanted), 'meetings_on_index': len(index), 'counts': dict(counts),
                     'failed_meetings': errors, 'records': len(records)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--master', type=Path, required=True)
    parser.add_argument('--payout', type=Path)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    if args.out:
        if not args.payout or not args.report:
            parser.error('--out requires --payout and --report')
        if {args.out.resolve(), args.report.resolve()} & {args.master.resolve(), args.payout.resolve()}:
            parser.error('output would replace an input')
        records, result = extract(args.master, args.payout, args.source)
        write_observations(args.out, records)
        write_json(args.report, result)
    else:
        result = fetch(args.source, targets(args.master))
    print(json.dumps(result, ensure_ascii=False))
    return bool(result.get('errors') or result.get('failed_meetings'))


if __name__ == '__main__':
    raise SystemExit(main())
