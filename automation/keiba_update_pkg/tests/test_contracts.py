#!/usr/bin/env python3
from __future__ import annotations
import subprocess, sys, tempfile
from pathlib import Path
import pandas as pd
import pytest

ROOT=Path(__file__).resolve().parents[1]
PY=sys.executable

def write_csv(path, rows, cols):
    pd.DataFrame(rows, columns=cols).to_csv(path,index=False,encoding='utf-8-sig')

def test_payout_column_alias():
    with tempfile.TemporaryDirectory() as td:
        q=Path(td); b=q/'base'; d=q/'delta'; o=q/'out'
        b.mkdir(); d.mkdir(); o.mkdir()
        write_csv(b/'払戻データ_全券種.csv', [['1','単勝','1','100','1']], ['race_id','券種','組合せ','払戻金','人気'])
        write_csv(d/'payout_delta.csv', [['2','単勝','2','200','1']], ['race_id','券種','組み合わせ','払戻金','人気'])
        subprocess.run([PY,str(ROOT/'tools/merge_delta_sources.py'),'--base-dir',str(b),'--delta-dir',str(d),'--out-dir',str(o)],check=True,capture_output=True,text=True)
        got=pd.read_csv(o/'払戻データ_全券種.csv',dtype=str,encoding='utf-8-sig').fillna('')
        assert '組み合わせ' in got.columns and '組合せ' not in got.columns
        assert set(got.race_id)=={'1','2'}

def make_delta(d:Path, include_flat_lap=True):
    write_csv(d/'race_meta_delta.csv', [['F'],['O']], ['race_id'])
    write_csv(d/'race_laps_delta.csv', ([['F']] if include_flat_lap else []), ['race_id'])
    write_csv(d/'horse_details_delta.csv', [['F'],['O']], ['race_id'])
    write_csv(d/'race_corners_delta.csv', [['F',''],['O','']], ['race_id','馬ID'])
    write_csv(d/'payout_delta.csv', [['F'],['O']], ['race_id'])
    write_csv(d/'errors.csv', [], ['race_id','error'])
    write_csv(d/'pedigree_errors.csv', [], ['馬ID','error'])
    write_csv(d/'horse_pedigree_delta.csv', [], ['馬ID'])

def test_obstacle_lap_exemption_and_flat_required():
    with tempfile.TemporaryDirectory() as td:
        q=Path(td); d=q/'delta'; d.mkdir()
        target=q/'target.csv'
        write_csv(target, [['F','平地競走'],['O','障害3歳以上未勝利']], ['race_id','レース名'])
        make_delta(d, True)
        good=subprocess.run([PY,str(ROOT/'tools/validate_delta_complete.py'),'--target',str(target),'--delta-dir',str(d)],capture_output=True,text=True)
        assert good.returncode==0, good.stdout+good.stderr
        make_delta(d, False)
        bad=subprocess.run([PY,str(ROOT/'tools/validate_delta_complete.py'),'--target',str(target),'--delta-dir',str(d)],capture_output=True,text=True)
        assert bad.returncode==2, bad.stdout+bad.stderr

@pytest.mark.parametrize('course,spans,expected', [
    ('芝1600m', '<span class="Item03">稍</span>', '稍重'),
    ('ダ1400m', '<span class="Item04">不</span>', '不良'),
    ('障3170m', '<span class="Item03">良</span><span class="Item04">良</span>', '良'),
    ('障3110m 芝', '<span class="Item03">良</span>', '良'),
    ('障2750m 芝', '<span class="Item03">稍</span>', '稍重'),
    ('芝1800m', '馬場：重', '重'),
])
def test_going_parsing_current_and_legacy(course, spans, expected):
    from bs4 import BeautifulSoup
    sys.path.insert(0, str(ROOT/'tools'))
    from fetch_netkeiba_delta import parse_meta
    html = f'<div class="RaceName">未勝利</div><div class="RaceData01"><span>{course}</span> / {spans}</div>'
    meta = parse_meta(BeautifulSoup(html, 'lxml'), '202605040301', {'date': '2026-10-10', 'venue': '東京'})
    assert meta['馬場状態'] == expected


def test_obstacle_mixed_going_keeps_both_observations():
    from bs4 import BeautifulSoup
    sys.path.insert(0, str(ROOT/'tools'))
    from fetch_netkeiba_delta import parse_meta
    html = '<div class="RaceData01"><span>障3170m</span> 芝 ダート / <span class="Item03">良</span><span class="Item04">重</span></div>'
    meta=parse_meta(BeautifulSoup(html, 'lxml'), '202608040304', {'date': '2026-10-10', 'venue': '京都'})
    assert meta['芝馬場状態']=='良'
    assert meta['ダート馬場状態']=='重'
    assert meta['馬場状態']=='芝:良/ダート:重'


@pytest.mark.parametrize('grade_class,want', [
    ('Icon_GradeType1', 'GI'),
    ('Icon_GradeType2', 'GII'),
    ('Icon_GradeType3', 'GIII'),
    ('Icon_GradeType6', ''),
])
def test_grade_is_read_from_source_icon_not_race_name(grade_class, want):
    from bs4 import BeautifulSoup
    sys.path.insert(0, str(ROOT/'tools'))
    from fetch_netkeiba_delta import parse_meta
    html=(f'<h1 class="RaceName">重賞名'
          f'<span class="Icon_GradeType {grade_class}"></span>'
          f'<span class="Icon_GradeType Icon_GradeType13"></span></h1>'
          '<div class="RaceData02">オープン</div>'
          '<div class="RaceData01"><span>芝2200m</span><span class="Item03">良</span></div>')
    meta=parse_meta(BeautifulSoup(html,'lxml'),'202608040911',{'date':'2026-10-10','venue':'京都'})
    assert meta['grade']==want
    assert meta['レース名']=='重賞名'
    assert meta['芝馬場状態']=='良' and meta['ダート馬場状態']==''


def test_obstacle_two_distinct_going_fields_are_preserved():
    from bs4 import BeautifulSoup
    sys.path.insert(0, str(ROOT/'tools'))
    from fetch_netkeiba_delta import parse_meta
    html=('<h1 class="RaceName">障害競走</h1>'
          '<div class="RaceData01"><span>障3170m</span> 芝 ダート / '
          '<span class="Item03">稍</span><span class="Item04">不</span></div>')
    m=parse_meta(BeautifulSoup(html,'lxml'),'202608040804',{'date':'2026-10-24','venue':'京都'})
    assert m['芝馬場状態']=='稍重'
    assert m['ダート馬場状態']=='不良'
    assert m['馬場状態']=='芝:稍重/ダート:不良'


def test_grade_icon_conflict_fails_closed():
    from bs4 import BeautifulSoup
    sys.path.insert(0,str(ROOT/'tools'))
    from fetch_netkeiba_delta import parse_meta
    html=('<h1 class="RaceName">重賞'
          '<span class="Icon_GradeType Icon_GradeType1"></span>'
          '<span class="Icon_GradeType Icon_GradeType2"></span></h1>'
          '<div class="RaceData01"><span>芝2200m</span><span class="Item03">良</span></div>')
    with pytest.raises(ValueError,match='conflicting graded-race icons'):
        parse_meta(BeautifulSoup(html,'lxml'),'202608040911',{})



if __name__=='__main__':
    test_payout_column_alias()
    test_obstacle_lap_exemption_and_flat_required()
    print('PASS: payout alias + obstacle lap-exemption contracts')
