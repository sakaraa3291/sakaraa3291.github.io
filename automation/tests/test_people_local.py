import csv
import gzip
import io
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from zipfile import ZipFile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import jra_trainer_registry
import nar_people
from nar_download import zip_members
from people import payout_tables, query, resolve_state
from people_state import MASTER, PAYOUT, observation, observations, values_for, write_observations


def month_zip(path, tables):
    with ZipFile(path, 'w') as archive:
        for kind, rows in tables.items():
            output = io.StringIO(newline='')
            writer = csv.DictWriter(output, sorted(nar_people.REQUIRED[kind]), lineterminator='\n')
            writer.writeheader()
            writer.writerows(rows)
            archive.writestr(f'202101_{kind}.csv', output.getvalue())


def test_nar_local_snapshot_checks_payout_and_is_idempotent(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    path = source / '2021-01.zip'
    race = {'競馬場': '川崎', '競走年月日': '20210103', 'レース番号': '1'}
    scheduled = {**race, 'レース番号': '2'}
    month_zip(path, {'racelist': [race | {'芝ダート区分': 'ダート', '距離': '1400', '頭数': '2'}, scheduled],
                     'horselist': [race | {'枠番': '1', '馬番': '1', '馬名': '馬ア', '着順': '1', '人気': '1',
                                            '騎手名': '騎手甲', '騎手所属': '川崎', '調教師': '調教師甲', '調教師所属': '川崎'},
                                   race | {'枠番': '2', '馬番': '2', '馬名': '馬イ', '着順': '2', '人気': '2',
                                            '騎手名': '騎手乙', '騎手所属': '川崎', '調教師': '調教師甲', '調教師所属': '川崎'},
                                   scheduled | {'枠番': '2', '馬番': '2', '馬名': '予定'}],
                     'payback': [race | {'単勝組番': '1', '単勝払戻金(円)': '200', '複勝組番1': '1',
                                          '複勝払戻金1(円)': '120'},
                                 race | {'単勝組番': '1', '単勝払戻金(円)': '200', '複勝組番1': '2',
                                          '複勝払戻金1(円)': '130'}]})
    (source / 'downloads.json').write_text(json.dumps({'2021-01': {'archive': {
        'sha256': nar_people.file_sha(path), 'covered_through': '2021-01-31'}}}), encoding='utf-8')
    output = tmp_path / 'state'
    start, end = date(2021, 1, 1), date(2021, 1, 31)
    report = nar_people.build(source, output, start, end)
    assert report['stats']['races:confirmed'] == report['stats']['races:unconfirmed'] == 1
    assert report['stats']['rows:started'] == 2
    state = resolve_state(output)
    assert len(payout_tables(state / PAYOUT)) == 2
    result = query(state / MASTER, state / PAYOUT, {}, start='2021-01-01', end='2021-01-31', group='trainer-label')
    row = result['results'][0]
    assert result['group_identity'] == 'published label and affiliation'
    assert row['starts'] == 2 and row['win']['return_yen'] == 200 and row['place']['return_yen'] == 250
    assert nar_people.build(source, output, start, end)['reused'] is True
    assert resolve_state(output) == state


def test_nar_zip_rejects_nonofficial_members(tmp_path):
    path = tmp_path / 'bad.zip'
    with ZipFile(path, 'w') as archive:
        archive.writestr('../202101_racelist.csv', 'bad')
    with ZipFile(path) as archive, pytest.raises(ValueError, match='unexpected'):
        zip_members(archive, date(2021, 1, 1))
    assert nar_people.ranks('1,(2,3),4-5') == {1: 1, 2: 2, 3: 2, 4: 4, 5: 5}
    assert nar_people.ranks('(1,1),2') == {}


def test_jra_profile_requires_exact_id_and_authoritative_evidence(tmp_path):
    url = 'https://www.jra.go.jp/JRADB/accessC.html?CNAME=pw05cmk001020%2F47'
    good = observation('202105010101', 1, 'TEST1', '2021-01-04', url, '2026-11-25T12:00:00+09:00',
                       'jra_trainer_profile', {'trainer_id': 'jra:001020'})
    path = tmp_path / 'people.csv.gz'
    write_observations(path, [good])
    parsed, = observations([path])
    assert values_for({'馬ID': 'TEST1', '日付': '2021-01-04'}, [parsed], Counter())['trainer_id'] == 'jra:001020'
    assert jra_trainer_registry.exact_affiliation('[東] 相沢　郁') == ('相沢郁', '美浦')
    assert jra_trainer_registry.exact_affiliation('相沢 郁') is None
    write_observations(path, [good | {'trainer_id': 'jra:001021'}])
    with pytest.raises(ValueError, match='invalid observation'):
        observations([path])


def test_local_offline_reads_only_hash_checked_input(tmp_path):
    from people_local_weekly import from_public_main

    input_path, output = tmp_path / 'base', tmp_path / 'stage'
    input_path.mkdir()
    output.mkdir()
    for name in (MASTER, PAYOUT):
        (input_path / name).write_bytes(gzip.compress(name.encode(), mtime=0))
    manifest = {'through': '2021-01-04', 'files': {name: nar_people.file_sha(input_path / name) for name in (MASTER, PAYOUT)}}
    (input_path / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    assert from_public_main(input_path, output, True)[1] == manifest
    (input_path / MASTER).write_bytes(b'changed')
    assert nar_people.file_sha(output / MASTER) == manifest['files'][MASTER]
    with pytest.raises(ValueError, match='checksum mismatch'):
        from_public_main(input_path, output, True)
