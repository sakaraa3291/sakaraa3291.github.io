from bs4 import BeautifulSoup
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'keiba_update_pkg/tools'))
from fetch_netkeiba_delta import parse_meta, parse_results, parse_lap, parse_payouts, corners_from_entries

RID='202606040501'

HTML='''<html><head><title>2歳未勝利 結果・払戻 | 2026年9月19日 中山1R レース情報(JRA) - netkeiba</title></head><body>
<div class="RaceName">2歳未勝利</div>
<div class="RaceData01">10:00発走 / ダ1200m (右) / 天候:曇 / 馬場:良</div>
<div class="RaceData02">4回 中山 5日目 サラ系２歳 未勝利 [指] 馬齢 9頭</div>
<table class="RaceTable01"><tr><th>着 順</th><th>枠</th><th>馬 番</th><th>馬名</th><th>性齢</th><th>斤量</th><th>騎手</th><th>タイム</th><th>着差</th><th>人 気</th><th>単勝 オッズ</th><th>後3F</th><th>コーナー 通過順</th></tr>
<tr><td>1</td><td>8</td><td>9</td><td><a href="/horse/2024101716/">スマートブライド</a></td><td>牝2</td><td>55.0</td><td><a href="/jockey/result/recent/05339/">ルメー</a></td><td>1:11.8</td><td></td><td>1</td><td>1.1</td><td>37.8</td><td>2-2</td></tr>
</table>
<div class="Result_Pay_Back"><table>
<tr class="Tansho"><th>単勝</th><td class="Result"><div><span>9</span></div></td><td class="Payout"><span>110円</span></td><td class="Ninki"><span>1人気</span></td></tr>
<tr class="Fukusho"><th>複勝</th><td class="Result"><div><span>9</span></div><div><span>5</span></div></td><td class="Payout"><span>100円<br/>110円</span></td><td class="Ninki"><span>1人気</span><span>3人気</span></td></tr>
<tr class="Umaren"><th>馬連</th><td class="Result"><ul><li><span>5</span></li><li><span>9</span></li></ul></td><td class="Payout"><span>370円</span></td><td class="Ninki"><span>2人気</span></td></tr>
<tr class="Fuku3"><th>3連複</th><td class="Result"><ul><li><span>1</span></li><li><span>5</span></li><li><span>9</span></li></ul></td><td class="Payout"><span>260円</span></td><td class="Ninki"><span>1人気</span></td></tr>
</table></div>
<table class="RaceCommon_Table Race_HaronTime"><tr class="Header"><th>200m</th><th>400m</th><th>600m</th><th>800m</th><th>1000m</th><th>1200m</th></tr>
<tr class="HaronTime"><td>12.0</td><td>22.5</td><td>33.9</td><td>46.0</td><td>58.6</td><td>1:11.8</td></tr>
<tr class="HaronTime"><td>12.0</td><td>10.5</td><td>11.4</td><td>12.1</td><td>12.6</td><td>13.2</td></tr></table>
</body></html>'''


def test_current_result_layout_parses_required_fields():
    soup=BeautifulSoup(HTML,'lxml')
    meta=parse_meta(soup,RID,{})
    assert meta == {
        'race_id':RID,'date':'2026-09-19','venue':'中山','レース名':'2歳未勝利',
        'distance_m':1200,'surface':'ダート','馬場状態':'良','クラス':'未勝利'
    }
    details,entries=parse_results(soup,RID)
    assert details == [{'race_id':RID,'馬番':'9','馬名':'スマートブライド','着順':'1','タイム':'1:11.8','着差':'','通過順':'2-2','上がり3F':'37.8'}]
    assert entries[0]['馬ID']=='2024101716' and entries[0]['騎手ID']=='05339' and entries[0]['通過順']=='2-2'
    lap=parse_lap(soup,RID,1200)
    assert lap['ラップ']=='12.0-10.5-11.4-12.1-12.6-13.2' and lap['前半3F']==33.9 and lap['後半3F']==37.9
    payouts=parse_payouts(soup,RID)
    assert {'race_id':RID,'券種':'馬連','組み合わせ':'5-9','払戻金':'370','人気':'2'} in payouts
    assert {'race_id':RID,'券種':'三連複','組み合わせ':'1-5-9','払戻金':'260','人気':'1'} in payouts
    assert len([x for x in payouts if x['券種']=='複勝'])==2


def test_abbreviated_going_is_normalized():
    soup=BeautifulSoup(HTML.replace('馬場:良','馬場:不'),'lxml')
    assert parse_meta(soup,RID,{})['馬場状態']=='不良'
    soup=BeautifulSoup(HTML.replace('馬場:良','馬場:稍'),'lxml')
    assert parse_meta(soup,RID,{})['馬場状態']=='稍重'


def test_field_size_is_per_race_not_batch():
    entries=[
        {'race_id':'r1','馬番':'1','馬名':'a','馬ID':'1','騎手ID':'j','通過順':'1-1'},
        {'race_id':'r1','馬番':'2','馬名':'b','馬ID':'2','騎手ID':'j','通過順':'2-2'},
        {'race_id':'r2','馬番':'1','馬名':'c','馬ID':'3','騎手ID':'j','通過順':'1-1'},
    ]
    rows=corners_from_entries(entries)
    assert [r['出走頭数'] for r in rows]==[2,2,1]


def test_current_lap_segment_count_mismatch_is_rejected():
    soup=BeautifulSoup(HTML.replace('<td>13.2</td>', ''),'lxml')
    with pytest.raises(ValueError, match='lap segment count mismatch'):
        parse_lap(soup,RID,1200)


def test_ambiguous_payout_counts_are_not_broadcast():
    soup=BeautifulSoup(HTML.replace('100円<br/>110円', '100円'),'lxml')
    assert not any(row['券種']=='複勝' for row in parse_payouts(soup,RID))
