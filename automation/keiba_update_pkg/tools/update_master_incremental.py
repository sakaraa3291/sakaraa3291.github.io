#!/usr/bin/env python3
from __future__ import annotations
import argparse, re
from pathlib import Path
import pandas as pd

def read_any(p:Path):
    with open(p,'rb') as f: head=f.read(2)
    return pd.read_csv(p,dtype=str,encoding='utf-8-sig',low_memory=False,compression='gzip' if head==b'\x1f\x8b' else None).fillna('')
def rd(p:Path):
    if not p.exists(): return pd.DataFrame()
    try:return pd.read_csv(p,dtype=str,encoding='utf-8-sig',low_memory=False).fillna('')
    except pd.errors.EmptyDataError:return pd.DataFrame()
def t2s(x):
    s=str(x or '').strip(); m=re.match(r'^(\d+):(\d+)\.(\d+)$',s)
    if m:return str(round(int(m[1])*60+int(m[2])+int(m[3])/10,1))
    m=re.match(r'^(\d+)\.(\d+)$',s)
    return str(round(int(m[1])+int(m[2])/10,1)) if m else ''
def nstr(x):
    s=str(x or '').strip()
    try:return str(int(float(s)))
    except:return s
def main():
    ap=argparse.ArgumentParser(description='Append new race IDs, or explicitly replace authorized race IDs, without reordering untouched history.')
    ap.add_argument('--master',required=True); ap.add_argument('--delta-dir',required=True); ap.add_argument('--existing-pedigree',required=True)
    ap.add_argument('--out-master',required=True); ap.add_argument('--out-pedigree',required=True)
    ap.add_argument('--allow-replace-race-ids',default='',help='CSV containing race_id values explicitly authorized for atomic replacement')
    a=ap.parse_args(); D=Path(a.delta_dir)
    old=read_any(Path(a.master)); cols=list(old.columns)
    meta=rd(D/'race_meta_delta.csv'); det=rd(D/'horse_details_delta.csv'); cor=rd(D/'race_corners_delta.csv'); lap=rd(D/'race_laps_delta.csv'); dp=rd(D/'horse_pedigree_delta.csv')
    if meta.empty or det.empty or cor.empty: raise SystemExit('delta meta/details/corners required')
    # Pedigree is keyed by horse and the newest fetched row is authoritative.
    ped=read_any(Path(a.existing_pedigree)); ped=pd.concat([ped,dp],ignore_index=True,sort=False) if not dp.empty else ped
    if '馬ID' not in ped: raise SystemExit('pedigree file missing 馬ID')
    ped=ped.drop_duplicates('馬ID',keep='last'); Path(a.out_pedigree).parent.mkdir(parents=True,exist_ok=True); ped.to_csv(a.out_pedigree,index=False,encoding='utf-8-sig')
    existing_ids=set(old['race_id'].astype(str)); delta_ids=set(det['race_id'].astype(str)); overlap=existing_ids & delta_ids
    allowed=set()
    if a.allow_replace_race_ids:
        auth=rd(Path(a.allow_replace_race_ids))
        if 'race_id' not in auth: raise SystemExit('authorized replacement CSV missing race_id')
        allowed=set(auth['race_id'].astype(str))
    unauthorized=overlap-allowed
    if unauthorized:
        raise SystemExit(f'delta overlaps {len(unauthorized)} existing race IDs without explicit authorization')
    # One row per horse/result.
    cor2=cor.drop(columns=['馬名'],errors='ignore').copy()
    x=det.merge(cor2,on=['race_id','馬番'],how='left',validate='one_to_one')
    x=x.merge(meta.drop_duplicates('race_id',keep='last'),on='race_id',how='left',validate='many_to_one')
    if not lap.empty:x=x.merge(lap.drop_duplicates('race_id',keep='last'),on='race_id',how='left',validate='many_to_one')
    else:x['ラップ']='';x['前半3F']='';x['後半3F']='';x['ハロン数']=''
    pcols=[c for c in ['馬ID','父','父父','母父'] if c in ped.columns]
    x=x.merge(ped[pcols].drop_duplicates('馬ID',keep='last'),on='馬ID',how='left',validate='many_to_one')
    if x['馬ID'].astype(str).str.strip().eq('').any(): raise SystemExit(f'missing 馬ID in new rows: {int(x["馬ID"].astype(str).str.strip().eq("").sum())}')
    if any(c in x and x[c].astype(str).str.strip().eq('').any() for c in ('父','父父','母父')): raise SystemExit('pedigree coverage incomplete in new rows')
    out=pd.DataFrame('',index=range(len(x)),columns=cols)
    def put(dst,src=None,fn=None):
        if dst not in out.columns:return
        src=src or dst
        if src in x.columns: out[dst]=x[src].map(fn) if fn else x[src].astype(str)
    for c in ['race_id','レース名','クラス','馬場状態','馬名','馬ID','騎手ID','タイム','着差','通過順','脚質','1コーナー順','2コーナー順','3コーナー順','4コーナー順','出走頭数','父','父父','母父','ラップ','前半3F','後半3F','ハロン数']:
        put(c)
    put('日付','date'); put('競馬場','venue'); put('距離','distance_m',nstr); put('馬番','馬番',nstr); put('着順','着順')
    put('上がり3F','上がり3F')
    if '年' in out: out['年']=x['date'].astype(str).str[:4]
    surf=x['surface'].astype(str).map({'芝':'芝','ダ':'ダート','ダート':'ダート','障':'障害'}).fillna(x['surface'].astype(str))
    if '馬場' in out:out['馬場']=surf
    if '条件' in out:out['条件']=[('障害' if s=='障' else str(k)) for s,k in zip(x['surface'].astype(str),x['クラス'].astype(str))]
    if '走破秒' in out:out['走破秒']=x['タイム'].map(t2s)
    if '中央地方' in out:out['中央地方']='中央'
    if 'ペース差' in out:
        a1=pd.to_numeric(x.get('前半3F',pd.Series('',index=x.index)),errors='coerce'); a2=pd.to_numeric(x.get('後半3F',pd.Series('',index=x.index)),errors='coerce')
        out['ペース差']=(a1-a2).map(lambda v:'' if pd.isna(v) else str(round(float(v),1)))
    # Refresh authorized overlaps at their existing race/horse positions.
    ids=set(out['race_id']); mask=old['race_id'].isin(ids)
    keys=['race_id','馬番']
    oldkeys=old.loc[mask,keys].copy(); oldkeys['馬番']=oldkeys['馬番'].map(nstr)
    updates=out[out['race_id'].isin(existing_ids)].copy()
    if oldkeys.duplicated(keys).any() or updates.duplicated(keys).any(): raise SystemExit('duplicate overlap horse keys')
    if set(map(tuple,oldkeys.values))!=set(map(tuple,updates[keys].values)): raise SystemExit('overlap horse keys differ; manual reconciliation required')
    final=old.copy()
    if len(updates):
        aligned=updates.set_index(keys).reindex(pd.MultiIndex.from_frame(oldkeys)).reset_index()[cols]
        final.loc[mask,cols]=aligned.to_numpy()
    appended=out[~out['race_id'].isin(existing_ids)].copy()
    appended['_horse_order']=pd.to_numeric(appended['馬番'],errors='coerce')
    appended=appended.sort_values(['日付','race_id','_horse_order'],kind='mergesort')[cols]
    final=pd.concat([final,appended],ignore_index=True)[cols]
    op=Path(a.out_master); op.parent.mkdir(parents=True,exist_ok=True); final.to_csv(op,index=False,encoding='utf-8-sig',compression='gzip')
    print(f'PASS: master {len(old)} -> {len(final)} rows; delta races={len(ids)} rows={len(out)}; pedigree={len(ped)}')
if __name__=='__main__': raise SystemExit(main())
