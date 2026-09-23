from __future__ import annotations

import json
import re
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from .core import JST, PREDICTIONS, dynamic, grade, normalized, require

NAR = 'https://www.keiba.go.jp'
JRA_VENUES = dict(zip(range(1, 11), ['札幌', '函館', '福島', '新潟', '東京', '中山', '中京', '京都', '阪神', '小倉']))


def text(node):
    return node.get_text(' ', strip=True) if node else ''


def page(html):
    low = html.lower()
    require('</html>' in low and '</body>' in low, 'truncated HTML')
    require(not any(x in low for x in ('captcha', 'challenge-platform', 'verify you are human', 'just a moment')),
            'CAPTCHA/bot challenge')
    soup = BeautifulSoup(html, 'html.parser')
    require(soup.title is not None, 'missing title')
    require(not any(x in text(soup.title).lower() for x in ('login', 'ログイン', 'メンテナンス', 'エラー')),
            'login/maintenance/error page')
    return soup


class Fetcher:
    def __init__(self, diagnostics):
        self.session = requests.Session()
        self.session.headers['User-Agent'] = 'Mozilla/5.0 (compatible; racecard-data/1.0; +https://sakaraa3291.github.io/)'
        self.diagnostics = Path(diagnostics)
        self.diagnostics.mkdir(parents=True, exist_ok=True)
        self.count = 0

    def get(self, url):
        time.sleep(.6)
        # Never follow redirects to login, another race, or another host.
        r = self.session.get(url, timeout=(15, 60), allow_redirects=False)
        require(r.status_code == 200, f'HTTP {r.status_code}: {url}')
        require('html' in r.headers.get('Content-Type', ''), f'not HTML: {url}')
        html = r.content.decode('utf-8', errors='strict')
        self.count += 1
        (self.diagnostics / f'{self.count:04d}.html').write_text(html)
        with (self.diagnostics / 'fetch.jsonl').open('a') as f:
            f.write(json.dumps({'url': url, 'fetched_at': datetime.now(JST).isoformat(), 'file': f'{self.count:04d}.html'}) + '\n')
        page(html)
        return html

    def odds(self, rid):
        time.sleep(.6)
        url = f'https://race.netkeiba.com/api/api_get_jra_odds.html?race_id={rid}&type=1&action=init&compress=0'
        response = self.session.get(url, timeout=(15, 60), allow_redirects=False)
        require(response.status_code == 200, f'odds HTTP {response.status_code}: {rid}')
        data = response.json()
        self.count += 1
        (self.diagnostics / f'{self.count:04d}-odds.json').write_text(json.dumps(data, ensure_ascii=False))
        return data, url


def apply_odds(race, response, url):
    status = response.get('status')
    require(status in ('result', 'middle', 'yoso'), f'odds acquisition failed: {status}')
    if status == 'yoso':
        # The provider's predicted odds are not observed betting facts.
        for h in race['horses']:
            for key in ('win_odds', 'popularity'):
                dynamic(h, key, None, race['fetched_at'], 'not_published')
        race['odds_source'] = dict(source_url=url, status='not_published', fetched_at=race['fetched_at'])
        return
    data = response['data']
    updated = datetime.strptime(data['official_datetime'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=JST)
    require(updated.date() <= date.fromisoformat(race['target_date']), 'odds from later date')
    require(updated.date() >= date.fromisoformat(race['target_date']) - __import__('datetime').timedelta(days=2), 'stale odds date')
    values = data['odds']['1']
    numbers = {h['horse_number'] for h in race['horses']}
    require(set(map(int, values)) <= numbers, 'odds for unknown horse')
    for h in race['horses']:
        value = values.get(str(h['horse_number']).zfill(2))
        require(value is not None or h['entry_status'] != 'active', 'partial active-horse odds')
        for key, offset, integer in [('win_odds', 0, False), ('popularity', 2, True)]:
            number = optional_number(str(value[offset]), integer) if value and h['entry_status'] == 'active' else None
            require(number is None or number > 0, 'invalid zero odds/popularity')
            dynamic(h, key, number, race['fetched_at'], 'not_available')
            h.setdefault('updated_at', {})[key] = updated.isoformat()
    race['odds_source'] = dict(source_url=url, status=status, fetched_at=race['fetched_at'], updated_at=updated.isoformat())


def jra_discover(html, target):
    from ..keiba_update_pkg.tools.discover_race_ids import parse_ids, validate_day
    ids = parse_ids(html, target)
    validate_day(html, ids, target)
    soup = page(html)
    tabs = soup.select(f'.jyo_tab li[data-kaisaidate="{target:%Y%m%d}"]')
    if ids:
        venues = {int(re.fullmatch(r'cd(\d{2})', tab['id'])[1]) for tab in tabs}
        require(venues == {int(rid[4:6]) for rid in ids}, 'missing JRA meeting')
    return ids


def base_race(org, rid, source_id, source, url, target, stamp):
    return dict(schema_version=1, race_id=rid, source_race_id=source_id,
                organization=org, source_name=source, source_url=url, fetched_at=stamp,
                target_date=target.isoformat(), race_status='scheduled', grade=None,
                horses=[], changes=[])


def base_horse(hid, name, namespace):
    return dict(horse_id=hid, horse_name=name, id_namespace=namespace,
                normalized_name=normalized(name), entry_status='active',
                past_performances=[], history_availability='not_fetched',
                pedigree=None, predictions={k: None for k in PREDICTIONS})


def source_id(node, pattern):
    require(node is not None, f'missing ID link {pattern}')
    m = re.search(pattern, node.get('href', ''))
    require(m is not None, f'ID unavailable/malformed {pattern}')
    return m[1]


def optional_number(value, integer=False):
    value = normalized(value)
    if value in ('', '--', '---', '---.-', '**', '未発表', '計不', '-', '取消', '除外'):
        return None
    require(bool(re.fullmatch(r'[+-]?\d+(?:\.\d+)?', value)), f'invalid number: {value}')
    return int(value) if integer else float(value)


def weight_fields(horse, raw, stamp):
    raw = normalized(raw).replace('kg', '')
    m = re.fullmatch(r'(\d{3})(?:\(([+-]?\d+)\))?', raw)
    if m:
        dynamic(horse, 'body_weight', int(m[1]), stamp)
        dynamic(horse, 'body_weight_diff', int(m[2]) if m[2] else None, stamp,
                'not_available')
    else:
        require(raw in ('', '--', '---', '計不', '取消', '除外', '-'), f'unknown body weight: {raw}')
        reason = 'not_available' if raw == '計不' or horse['entry_status'] != 'active' else 'not_published'
        dynamic(horse, 'body_weight', None, stamp, reason)
        dynamic(horse, 'body_weight_diff', None, stamp, reason)


def jra_identity(soup, rid, target):
    venue = JRA_VENUES[int(rid[4:6])]
    title = normalized(text(soup.title))
    require(f'{target.year}年{target.month}月{target.day}日{venue}{int(rid[-2:])}R' in title,
            f'wrong date/venue/race number: {title}')
    require(soup.select_one('.RaceList_NameBox .RaceName') is not None, 'missing race heading')
    require(soup.select_one(f'.MyRace-Item-{rid}') is not None, 'race ID/heading mismatch')
    require(venue in text(soup.select_one('.RaceData02')), 'venue/body mismatch')
    return venue


def parse_jra(html, rid, target, stamp):
    soup = page(html)
    venue = jra_identity(soup, rid, target)
    race = base_race('JRA', rid, rid, 'netkeiba JRA',
                     f'https://race.netkeiba.com/race/shutuba.html?race_id={rid}', target, stamp)
    race.update(venue=venue, race_number=int(rid[-2:]), race_name=text(soup.select_one('.RaceName')))
    details = normalized(text(soup.select_one('.RaceData01')))
    m = re.search(r'(\d{2}:\d{2})発走.*?([芝ダ障])(\d+)m', details)
    require(m is not None, 'missing start time/distance')
    race.update(start_time=f'{target}T{m[1]}:00+09:00', surface={'芝': 'turf', 'ダ': 'dirt', '障': 'jump'}[m[2]], distance_m=int(m[3]))
    head = text(soup.select_one('.RaceList_NameBox'))
    if '中止' in head or '取消' in head:
        race['race_status'] = 'cancelled'
    count = re.search(r'(\d+)頭', text(soup.select_one('.RaceData02')))
    require(count is not None, 'missing declared field size')
    race['declared_entry_count'] = int(count[1])
    for key, label in [('weather', '天候'), ('going', '馬場')]:
        match = re.search(label + r':([^/\s]+)', details)
        value = match[1] if match and match[1] not in ('-', '--') else None
        dynamic(race, key, value, stamp)
    table = soup.select_one('table.Shutuba_Table')
    require(table is not None, 'missing racecard table')
    for row in table.select('tr.HorseList'):
        cells = row.find_all('td', recursive=False)
        require(len(cells) >= 11, 'partial horse row')
        link = row.select_one('.HorseName a[href]')
        horse = base_horse(source_id(link, r'/horse/(\d+)'), text(link), 'netkeiba')
        status_text = ' '.join(row.get('class', [])) + ' ' + text(cells[0]) + ' ' + text(cells[1]) + ' ' + text(cells[8])
        if '取消' in text(row) or 'Cancel' in status_text:
            horse['entry_status'] = 'scratched'
        if '除外' in text(row):
            horse['entry_status'] = 'excluded'
        jockey = row.select_one('.Jockey a[href]')
        trainer = row.select_one('.Trainer a[href]')
        horse.update(gate_number=optional_number(text(cells[0]), True), horse_number=int(text(cells[1])),
                     sex_age=text(cells[4]), carried_weight=float(text(cells[5])),
                     jockey_id=source_id(jockey, r'/jockey/(?:result/recent/)?(\d+)'), jockey_name=text(jockey),
                     trainer_id=source_id(trainer, r'/trainer/(?:result/recent/)?(\d+)'), trainer_name=text(trainer))
        weight_fields(horse, text(cells[8]), stamp)
        for key, selector, integer in [('win_odds', '[id^="odds-"]', False), ('popularity', '[id^="ninki-"]', True)]:
            node = row.select_one(selector)
            require(node is not None, f'missing dynamic cell: {key}')
            # A JS placeholder is not evidence that betting has not opened.
            dynamic(horse, key, optional_number(text(node), integer), stamp, 'not_available')
        race['horses'].append(horse)
    return race


def parse_jra_history(html, race):
    soup = page(html)
    target = date.fromisoformat(race['target_date'])
    jra_identity(soup, race['source_race_id'], target)
    table = soup.select_one('table.Shutuba_Past5_Table')
    require(table is not None, 'history table absent')
    rows = table.select('tr.HorseList')
    out = {}
    for row in rows:
        link = row.select_one('.Horse02 a[href]')
        hid = source_id(link, r'/horse/(\d+)')
        runs = []
        cells = row.find_all('td', recursive=False)[5:]
        require(len(cells) in (5, 9), 'incomplete history columns')
        for cell in cells:
            anchor = cell.select_one('.Data02 a[href*="/race/"]')
            if anchor is None:
                # Rest intervals and debut cells are not starts.
                require(not re.search(r'\d{4}\.\d{2}\.\d{2}', text(cell)), 'dated history missing race ID')
                continue
            old_id = source_id(anchor, r'/race/(\d{12})')
            if text(cell.select_one('.Num')) in ('除', '除外', '取消', '取'):
                continue
            first = text(cell.select_one('.Data01'))
            dm = re.search(r'(\d{4})\.(\d{2})\.(\d{2})\s*(\S+)', first)
            require(dm is not None, 'history date absent')
            day = '-'.join(dm.group(i) for i in (1, 2, 3))
            require(day < race['target_date'], 'history lookahead')
            details = text(cell.select_one('.Data05'))
            dist = re.search(r'([芝ダ障])(\d+)', details)
            perf = text(cell.select_one('.Data06'))
            jm = re.search(r'人\s*(.*?)\s+(\d+(?:\.\d+)?)$', text(cell.select_one('.Data03')))
            passage = re.search(r'(?<!\d)(\d+(?:-\d+)+)', perf)
            late = re.search(r'\((\d+\.\d+)\)', perf)
            runs.append(dict(race_id=old_id, date=day, venue=dm[4], race_name=text(anchor),
                             rank=text(cell.select_one('.Num')), distance_m=int(dist[2]) if dist else None,
                             surface={'芝': 'turf', 'ダ': 'dirt', '障': 'jump'}.get(dist[1]) if dist else None,
                             jockey_id=None, jockey_name=jm[1] if jm else None,
                             carried_weight=float(jm[2]) if jm else None,
                             passage=passage[1] if passage else None, last_3f=float(late[1]) if late else None,
                             source_url=anchor['href'], raw=text(cell)))
        pedigree = {key: text(row.select_one(sel)).strip('()') or None for key, sel in
                    [('sire', '.Horse01'), ('dam', '.Horse03'), ('damsire', '.Horse04')]}
        out[hid] = {'past_performances': runs[:5], 'pedigree': pedigree, 'history_availability': 'available' if runs else 'no_starts',
                    'history_source_url': f'https://race.netkeiba.com/race/shutuba_past.html?race_id={race["source_race_id"]}',
                    'history_fetched_at': race['fetched_at']}
    require(set(out) == {h['horse_id'] for h in race['horses']}, 'history/card horse ID mismatch')
    return out


def nar_params(url, target=None):
    q = parse_qs(urlsplit(url).query)
    require(all(len(v) == 1 for v in q.values()), 'duplicate query parameters')
    require('k_raceDate' in q and 'k_babaCode' in q, 'NAR identity missing')
    if target:
        require(q['k_raceDate'][0] == target.strftime('%Y/%m/%d'), 'NAR wrong date')
    return {k: v[0] for k, v in q.items()}


def nar_calendar(html, target):
    soup = page(html)
    require('月別開催日程' in text(soup.title), 'wrong NAR calendar')
    require(f'{target.year}年{target.month}月分' in text(soup), 'wrong calendar month')
    table = soup.select_one('table.schedule')
    require(table is not None, 'missing calendar')
    rows = [r for r in table.select('tr') if text(r.find('td'))]
    require(len(rows) == 17, 'incomplete calendar venue rows')
    meetings = []
    import calendar
    for row in rows:
        cells = row.find_all('td', recursive=False)
        require(len(cells) == 33, 'partial calendar day columns')
        cell = cells[target.day]
        label = text(cell)
        if not label:
            continue
        if label == '△':
            # Rescheduled day is no longer a meeting; the destination calendar day owns the race.
            continue
        require(label in ('●', '☆', 'Ｄ', 'D'), f'unknown calendar marker {label}')
        anchor = cell.select_one('a[href]')
        require(anchor is not None, f'NAR meeting not yet published: {text(cells[0])}')
        url = urljoin(NAR, anchor['href'])
        p = nar_params(url, target)
        meetings.append(dict(venue=text(cells[0]), code=p['k_babaCode'], url=url, expects_jpn=label in ('Ｄ', 'D')))
    require(len({m['code'] for m in meetings}) == len(meetings), 'duplicate calendar venue')
    return meetings


def nar_list(html, meeting, target):
    soup = page(html)
    table = soup.select_one('table')
    require(table is not None, 'NAR race table absent')
    heading = normalized(text(table.select_one('th')))
    require(f'{target.year}年{target.month}月{target.day}日' in heading and normalized(meeting['venue']) + '競馬' in heading,
            'NAR list wrong date/venue')
    rows = table.select('tr.data')
    require(len(rows) >= 1, 'empty NAR meeting')
    numbers, races = [], []
    for row in rows:
        cells = row.find_all('td', recursive=False)
        require(len(cells) == 10, 'partial NAR list row')
        num = re.fullmatch(r'(\d+)R', text(cells[0]))
        require(num is not None, 'invalid race number')
        numbers.append(int(num[1]))
        anchor = cells[4].select_one('a[href*="DebaTable"]')
        require(anchor is not None, 'missing NAR race link')
        url = urljoin(NAR, anchor['href'])
        p = nar_params(url, target)
        require(p['k_babaCode'] == meeting['code'] and int(p['k_raceNo']) == int(num[1]), 'NAR list identity mismatch')
        g = grade(text(anchor))
        if g:
            races.append(dict(url=url, venue=meeting['venue'], code=meeting['code'], race_number=int(num[1]),
                              grade=g, count=int(text(cells[8])), start=text(cells[1]), course=text(cells[5])))
    require(numbers == list(range(1, max(numbers) + 1)), 'partial NAR race list')
    # Header-to-menu race count is checked independently through the race navigation links.
    nav = {int(nar_params(urljoin(NAR, a['href']), target)['k_raceNo']) for a in soup.select('a[href*="DebaTable"]')}
    require(nav == set(numbers), 'NAR race navigation mismatch')
    require(not meeting['expects_jpn'] or races, 'calendar Jpn race missing; possible change/cancellation requires review')
    return races


def parse_nar(html, item, target, stamp):
    soup = page(html)
    p = nar_params(item['url'], target)
    sid = f'{target:%Y%m%d}-{p["k_babaCode"]}-{int(p["k_raceNo"]):02d}'
    race = base_race('NAR', 'nar-' + sid, sid, 'NAR official', item['url'], target, stamp)
    header = normalized(text(soup.select_one('h4')))
    require(f'{target.year}年{target.month}月{target.day}日' in header and normalized(item['venue']) in header
            and f'第{item["race_number"]}競走' in header, 'NAR card date/venue/number mismatch')
    start = re.search(r'(\d{2}:\d{2})発走', header)
    require(start is not None and start[1] == item['start'], 'NAR start time/list mismatch')
    name = text(soup.select_one('h3'))
    require(grade(name) == item['grade'], 'NAR grade mismatch')
    # Limit condition parsing to the metadata before the horse table.
    table = soup.select_one('table')
    require(table is not None, 'missing NAR card table')
    full = normalized(text(soup))
    meta = full.split('対戦表')[0]
    distance = re.search(r'(ダート|芝)(\d+)m', meta)
    require(distance is not None and str(distance[2]) in item['course'], 'NAR distance mismatch')
    race.update(venue=item['venue'], race_number=item['race_number'], race_name=name, grade=item['grade'],
                start_time=f'{target}T{start[1]}:00+09:00', surface='dirt' if distance[1] == 'ダート' else 'turf',
                distance_m=int(distance[2]), declared_entry_count=item['count'])
    if '競走中止' in meta or '開催中止' in meta or '競走取消' in meta:
        race['race_status'] = 'cancelled'
    for key, label in [('weather', '天候'), ('going', '馬場')]:
        m = re.search(label + r':(.*?)(?=馬場:|サラブレッド|サラ系|\*|$)', meta)
        value = m[1] if m and m[1] not in ('', '-', '--') else None
        dynamic(race, key, value, stamp)
    rows = table.find('tbody').find_all('tr', recursive=False)
    starts = [i for i, row in enumerate(rows) if row.select_one('a.horseName')]
    previous_gate = None
    for index in starts:
        group = rows[index:index + 5]
        require(len(group) == 5 and not any(x.select_one('a.horseName') for x in group[1:]), 'partial NAR horse block')
        cells = [r.find_all('td', recursive=False) for r in group]
        if len(cells[0]) == 10 and group[0].select_one('.courseNum') is None:
            require(previous_gate is not None, 'missing first gate')
            cells[0].insert(0, previous_gate)
        require([len(c) for c in cells] == [11, 9, 8, 7, 8], 'NAR horse layout changed')
        previous_gate = cells[0][0]
        link = group[0].select_one('.horseName')
        h = base_horse(source_id(link, r'k_lineageLoginCode=(\d+)'), text(link), 'nar')
        jockey = group[0].select_one('.jockeyName')
        trainer = group[2].select_one('a[href*="TrainerMark"]')
        status = text(cells[4][2])
        h['entry_status'] = 'excluded' if '除外' in status else 'scratched' if '取消' in status else 'active'
        carried = re.search(r'(\d+(?:\.\d+)?)', text(cells[1][3]))
        require(carried is not None, 'missing carried weight')
        h.update(gate_number=int(text(cells[0][0])), horse_number=int(text(cells[0][1])),
                 sex_age=text(cells[1][0]), carried_weight=float(carried[1]),
                 jockey_id=source_id(jockey, r'k_riderLicenseNo=(\d+)'), jockey_name=text(jockey).split('（')[0].strip(),
                 trainer_id=source_id(trainer, r'k_trainerLicenseNo=(\d+)'), trainer_name=text(trainer).split('（')[0].strip())
        odds = cells[0][4]
        odd = re.search(r'(\d+\.\d+)', text(odds))
        pop = re.search(r'(\d+)人気', text(odds))
        dynamic(h, 'win_odds', float(odd[1]) if odd else None, stamp)
        dynamic(h, 'popularity', int(pop[1]) if pop else None, stamp)
        weight_fields(h, text(cells[2][2]), stamp)
        runs = []
        for col, info in enumerate(group[0].select('.raceInfo')):
            raw = ' | '.join(text(c[-5 + col]) for c in cells)
            dm = re.search(r'(\d{2})\.(\d{2})\.(\d{2})', text(info))
            if not dm:
                require(not text(info), 'unknown NAR history')
                continue
            if text(info.select_one('.pastRank')) in ('除外', '取消', '取', '除'):
                continue
            year = target.year // 100 * 100 + int(dm[1])
            if year > target.year:
                year -= 100
            day = date(year, int(dm[2]), int(dm[3])).isoformat()
            anchor = cells[1][-5 + col].select_one('a[href]')
            old_url = urljoin(NAR + '/KeibaWeb/TodayRaceInfo/DebaTable', anchor['href']) if anchor else None
            old_id = None
            if old_url:
                q = nar_params(old_url)
                old_id = 'nar-' + q['k_raceDate'].replace('/', '') + '-' + q['k_babaCode'] + '-' + q['k_raceNo'].zfill(2)
            dist = re.search(r'[左右直](\d+)', text(info))
            jm = re.search(r'人\s*\d+\s+(.*?)\s+(\d+(?:\.\d+)?)$', text(cells[2][-5 + col]))
            perf = text(cells[3][-5 + col])
            passage = re.search(r'\b(\d+(?:-\d+)+)\b', perf)
            late = re.search(r'\s(\d+\.\d+)$', perf)
            runs.append(dict(race_id=old_id, date=day, race_name=text(cells[1][-5 + col]),
                             rank=text(info.select_one('.pastRank')), distance_m=int(dist[1]) if dist else None,
                             jockey_id=None, jockey_name=jm[1] if jm else None,
                             carried_weight=float(jm[2]) if jm else None, passage=passage[1] if passage else None,
                             last_3f=float(late[1]) if late else None, source_url=old_url, raw=raw))
        h.update(past_performances=runs[:5], history_availability='available' if runs else 'no_starts',
                 history_source_url=item['url'], history_fetched_at=stamp,
                 pedigree=dict(sire=text(cells[2][0]), dam=text(cells[3][0]), damsire=text(cells[4][0]).strip('（）')))
        race['horses'].append(h)
    return race
