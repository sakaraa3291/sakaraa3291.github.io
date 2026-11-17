import importlib.util
from pathlib import Path
import pytest
from bs4 import BeautifulSoup

P = Path(__file__).resolve().parents[1] / 'tools/fetch_netkeiba_delta.py'
S = importlib.util.spec_from_file_location('going_collector', P)
M = importlib.util.module_from_spec(S)
S.loader.exec_module(M)

def parse(html):
    return M.parse_meta(BeautifulSoup(html, 'lxml'), '202608050411', {})['馬場状態']

@pytest.mark.parametrize('raw,expected', [('良','良'),('稍重','稍重'),('稍','稍重'),('重','重'),('不良','不良'),('不','不良')])
def test_current_header(raw, expected):
    assert parse(f'<div class="RaceData01"><span>芝2200m</span><span class="Item03"> {raw}</span></div>') == expected

@pytest.mark.parametrize('label', ['芝','ダート','ダ','馬場'])
def test_legacy_header(label):
    assert parse(f'<div class="RaceData01">{label} : 稍重</div>') == '稍重'

@pytest.mark.parametrize('html', ['<div>芝:良</div>', '<div class="RaceData01">芝2200m 良血馬</div>', '<div class="RaceData01"><span class="Item03">不明</span></div>'])
def test_missing_or_unrelated_is_not_guessed(html):
    assert parse(html) == ''

def test_current_value_ignores_other_race():
    assert parse('<div>芝:良</div><div class="RaceData01"><span class="Item03">重</span></div>') == '重'

def test_conflict_fails_closed():
    with pytest.raises(ValueError, match='conflicting going'):
        parse('<div class="RaceData01">芝:良<span class="Item03">重</span></div>')

@pytest.mark.parametrize('label,expected', [('オープン','オープン'),('1勝クラス','1勝'),('2勝クラス','2勝'),('3勝クラス','3勝'),('500万円以下','1勝'),('1000万円以下','2勝'),('1600万円以下','3勝')])
def test_class_does_not_read_prize_money(label, expected):
    html = f'<div class="RaceName">対象レース</div><div class="RaceData02">{label}<br>本賞金:15000,6000,3800,2300,1500万円</div>'
    assert M.parse_meta(BeautifulSoup(html, 'lxml'), '202608050411', {})['クラス'] == expected

def test_class_name_fallback_survives_prize_section():
    html = '<div class="RaceName">3歳未勝利</div><div class="RaceData02">本賞金:500,200万円</div>'
    assert M.parse_meta(BeautifulSoup(html, 'lxml'), '202608050411', {})['クラス'] == '未勝利'
