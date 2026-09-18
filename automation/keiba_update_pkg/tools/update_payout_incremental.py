#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path
import pandas as pd

def read(p):
    return pd.read_csv(p,dtype=str,encoding='utf-8-sig',low_memory=False).fillna('')
def norm(d):
    return d.rename(columns={'組合せ':'組み合わせ'}) if '組合せ' in d.columns and '組み合わせ' not in d.columns else d
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--payout',required=True);ap.add_argument('--delta-dir',required=True);ap.add_argument('--out',required=True)
    ap.add_argument('--allow-replace-race-ids',default='',help='CSV containing race_id values explicitly authorized for atomic replacement');a=ap.parse_args()
    b=norm(read(a.payout)); d=norm(read(Path(a.delta_dir)/'payout_delta.csv'))
    need=['race_id','券種','組み合わせ'];
    if any(c not in b.columns or c not in d.columns for c in need):raise SystemExit('payout key columns missing')
    ids=set(d.race_id.astype(str)); overlap=ids & set(b.race_id.astype(str)); allowed=set()
    if a.allow_replace_race_ids:
        auth=read(a.allow_replace_race_ids)
        if 'race_id' not in auth: raise SystemExit('authorized replacement CSV missing race_id')
        allowed=set(auth.race_id.astype(str))
    unauthorized=overlap-allowed
    if unauthorized: raise SystemExit(f'delta overlaps {len(unauthorized)} existing race IDs without explicit authorization')
    d=d.drop_duplicates(need,keep='last').copy()
    first=b.reset_index().groupby('race_id',sort=False)['index'].first().to_dict()
    kept=b[~b.race_id.isin(ids)].copy(); kept['_merge_order']=kept.index
    d['_merge_order']=[first.get(rid,len(b)+i) for i,rid in enumerate(d.race_id)]
    m=pd.concat([kept,d],ignore_index=True,sort=False).sort_values('_merge_order',kind='mergesort').drop(columns='_merge_order').reset_index(drop=True)
    p=Path(a.out);p.parent.mkdir(parents=True,exist_ok=True);m.to_csv(p,index=False,encoding='utf-8-sig',compression='gzip' if p.suffix=='.gz' else None)
    print(f'PASS: payout rows={len(m)} delta_races={len(ids)} delta_rows={len(d)}')
if __name__=='__main__':raise SystemExit(main())
