#!/usr/bin/env python3
from pathlib import Path
import argparse, pandas as pd

def rd(p):
    p=Path(p)
    if not p.exists(): return pd.DataFrame()
    try: return pd.read_csv(p,dtype=str,encoding='utf-8-sig',low_memory=False).fillna('')
    except pd.errors.EmptyDataError: return pd.DataFrame()

def normalize_payout_cols(d):
    if d.empty: return d
    if '組合せ' in d.columns and '組み合わせ' not in d.columns:
        d=d.rename(columns={'組合せ':'組み合わせ'})
    return d

def merge(base, delta, keys, out, normalizer=None):
    b,d=rd(base),rd(delta)
    if normalizer: b=normalizer(b); d=normalizer(d)
    if d.empty:
        b.to_csv(out,index=False,encoding='utf-8-sig'); return len(b),0
    for k in keys:
        if k not in d.columns: raise SystemExit(f'missing key {k} in {delta}; columns={list(d.columns)}')
    if not b.empty:
        if any(k not in b.columns for k in keys): raise SystemExit(f'missing keys {keys} in {base}; columns={list(b.columns)}')
        b['_k']=b[keys].astype(str).agg('|'.join,axis=1); d['_k']=d[keys].astype(str).agg('|'.join,axis=1)
        b=b[~b['_k'].isin(set(d['_k']))].drop(columns=['_k']); d=d.drop(columns=['_k'])
    m=pd.concat([b,d],ignore_index=True,sort=False)
    m.to_csv(out,index=False,encoding='utf-8-sig')
    return len(m),len(d)

def patch_keiba_2026(base_csv, meta_csv, out_csv):
    b=rd(base_csv); m=rd(meta_csv)
    if b.empty: return 0,0
    if m.empty:
        b.to_csv(out_csv,index=False,encoding='utf-8-sig'); return len(b),0
    need={'race_id','distance_m','surface','馬場状態'}
    if not need.issubset(m.columns): raise SystemExit(f'race_meta_delta missing {sorted(need-set(m.columns))}')
    m=m.drop_duplicates('race_id',keep='last').set_index('race_id'); patched=0
    for rid,idxs in b.groupby('race_id').groups.items():
        rid=str(rid)
        if rid not in m.index: continue
        r=m.loc[rid]; dist=str(r.get('distance_m','')).strip(); surface=str(r.get('surface','')).strip(); going=str(r.get('馬場状態','')).strip(); name=str(r.get('レース名','')).strip()
        vals={'距離':(f'{int(float(dist))}m' if dist else ''),'馬場':surface,'馬場状態':going,'レース名':name}
        for c,v in vals.items():
            if c in b.columns and v: b.loc[list(idxs),c]=v
        patched+=1
    b.to_csv(out_csv,index=False,encoding='utf-8-sig'); return len(b),patched

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--base-dir',required=True); ap.add_argument('--delta-dir',required=True); ap.add_argument('--out-dir',required=True)
    a=ap.parse_args(); B,D,O=map(Path,[a.base_dir,a.delta_dir,a.out_dir]); O.mkdir(parents=True,exist_ok=True)
    specs=[
      ('race_laps.csv','race_laps_delta.csv',['race_id'],None),
      ('horse_details.csv','horse_details_delta.csv',['race_id','馬番'],None),
      ('race_corners.csv','race_corners_delta.csv',['race_id','馬番'],None),
      ('horse_pedigree.csv','horse_pedigree_delta.csv',['馬ID'],None),
      ('払戻データ_全券種.csv','payout_delta.csv',['race_id','券種','組み合わせ'],normalize_payout_cols),
    ]
    for bf,df,keys,norm in specs:
        if (B/bf).exists() or (D/df).exists():
            n,nd=merge(B/bf,D/df,keys,O/bf,norm); print(f'{bf}: {n} rows ({nd} delta)')
    if (B/'keiba_2026.csv').exists():
        n,np=patch_keiba_2026(B/'keiba_2026.csv',D/'race_meta_delta.csv',O/'keiba_2026.csv'); print(f'keiba_2026.csv: {n} rows ({np} race metadata patched)')
if __name__=='__main__': main()
