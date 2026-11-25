"""Fetch only the NAR monthly race ZIPs covered by its data download FAQ."""

import argparse
import hashlib
import io
import json
import time
from calendar import monthrange
from datetime import date, datetime, timedelta
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from people_state import JST, atomic_write, write_json


MONTHLY = 'https://www.keiba.go.jp/KeibaWeb/DataDownload/RaceDataDownload'
GUIDE = 'https://www.keiba.go.jp/pdf/manual/data_pdf_manual.pdf'
USER_AGENT = 'KeibaResultMaintenance/1.0 (+https://github.com/sakaraa3291/sakaraa3291.github.io)'
INTERVAL = 10
ZIP_LIMIT = 64 * 1024 * 1024
UNPACKED_LIMIT = 256 * 1024 * 1024
FILES = ('racelist', 'horselist', 'payback')


def months(start, end):
    current = start.replace(day=1)
    while current <= end:
        yield current
        current = date(current.year + (current.month == 12), current.month % 12 + 1, 1)


def zip_members(archive, month):
    prefix = month.strftime('%Y%m')
    expected = {f'{prefix}_{kind}.csv': kind for kind in FILES}
    result = {}
    total = 0
    for item in archive.infolist():
        if item.is_dir():
            continue
        kind = expected.get(item.filename)
        if not kind or kind in result or item.flag_bits & 1:
            raise ValueError(f'unexpected or repeated ZIP member for {prefix}: {item.filename}')
        total += item.file_size
        if total > UNPACKED_LIMIT:
            raise ValueError(f'unpacked limit exceeded for {prefix}')
        result[kind] = item
    if set(result) != set(FILES):
        raise ValueError(f'missing NAR CSV members for {prefix}: {sorted(set(FILES) - set(result))}')
    return result


def completed(path, receipt, required):
    if not path.is_file() or not receipt:
        return False
    if receipt.get('covered_through', '') < required.isoformat():
        return False
    return hashlib.sha256(path.read_bytes()).hexdigest() == receipt.get('sha256')


def download(source_dir, start, through):
    import requests

    ready = (datetime.now(JST) - timedelta(hours=2)).date() - timedelta(days=1)
    if not date(2021, 1, 1) <= start <= through <= ready:
        raise ValueError(f'use completed JST dates from 2021 through the published monthly cutoff {ready}')
    source_dir.mkdir(parents=True, exist_ok=True)
    catalog = source_dir / 'downloads.json'
    lock = source_dir / '.download.lock'
    with lock.open('x', encoding='ascii') as handle:
        handle.write(datetime.now(JST).isoformat() + '\n')
    try:
        records = json.loads(catalog.read_text(encoding='utf-8')) if catalog.is_file() else {}
        last_request = None
        failures = {}
        targets = list(months(start, through))
        counts = {'expected': len(targets), 'cached': 0, 'downloaded': 0}
        with requests.Session() as session:
            session.headers['User-Agent'] = USER_AGENT
            for month in targets:
                label = month.strftime('%Y-%m')
                end = date(month.year, month.month, monthrange(month.year, month.month)[1])
                required = min(end, through)
                path = source_dir / f'{label}.zip'
                record = records.setdefault(label, {})
                if completed(path, record.get('archive'), required):
                    counts['cached'] += 1
                    continue
                if last_request is not None:
                    time.sleep(max(0, INTERVAL - (time.monotonic() - last_request)))
                now = datetime.now(JST)
                if record.get('last_attempt', {}).get('jst_date') == now.date().isoformat():
                    failures[label] = 'this file has already been requested today (JST)'
                    continue
                attempt = {'jst_date': now.date().isoformat(), 'at': now.isoformat(), 'status': 'started'}
                record['last_attempt'] = attempt
                write_json(catalog, records)
                last_request = time.monotonic()
                stop = False
                try:
                    with session.get(MONTHLY, params={'k_month': month.month, 'k_year': month.year,
                                                    'type': 'monthly'}, timeout=(10, 90),
                                     allow_redirects=False, stream=True) as response:
                        if response.status_code != 200:
                            stop = response.status_code in {401, 403, 429, 503}
                            raise ValueError(f'HTTP {response.status_code}')
                        data = io.BytesIO()
                        for chunk in response.iter_content(65536):
                            if data.tell() + len(chunk) > ZIP_LIMIT:
                                raise ValueError('ZIP exceeds the size limit')
                            data.write(chunk)
                        with ZipFile(data) as archive:
                            zip_members(archive, month)
                            if archive.testzip() is not None:
                                raise ValueError('invalid ZIP checksum')
                        content = data.getvalue()
                        atomic_write(path, content)
                        record['archive'] = {'covered_through': min(end, (now - timedelta(hours=2)).date() - timedelta(days=1)).isoformat(),
                                             'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content),
                                             'received_at': datetime.now(JST).isoformat(), 'source': response.url}
                        attempt['status'] = 'complete'
                        counts['downloaded'] += 1
                except (OSError, ValueError, BadZipFile, requests.RequestException) as exc:
                    attempt.update(status='failed', error=str(exc))
                    failures[label] = str(exc)
                finally:
                    write_json(catalog, records)
                print(json.dumps({'month': label, 'status': attempt['status'],
                                  'downloaded': counts['downloaded'], 'error': attempt.get('error')}), flush=True)
                if stop:
                    break
        return counts | {'failures': failures}
    finally:
        lock.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__, epilog=f'The publisher documents the download limits at {GUIDE}.')
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--from', dest='start', type=date.fromisoformat, default=date(2021, 1, 1))
    parser.add_argument('--through', type=date.fromisoformat, default=datetime.now(JST).date() - timedelta(days=1))
    args = parser.parse_args()
    report = download(args.source, args.start, args.through)
    print(json.dumps(report, ensure_ascii=False))
    return bool(report['failures'])


if __name__ == '__main__':
    raise SystemExit(main())
