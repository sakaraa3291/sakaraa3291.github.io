#!/usr/bin/env python3
from __future__ import annotations
import subprocess, sys, tempfile
from pathlib import Path
import pandas as pd

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

if __name__=='__main__':
    test_payout_column_alias()
    test_obstacle_lap_exemption_and_flat_required()
    print('PASS: payout alias + obstacle lap-exemption contracts')
