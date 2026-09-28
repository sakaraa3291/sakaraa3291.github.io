import copy
import json
from datetime import date, datetime
from pathlib import Path

import pytest

from automation.racecard.core import digest, grade, reconcile, target_date, validate_race
from automation.racecard.guard import allowed, assert_current
from automation.racecard.run import ROOT, enrich, prepare, publish, tree_hash
from automation.racecard.sources import jra_discover, nar_calendar, nar_list, page, parse_jra, parse_jra_history, parse_nar

FIX = Path(__file__).with_name('fixtures')
STAMP = '2026-09-23T12:00:00+09:00'


def fixture(name):
    return (FIX / (name + '.html')).read_text()


def jra():
    r = parse_jra(fixture('jra-card'), '202606040711', date(2026, 9, 22), STAMP)
    history = parse_jra_history(fixture('jra-past5'), r)
    for h in r['horses']:
        h.update(history[h['horse_id']])
    enrich(r, ROOT)
    return r


def nar():
    target = date(2026, 9, 23)
    meetings = nar_calendar(fixture('nar-calendar'), target)
    items = nar_list(fixture('nar-list'), next(m for m in meetings if m['code'] == '18'), target)
    r = parse_nar(fixture('nar-card'), items[0], target, STAMP)
    enrich(r, ROOT)
    return r


@pytest.mark.parametrize('utc,expected', [('2026-09-22T12:00:00+00:00', '2026-09-23'),
    ('2026-09-22T22:00:00+00:00', '2026-09-23'), ('2026-09-23T02:30:00+00:00', '2026-09-23'),
    ('2026-12-31T12:00:00+00:00', '2027-01-01')])
def test_jst(utc, expected):
    assert str(target_date(now=datetime.fromisoformat(utc))) == expected


def test_delayed_schedule_and_dispatch():
    now = datetime.fromisoformat('2026-09-24T00:20:00+09:00')
    assert str(target_date(now=now, schedule='0 12 * * *')) == '2026-09-24'
    assert str(target_date('2026-01-01', now)) == '2026-01-01'
    with pytest.raises(ValueError):
        target_date('2026-02-30')


@pytest.mark.parametrize('marker', ['CAPTCHA', 'challenge-platform', 'verify you are human', 'Just a moment'])
def test_challenges(marker):
    with pytest.raises(ValueError):
        page(fixture('jra-card').replace('</body>', marker + '</body>'))


def test_wrong_date_and_truncation():
    with pytest.raises(ValueError):
        parse_jra(fixture('jra-card'), '202606040711', date(2026, 9, 21), STAMP)
    with pytest.raises(ValueError):
        page(fixture('nar-card')[:-1000])


def test_scope_jra_ids():
    ids = jra_discover(fixture('jra-list'), date(2026, 9, 22))
    assert ids == [f'2026060407{i:02d}' for i in range(1, 13)]
    from automation.keiba_update_pkg.tools.discover_race_ids import validate_day
    with pytest.raises(RuntimeError):
        validate_day(fixture('jra-list'), ids + ['202606040511'], date(2026, 9, 22))


def test_empty_jra():
    assert jra_discover(fixture('jra-empty'), date(2026, 9, 23)) == []


@pytest.mark.parametrize('get_race', [jra, nar])
def test_real_schema_and_count(get_race):
    r = get_race()
    validate_race(r)
    r['horses'].pop()
    with pytest.raises(ValueError, match='partial'):
        validate_race(r)


def test_unpublished_is_valid():
    r = nar()
    assert all(h['body_weight'] is None and h['availability']['body_weight'] == 'not_published' for h in r['horses'])
    for h in r['horses']:
        for k in ('win_odds', 'popularity'):
            h[k] = None
            h['availability'][k] = 'not_published'
    validate_race(r)


def test_dynamic_js_placeholder_not_unpublished():
    r = jra()
    assert r['horses'][0]['win_odds'] is None
    assert r['horses'][0]['availability']['win_odds'] == 'not_available'


def test_jra_body_weight_previous_unavailable():
    soup = page(fixture('jra-card'))
    cell = soup.select_one('tr.HorseList .Weight')
    cell.string = '532'
    comparison = soup.new_tag('small')
    comparison.string = '(前計不)'
    cell.append(comparison)
    r = parse_jra(str(soup), '202606040711', date(2026, 9, 22), STAMP)
    assert len(r['horses']) == 16
    horse = r['horses'][0]
    assert horse['entry_status'] == 'active'
    assert horse['body_weight'] == 532
    assert horse['availability']['body_weight'] == 'available'
    assert horse['body_weight_diff'] is None
    assert horse['availability']['body_weight_diff'] == 'not_available'
    for key in ('body_weight', 'body_weight_diff'):
        assert horse['observed_at'][key] == STAMP


@pytest.mark.parametrize('raw,weight,diff,status', [
    ('532(+4)', 532, 4, 'active'), ('532(-2)', 532, -2, 'active'),
    ('532', 532, None, 'active'), ('計不', None, None, 'active'),
    ('取消', None, None, 'scratched'), ('除外', None, None, 'excluded')])
def test_jra_body_weight_existing_forms(raw, weight, diff, status):
    soup = page(fixture('jra-card'))
    soup.select_one('tr.HorseList .Weight').string = raw
    r = parse_jra(str(soup), '202606040711', date(2026, 9, 22), STAMP)
    horse = r['horses'][0]
    assert horse['entry_status'] == status
    for key, value in [('body_weight', weight), ('body_weight_diff', diff)]:
        assert horse[key] == value
        assert horse['availability'][key] == ('available' if value is not None else 'not_available')
        assert horse['observed_at'][key] == STAMP


@pytest.mark.parametrize('raw', ['不明', '532(不明)', '532(前計不)extra'])
def test_jra_unknown_body_weight_fails(raw):
    soup = page(fixture('jra-card'))
    soup.select_one('tr.HorseList .Weight').string = raw
    with pytest.raises(ValueError, match='unknown body weight:'):
        parse_jra(str(soup), '202606040711', date(2026, 9, 22), STAMP)


@pytest.mark.parametrize('key,selector', [
    ('win_odds', '[id^="odds-"]'), ('popularity', '[id^="ninki-"]')])
def test_jra_missing_dynamic_node(key, selector):
    soup = page(fixture('jra-card'))
    row = soup.select_one('tr.HorseList')
    row.select_one(selector).decompose()
    r = parse_jra(str(soup), '202606040711', date(2026, 9, 22), STAMP)
    assert len(r['horses']) == 16
    horse = r['horses'][0]
    assert horse['horse_number'] == 1
    assert horse['entry_status'] == 'active'
    assert horse[key] is None
    assert horse['availability'][key] == 'not_available'


def test_jra_scratched_missing_both_dynamic_nodes():
    soup = page(fixture('jra-card'))
    row = soup.select_one('tr.HorseList')
    row['class'].append('Cancel')
    for selector in ('[id^="odds-"]', '[id^="ninki-"]'):
        row.select_one(selector).decompose()
    r = parse_jra(str(soup), '202606040711', date(2026, 9, 22), STAMP)
    assert len(r['horses']) == 16
    horse = r['horses'][0]
    assert horse['horse_number'] == 1
    assert horse['entry_status'] == 'scratched'
    for key in ('win_odds', 'popularity'):
        assert horse[key] is None
        assert horse['availability'][key] == 'not_available'


def test_jra_missing_jockey_identity_fails():
    soup = page(fixture('jra-card'))
    soup.select_one('tr.HorseList .Jockey a').decompose()
    with pytest.raises(ValueError, match='missing ID link'):
        parse_jra(str(soup), '202606040711', date(2026, 9, 22), STAMP)


def test_jra_partial_active_horse_odds_fails():
    from automation.racecard.sources import apply_odds
    r = jra()
    actual = json.loads((FIX/'jra-odds.json').read_text())
    horse = r['horses'][0]
    assert horse['entry_status'] == 'active'
    del actual['data']['odds']['1'][str(horse['horse_number']).zfill(2)]
    with pytest.raises(ValueError, match='partial active-horse odds'):
        apply_odds(r, actual, 'https://race.netkeiba.com/api/api_get_jra_odds.html')


def test_actual_odds_and_prediction_separation():
    from automation.racecard.sources import apply_odds
    r = jra()
    actual = json.loads((FIX/'jra-odds.json').read_text())
    apply_odds(r, actual, 'https://race.netkeiba.com/api/api_get_jra_odds.html')
    assert r['horses'][0]['win_odds'] == 42.8
    assert r['horses'][0]['popularity'] == 13
    validate_race(r)
    apply_odds(r, {'status':'yoso'}, 'https://race.netkeiba.com/api/api_get_jra_odds.html')
    assert r['horses'][0]['win_odds'] is None
    assert r['horses'][0]['availability']['win_odds'] == 'not_published'
    with pytest.raises(ValueError):
        apply_odds(r, {'status':'NG'}, 'https://race.netkeiba.com/api/api_get_jra_odds.html')


def test_scratched_jockey_and_weight_changes():
    old = jra()
    new = copy.deepcopy(old)
    new['horses'][0]['entry_status'] = 'scratched'
    new['horses'][1]['jockey_id'] = '99999'
    new['horses'][1]['carried_weight'] = 55.0
    new['start_time'] = '2026-09-22T15:35:00+09:00'
    reconcile(new, old)
    assert {c['field'] for c in new['changes']} == {'entry_status', 'jockey_id', 'carried_weight', 'start_time'}
    assert len(new['horses']) == len(old['horses'])
    validate_race(new)
    new['horses'].pop()
    with pytest.raises(ValueError, match='disappeared'):
        reconcile(new, old)


def test_parser_preserves_scratched_and_jockey_identity():
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(fixture('jra-card'), 'html.parser')
    row = soup.select_one('tr.HorseList')
    row.find_all('td', recursive=False)[8].string = '取消'
    row.select_one('.Jockey a')['href'] = 'https://db.netkeiba.com/jockey/result/recent/99999/'
    r = parse_jra(str(soup), '202606040711', date(2026,9,22), STAMP)
    assert len(r['horses']) == 16
    assert r['horses'][0]['entry_status'] == 'scratched'
    assert r['horses'][0]['jockey_id'] == '99999'


def test_history_cache_reuses_same_horse_day(monkeypatch):
    from automation.racecard import run
    class Fake:
        def __init__(self): self.history_calls = 0
        def get(self, url):
            if 'shutuba_past' in url:
                self.history_calls += 1
                return fixture('jra-past5')
            return fixture('jra-card')
        def odds(self, rid):
            return json.loads((FIX/'jra-odds.json').read_text()), 'https://race.netkeiba.com/api/api_get_jra_odds.html'
    monkeypatch.setattr(run, 'jra_discover', lambda html, target: ['202606040711'])
    cache, fetch = {}, Fake()
    run.collect_jra(fetch, date(2026,9,22), cache, STAMP)
    run.collect_jra(fetch, date(2026,9,22), cache, STAMP.replace('12:00', '13:00'))
    assert fetch.history_calls == 1


@pytest.mark.parametrize('value,result', [('JpnⅠ','JpnI'), ('JpnⅡ','JpnII'), ('JpnⅢ','JpnIII'),
    ('JpnIII３上','JpnIII'), ('S1',None), ('H2',None), ('重賞',None), ('一般戦',None)])
def test_only_jpn(value,result):
    assert grade(value) == result


def test_no_changes_and_atomic_publication(tmp_path):
    r = nar()
    source = {'JRA': {'status': 'complete'}, 'NAR': {'status': 'complete'}}
    day = date(2026,9,23)
    candidate = prepare(tmp_path, day, [r], source, STAMP)
    publish(candidate, tmp_path/'prediction-data')
    before = tree_hash(tmp_path/'prediction-data')
    newer = copy.deepcopy(r)
    newer['fetched_at'] = '2026-09-23T13:00:00+09:00'
    candidate = prepare(tmp_path, day, [newer], source, newer['fetched_at'])
    assert tree_hash(candidate) == before
    publish(candidate, tmp_path/'prediction-data')
    assert tree_hash(tmp_path/'prediction-data') == before
    broken = copy.deepcopy(r)
    broken['horses'].pop()
    with pytest.raises(ValueError):
        prepare(tmp_path, day, [broken], source, STAMP)
    assert tree_hash(tmp_path/'prediction-data') == before


def test_no_publishing_partial_sources(tmp_path):
    with pytest.raises(ValueError, match='partial source'):
        prepare(tmp_path, date(2026,9,23), [], {'JRA': {'status':'complete'}, 'NAR':{'status':'failed'}}, STAMP)
    assert not (tmp_path/'prediction-data').exists()


def test_stale_pages_and_commit_paths():
    with pytest.raises(ValueError, match='stale checkout'):
        assert_current('old', 'new')
    assert_current('same', 'same')
    assert allowed('prediction-data/latest.json')
    assert allowed('automation/racecard-state/cache.json')
    for p in ['lapdata.json', 'pedigree_stats.json', 'courses.json', 'elevation.json', 'index.html',
              'sw.js', 'automation/state/manifest.json', 'prediction-data/../../index.html']:
        assert not allowed(p)
