#!/usr/bin/env python3
from __future__ import annotations
import argparse, re
from pathlib import Path
import pandas as pd
CENTRAL=['札幌','函館','福島','新潟','東京','中山','中京','京都','阪神','小倉']

def pick(name,base,merged):
    p=merged/name
    if p.exists(): return p
    p=base/name
    if p.exists(): return p
    raise FileNotFoundError(name)

def cls(s):
    s=str(s)
    if '未勝利' in s:return '未勝利'
    if '新馬' in s:return '新馬'
    if '1勝' in s or '500万' in s:return '1勝'
    if '2勝' in s or '1000万' in s:return '2勝'
    if '3勝' in s or '1600万' in s:return '3勝'
    if 'オープン' in s or 'OP' in s:return 'オープン'
    return 'その他'

def t2s(t):
    if pd.isna(t):return None
    s=str(t).strip(); m=re.match(r'^(\d+):(\d+)\.(\d+)$',s)
    if m:return int(m[1])*60+int(m[2])+int(m[3])/10
    m=re.match(r'^(\d+)\.(\d+)$',s)
    if m:return int(m[1])+int(m[2])/10
    return None

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--base-dir',required=True); ap.add_argument('--merged-dir',default=''); ap.add_argument('--out',required=True); a=ap.parse_args()
    B=Path(a.base_dir); M=Path(a.merged_dir) if a.merged_dir else B
    frames=[]
    for y in range(2021,2027):
        d=pd.read_csv(pick(f'keiba_{y}.csv',B,M),dtype=str,encoding='utf-8-sig',low_memory=False); d['年']=str(y); frames.append(d)
    k=pd.concat(frames,ignore_index=True); k.columns=[c.replace('\u3000','').replace(' ','') for c in k.columns]
    kai=k['開催情報'].fillna(''); parts=kai.str.extract(r'(\d{4})年(\d{2})月(\d{2})日')
    k['日付']=parts.apply(lambda r:f'{r[0]}-{r[1]}-{r[2]}' if pd.notna(r[0]) else None,axis=1)
    k['競馬場']=kai.str.extract(r'\d+回\s*([^\d\s]+?)\s*\d+日')[0]; k['開催回']=kai.str.extract(r'(\d+)回')[0]; k['開催日目']=kai.str.extract(r'回[^\d]+(\d+)日')[0]
    k['条件']=kai.str.replace(r'^.*?\d+日目\s*','',regex=True).str.replace('\xa0',' ').str.strip(); k['クラス']=k['条件'].map(cls)
    k['距離m']=pd.to_numeric(k['距離'].astype(str).str.extract(r'(\d+)')[0],errors='coerce')
    for src,dst in [('着順','着順n'),('人気','人気n'),('枠番','枠番n'),('馬番','馬番n'),('単勝','単勝n'),('斤量','斤量n')]:
        if src in k:k[dst]=pd.to_numeric(k[src],errors='coerce')
    k['走破秒']=k['タイム'].map(t2s); k['馬体重n']=pd.to_numeric(k['馬体重'].astype(str).str.extract(r'^(\d+)')[0],errors='coerce'); k['増減n']=pd.to_numeric(k['馬体重'].astype(str).str.extract(r'\(([-+]?\d+)\)')[0],errors='coerce'); k['中央地方']=k['競馬場'].isin(CENTRAL).map({True:'中央',False:'地方'})
    co=pd.read_csv(pick('race_corners.csv',B,M),dtype=str,encoding='utf-8-sig',low_memory=False).rename(columns={'馬番':'馬番_c','馬名':'馬名_c'})
    k=k.merge(co.drop(columns=['馬名_c']),left_on=['race_id','馬番'],right_on=['race_id','馬番_c'],how='left').drop(columns=['馬番_c'])
    hd=pd.read_csv(pick('horse_details.csv',B,M),dtype=str,encoding='utf-8-sig',low_memory=False)[['race_id','馬番','通過順','上がり3F']].rename(columns={'馬番':'馬番_h'})
    k=k.merge(hd,left_on=['race_id','馬番'],right_on=['race_id','馬番_h'],how='left').drop(columns=['馬番_h']); k['上がり3Fn']=pd.to_numeric(k['上がり3F'],errors='coerce')
    lp=pd.read_csv(pick('race_laps.csv',B,M),dtype=str,encoding='utf-8-sig',low_memory=False); k=k.merge(lp[['race_id','ラップ','前半3F','後半3F','ハロン数']],on='race_id',how='left')
    k['前半3Fn']=pd.to_numeric(k['前半3F'],errors='coerce'); k['後半3Fn']=pd.to_numeric(k['後半3F'],errors='coerce'); k['ペース差']=k['前半3Fn']-k['後半3Fn']
    pe=pd.read_csv(pick('horse_pedigree.csv',B,M),dtype=str,encoding='utf-8-sig',low_memory=False)[['馬ID','父','母父','父父']].drop_duplicates('馬ID',keep='last'); k=k.merge(pe,on='馬ID',how='left')
    try:
        rn=pd.read_csv(pick('race_names.csv',B,M),dtype=str,encoding='utf-8-sig',low_memory=False).rename(columns={'レース名':'レース名_r'})
        k=k.merge(rn[['race_id','レース名_r']].drop_duplicates('race_id',keep='last'),on='race_id',how='left'); k['レース名']=k['レース名'].replace('',pd.NA).fillna(k['レース名_r']); k=k.drop(columns=['レース名_r'])
    except FileNotFoundError:pass
    cols=['race_id','日付','年','競馬場','開催回','開催日目','レース名','クラス','条件','馬場','距離m','馬場状態','枠番n','馬番n','馬名','馬ID','性齢','斤量n','騎手','騎手ID','着順n','タイム','走破秒','着差','上がり3Fn','通過順','脚質','1コーナー順','2コーナー順','3コーナー順','4コーナー順','出走頭数','人気n','単勝n','馬体重n','増減n','調教師','父','父父','母父','ラップ','前半3Fn','後半3Fn','ペース差','ハロン数','中央地方']
    cols=[c for c in cols if c in k.columns]; m=k[cols].copy(); ren={}
    for c in m.columns:
        if c.endswith('n') and c[:-1] in ['枠番','馬番','斤量','着順','上がり3F','人気','単勝','馬体重','増減','前半3F','後半3F','距離m']:ren[c]=c[:-1]
    m=m.rename(columns=ren).rename(columns={'距離m':'距離'}); out=Path(a.out); out.parent.mkdir(parents=True,exist_ok=True); m.to_csv(out,index=False,encoding='utf-8-sig',compression='gzip')
    print(f'PASS: master rebuilt rows={len(m)} from={m["日付"].min()} to={m["日付"].max()} -> {out}')
if __name__=='__main__':main()
