#!/usr/bin/env python3
"""Rebuild lapdata.json condition averages from the unified master.

Verified against the current v3.8 baseline: all 934 condition records match exactly.
The historical 17,822 -> 17,759 difference is exactly 63 singleton condition groups;
production therefore keeps groups only when n >= 2.

Grade records and audit notes are preserved from the supplied baseline JSON.
"""
from __future__ import annotations
import argparse, json, math, uuid
from pathlib import Path
import numpy as np
import pandas as pd

VENUES=['札幌','函館','福島','新潟','東京','中山','中京','京都','阪神','小倉','大井','船橋','川崎','浦和']

def read_master(path:str)->pd.DataFrame:
    # Current Drive file named .csv is actually gzip; pandas auto inference cannot use extension.
    with open(path,'rb') as f: head=f.read(2)
    comp='gzip' if head==b'\x1f\x8b' else None
    return pd.read_csv(path,dtype=str,low_memory=False,compression=comp,encoding='utf-8-sig')

def to_float(x):
    try: return float(x)
    except Exception: return None

def segdist(dist:int,n:int):
    first=dist-200*(n-1)
    return [first]+[200]*(n-1)

def build_cond(master:pd.DataFrame,min_n:int=2):
    m=master.copy()
    m['距離_num']=pd.to_numeric(m['距離'],errors='coerce')
    m['着順_num']=pd.to_numeric(m['着順'],errors='coerce')
    m['走破秒_num']=pd.to_numeric(m['走破秒'],errors='coerce')
    r=m[(m['競馬場'].isin(VENUES)) & m['ラップ'].notna()].drop_duplicates('race_id').copy()
    wins=m[m['着順_num']==1][['race_id','走破秒_num']].drop_duplicates('race_id')
    r=r.merge(wins,on='race_id',how='left',suffixes=('','_winner'))
    # Some masters already carry one 走破秒 on the de-duplicated row. Always use winner column.
    wcol='走破秒_num_winner' if '走破秒_num_winner' in r.columns else '走破秒_num'
    r['surface']=r['馬場'].map({'芝':'芝','ダ':'ダート','ダート':'ダート'})
    r=r[r['surface'].notna() & r['距離_num'].notna()]
    r['going_group']=r['馬場状態'].map(lambda x:'良' if x=='良' else '道悪')
    groups={}
    for row in r.itertuples(index=False):
        laps=[float(v) for v in str(row.ラップ).split('-') if str(v).strip()]
        dist=int(row.距離_num)
        if not laps or len(laps)!=math.ceil(dist/200):
            continue
        klass=str(row.クラス) if pd.notna(row.クラス) and str(row.クラス) else 'その他'
        key=f'{row.競馬場}|{row.surface}|{dist}|{klass}|{row.going_group}'
        winner=getattr(row,wcol.replace('走破秒_num_winner','走破秒_num_winner'),None)
        # itertuples sanitizes duplicate-like names unpredictably; use dataframe lookup below later.
        groups.setdefault(key,[]).append((str(row.race_id),laps,dist))
    # Winner times by race id is easier and deterministic.
    winmap={str(a):float(b) for a,b in wins.dropna().itertuples(index=False,name=None)}
    out={}; singleton=[]
    for key,rows in groups.items():
        if len(rows)<min_n:
            singleton.extend(rid for rid,_,_ in rows); continue
        arr=np.asarray([x[1] for x in rows],dtype=float)
        dist=rows[0][2]
        ws=[winmap[rid] for rid,_,_ in rows if rid in winmap]
        out[key]={
            'l':np.round(arr.mean(axis=0),2).tolist(),
            'n':len(rows),
            'w':round(float(np.mean(ws)),1) if ws else None,
            'wb':round(float(min(ws)),1) if ws else None,
            'segment_distances':segdist(dist,arr.shape[1]),
        }
    return dict(sorted(out.items())), singleton, r

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--master',required=True)
    ap.add_argument('--baseline',required=True,help='Current production lapdata.json; grade/audit are preserved')
    ap.add_argument('--out',required=True)
    ap.add_argument('--dataset-id',default='')
    args=ap.parse_args()
    m=read_master(args.master)
    base=json.load(open(args.baseline,encoding='utf-8'))
    cond,singletons,r=build_cond(m,2)
    base['cond']=cond
    meta=base.setdefault('meta',{})
    meta['from']=str(r['日付'].dropna().min()) if len(r) else None
    meta['to']=str(r['日付'].dropna().max()) if len(r) else None
    meta['races']=sum(x['n'] for x in cond.values())
    meta['singleton_conditions_excluded']=len(singletons)
    meta['singleton_exclusion_rule']='同一 競馬場|馬場|距離|クラス|馬場状態 が1レースのみの条件は表示対象外'
    if args.dataset_id: meta['dataset_id']=args.dataset_id
    Path(args.out).write_text(json.dumps(base,ensure_ascii=False,indent=2)+"\n",encoding='utf-8')
    print(json.dumps({'conditions':len(cond),'races':meta['races'],'singletons_excluded':len(singletons),'from':meta['from'],'to':meta['to']},ensure_ascii=False))
if __name__=='__main__': main()
