import csv
import gzip
import sys
from datetime import date
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

AUTOMATION = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(AUTOMATION), str(AUTOMATION / 'keiba_update_pkg/tools')]
from fetch_netkeiba_delta import parse_people, parse_results, race_course
from people import query, window
from people_state import MASTER, PAYOUT, PEOPLE, audit, by_runner, observation, observations, write_observations
from people_weekly import SUMMARY, build_snapshot, retry_results, retries_to_do

DAY = '2026-11-23'
RID, OTHER, LOCAL = '202605050801', '202605050802', '202654110101'
SOURCE = f'https://race.netkeiba.com/race/result.html?race_id={RID}'
STAMP = '2026-11-24T04:00:00+09:00'


def write_csv(path, rows, columns=None):
    with gzip.open(path, 'wt', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, columns or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def runner(rid, number, day=DAY, rank='1', org='中央', horse='123', **fields):
    result = {'race_id': rid, '日付': day, '中央地方': org, '馬番': str(number), '馬ID': horse,
              '騎手ID': '00123', '騎手': '騎手甲', '調教師': '', '着順': rank, 'タイム': '',
              '競馬場': '東京', '距離': '1600.0', 'クラス': '1勝', '馬場': '芝', '馬場状態': '良',
              '人気': '1', '単勝': '2.2', '枠番': '1', '脚質': '先行', '通過順': '2-2', '出走頭数': '6'}
    return result | fields


def observed(rid=RID, number=1, horse='123', day=DAY, **fields):
    return observation(rid, number, horse, day, SOURCE, STAMP, 'result', fields or {'trainer_id': '00012', 'trainer_name': '同じ名前'})


def payouts(rid, kind, horse, amount):
    return {'race_id': rid, '券種': kind, '組み合わせ': str(horse), '払戻金': str(amount)}


def test_course_jockey_trainer_and_odds_from_result_table():
    html = '''<div class="RaceData01">芝1600m (左 外 A)</div>
    <table><tr><th>着 順</th><th>枠</th><th>馬番</th><th>馬名</th><th>騎手</th><th>調教師</th>
    <th>タイム</th><th>単勝 オッズ</th><th>人 気</th></tr>
    <tr><td>1</td><td>2</td><td>1</td><td><a href="/horse/123/">馬</a></td>
    <td><a href="/jockey/result/recent/a0123/">騎手</a></td>
    <td><span>栗東</span><a href="https://db.netkeiba.com/trainer/result/recent/00012">調教師</a></td>
    <td>1:39.1</td><td>3.3</td><td>2</td></tr></table>'''
    soup = BeautifulSoup(html, 'lxml')
    _, entries = parse_results(soup, RID)
    row, = parse_people(soup, RID, {'date': DAY}, entries, STAMP, SOURCE)
    assert [row[k] for k in ('jockey_id', 'trainer_id', 'trainer_name', 'trainer_affiliation', 'popularity', 'win_odds', 'gate', 'course')] == [
        'a0123', '00012', '調教師', '栗東', '2', '3.3', '2', '左外A']
    assert race_course(BeautifulSoup('<div class="RaceData01">09:45 / ダ1150m 右\n / 稍 / 直線：弱追風</div>', 'lxml')) == '右'


def test_run_count_returns_and_unconfirmed_start_separation(tmp_path):
    entries = [runner(RID, 1), runner(RID, 2, rank='3', horse='124'),
               runner(RID, 3, rank='取消', horse='125'), runner(OTHER, 1, rank='中止', horse='126'),
               runner(OTHER, 2, rank='', horse='127'), runner(OTHER, 3, rank='', horse='128', 通過順='', 人気='', 単勝=''),
               runner(LOCAL, 1, org='地方')]
    write_csv(tmp_path / MASTER, entries)
    write_csv(tmp_path / PAYOUT, [payouts(RID, '単勝', 1, '1,500'), payouts(RID, '複勝', 1, 490)])
    supplement = by_runner([observed(), observed(number=2, horse='124', trainer_id='00013', trainer_name='同じ名前')])
    report = query(tmp_path / MASTER, tmp_path / PAYOUT, supplement,
                   start=DAY, end=DAY, group='total', by=('organization',))
    central, local = report['results']
    assert (central['starts'], central['first'], central['third'], central['outside_top3'], central['unknown_finish']) == (4, 1, 1, 1, 1)
    assert central['win'] == {'sample': 2, 'missing': 2, 'return_yen': 1500, 'return_pct': 750.0}
    assert central['place'] == {'sample': 2, 'missing': 2, 'return_yen': 490, 'return_pct': 245.0}
    assert local['place']['return_pct'] is None
    assert (report['coverage']['nonstarter'], report['coverage']['unresolved_start']) == (1, 1)
    pairs = query(tmp_path / MASTER, tmp_path / PAYOUT, supplement, start=DAY, end=DAY, group='pair')
    assert [x['trainer_id'] for x in pairs['results']] == ['00012', '00013']
    assert pairs['coverage']['missing_group_id'] == 3


def test_prior_form_never_includes_same_or_later_day(tmp_path):
    entries = [runner(RID, 1, day='2026-11-21', 脚質='逃げ'), runner(OTHER, 1, 脚質='追込'),
               runner('202605050803', 1, 脚質='差し'), runner('202605050901', 1, day='2026-11-24', 脚質='追込')]
    write_csv(tmp_path / MASTER, entries)
    write_csv(tmp_path / PAYOUT, [], ('race_id', '券種', '組み合わせ', '払戻金'))
    result = query(tmp_path / MASTER, tmp_path / PAYOUT, {}, start=DAY, end=DAY, group='total',
                   by=('prior_style',), prior=True)['results']
    assert [(row['prior_style'], row['starts'], row['prior_form_sample']) for row in result] == [('逃げ', 2, 2)]
    assert window(date(2026, 11, 24), period='1m', before=date(2026, 11, 24)) == ('2026-10-24', DAY)
    assert not by_runner([observed()], before='2026-11-24')


def test_weekly_snapshot_idempotent_and_failed_join_preserves_previous_state(tmp_path):
    write_csv(tmp_path / MASTER, [runner(RID, 1)])
    write_csv(tmp_path / PAYOUT, [payouts(RID, '単勝', 1, 200)])
    old = tmp_path / PEOPLE
    delta = tmp_path / 'delta.csv'
    write_observations(old, [observed()])
    write_observations(delta, [observed() | {'observed_at': '2026-11-25T01:00:00+09:00'}])
    first, second = tmp_path / 'first', tmp_path / 'second'
    for dest in [first, second]:
        report, _ = build_snapshot(tmp_path, tmp_path / MASTER, tmp_path / PAYOUT, DAY, [delta], dest)
        assert report['observations'] == 1
        assert report['results']['pair']['results'][0]['starts'] == 1
    assert (first / PEOPLE).read_bytes() == (second / PEOPLE).read_bytes() == old.read_bytes()
    assert (first / SUMMARY).read_bytes() == (second / SUMMARY).read_bytes()
    write_observations(delta, [observed(horse='999')])
    with pytest.raises(ValueError, match='identity changed'):
        build_snapshot(tmp_path, tmp_path / MASTER, tmp_path / PAYOUT, DAY, [delta], tmp_path / 'failed')
    assert not (tmp_path / 'failed').exists() and old.read_bytes() == (first / PEOPLE).read_bytes()
    with pytest.raises(ValueError, match='does not match master'):
        audit(tmp_path / MASTER, by_runner([observed(horse='999')]))


def test_duplicate_observation_and_invalid_payout_rejected(tmp_path):
    path = tmp_path / 'duplicate.csv'
    write_observations(path, [observed(), observed()])
    with pytest.raises(ValueError, match='duplicate observation'):
        observations([path])
    write_csv(tmp_path / MASTER, [runner(RID, 1)])
    write_csv(tmp_path / PAYOUT, [payouts(RID, '複勝', 7, 100)])
    with pytest.raises(ValueError, match='unverified starters'):
        query(tmp_path / MASTER, tmp_path / PAYOUT, {}, start=DAY, end=DAY, group='total')


def test_retry_queue_excludes_new_completed_and_local_races(tmp_path):
    master = tmp_path / MASTER
    write_csv(master, [runner(RID, 1), runner(OTHER, 1), runner(LOCAL, 1, org='地方')])
    pending = {rid: {'trainer_id': 1} for rid in [RID, OTHER, LOCAL]}
    assert retries_to_do(master, pending, {}, {OTHER}, DAY, 10) == [RID]
    assert not retries_to_do(master, pending, {RID: {'outcome': 'HTTP_403'}}, {OTHER}, DAY, 10)


def test_rate_limit_stops_supplementary_retry(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import requests
    master = tmp_path / MASTER
    write_csv(master, [runner(RID, 1), runner(OTHER, 1)])
    urls = []

    def get(url, **kwargs):
        urls.append(url)
        if url.endswith('robots.txt'):
            return SimpleNamespace(status_code=200, text='User-agent: *\nAllow: /')
        return SimpleNamespace(status_code=429)

    monkeypatch.setattr(requests, 'Session', lambda: SimpleNamespace(headers={}, get=get))
    monkeypatch.setattr('people_weekly.time.sleep', lambda _: None)
    log = {}
    snapshot = tmp_path / 'retry.csv.gz'
    retry_results([RID, OTHER], master, tmp_path, log, snapshot)
    assert len(urls) == 2 and urls[1].endswith(RID)
    assert log[RID]['outcome'] == 'HTTP_429' and OTHER not in log
    assert not snapshot.exists()


def test_later_blank_does_not_erase_saved_result(tmp_path):
    old, new = tmp_path / 'old.csv.gz', tmp_path / 'new.csv.gz'
    record = observed()
    write_observations(old, [record])
    write_observations(new, [record | {'trainer_name': '', 'observed_at': '2026-11-25T00:00:00+09:00'}])
    assert list(observations([old, new])) == [record]
    write_observations(new, [record | {'course': '右'}])
    assert list(observations([old, new])) == [record | {'course': '右'}]
