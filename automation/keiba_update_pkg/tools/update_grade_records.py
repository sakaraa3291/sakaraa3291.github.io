#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re
from pathlib import Path
import numpy as np
import pandas as pd

VENUES=['札幌','函館','福島','新潟','東京','中山','中京','京都','阪神','小倉','大井','船橋','川崎','浦和']
GRADE_RE=re.compile(r'\((GI|GII|GIII)\)$')

def read_master(path):
    with open(path,'rb') as f: head=f.read(2)
    return pd.read_csv(path,dtype=str,low_memory=False,compression='gzip' if head==b'\x1f\x8b' else None,encoding='utf-8-sig').fillna('')

def canonical_raw(name:str)->str:
    s=str(name or '').strip()
    s=re.sub(r'^第\d+回','',s)
    s=GRADE_RE.sub('',s)
    return s.strip()

def resolve_key(raw:str, base_keys:set[str])->str:
    if raw in base_keys:
        return raw
    # 2026 official short-name spelling seen in source; preserve existing app key when obvious.
    if raw.endswith('C') and raw[:-1]+'カップ' in base_keys:
        return raw[:-1]+'カップ'
    return raw

def parse_laps(s):
    try:return [float(x) for x in str(s).split('-') if str(x).strip()]
    except Exception:return []

def segdist(dist:int,n:int):
    return [dist-200*(n-1)]+[200]*(n-1)

def build(master, baseline):
    base_grade=baseline.get('grade',{})
    base_keys=set(base_grade)
    m=master.copy()
    m['_rank']=pd.to_numeric(m['着順'],errors='coerce')
    m['_winsec']=pd.to_numeric(m['走破秒'],errors='coerce')
    win=m[m['_rank']==1][['race_id','_winsec']].drop_duplicates('race_id').set_index('race_id')['_winsec'].to_dict()
    r=m[(m['競馬場'].isin(VENUES)) & m['ラップ'].ne('')].drop_duplicates('race_id').copy()
    r=r[r['レース名'].map(lambda x:bool(GRADE_RE.search(str(x))))].copy()
    r['_raw']=r['レース名'].map(canonical_raw)
    r['_key']=r['_raw'].map(lambda x:resolve_key(x,base_keys))
    r['_grade']=r['レース名'].str.extract(r'\((GI|GII|GIII)\)$')[0]
    r['_dist']=pd.to_numeric(r['距離'],errors='coerce')
    r['_laps']=r['ラップ'].map(parse_laps)
    r['_nseg']=r['_laps'].map(len)
    r=r[(r['_nseg']>0)&r['_dist'].notna()].sort_values(['日付','race_id'])

    out={}
    keys=list(base_grade.keys())+[k for k in r['_key'].drop_duplicates().tolist() if k not in base_grade]
    for key in keys:
        g=r[r['_key']==key].copy()
        if key in base_grade:
            old=base_grade[key]
            nseg=len(old.get('segment_distances',[]) or old.get('avg',[]))
            if nseg<=0:
                out[key]=old; continue
            use=g[g['_nseg']==nseg].copy()
            if use.empty:
                out[key]=old; continue
            meta={k:old[k] for k in ('g','v','s','dist','segment_distances')}
        else:
            if g.empty: continue
            vc=g['_nseg'].value_counts()
            nseg=int(vc.index[0])
            use=g[g['_nseg']==nseg].copy().sort_values(['日付','race_id'])
            first=use.iloc[0]
            dist=int(first['_dist'])
            surf='ダート' if first['馬場'] in ('ダ','ダート') else str(first['馬場'])
            meta={'g':str(first['_grade']),'v':str(first['競馬場']),'s':surf,'dist':dist,'segment_distances':segdist(dist,nseg)}
        use=use.sort_values(['日付','race_id'])
        yrs=[]; laps=[]
        for _,row in use.iterrows():
            ll=row['_laps']
            wt=win.get(row['race_id'])
            yrs.append({'y':str(row['年']),'d':str(row['日付']),'c':str(row['馬場状態']),'l':ll,'w':round(float(wt),1) if pd.notna(wt) else None})
            laps.append(ll)
        arr=np.asarray(laps,dtype=float)
        out[key]={**meta,'avg':np.round(arr.mean(axis=0),2).tolist(),'yrs':yrs}
        # maintain key order used by production object
        out[key]={'g':out[key]['g'],'v':out[key]['v'],'s':out[key]['s'],'dist':out[key]['dist'],'avg':out[key]['avg'],'yrs':out[key]['yrs'],'segment_distances':out[key]['segment_distances']}
    return out

def compare_exact(generated, baseline_grade):
    if generated!=baseline_grade:
        if set(generated)!=set(baseline_grade):
            raise SystemExit(f'grade key mismatch generated={len(generated)} baseline={len(baseline_grade)} extra={sorted(set(generated)-set(baseline_grade))[:10]} missing={sorted(set(baseline_grade)-set(generated))[:10]}')
        bad=[k for k in baseline_grade if generated[k]!=baseline_grade[k]]
        raise SystemExit(f'grade value mismatch {len(bad)} records sample={bad[:10]}')
    print(f'PASS: grade baseline exact match ({len(generated)} records)')

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--master',required=True)
    ap.add_argument('--baseline',required=True)
    ap.add_argument('--out',required=True)
    ap.add_argument('--compare-baseline',action='store_true',help='Require exact grade match to baseline (for regression on baseline-era master).')
    ap.add_argument('--max-date',default='',help='Optional YYYY-MM-DD cutoff for regression/audit.')
    a=ap.parse_args()
    obj=json.load(open(a.baseline,encoding='utf-8'))
    m=read_master(a.master)
    if a.max_date:
        m=m[m['日付'].astype(str)<=a.max_date].copy()
    grade=build(m,obj)
    if a.compare_baseline: compare_exact(grade,obj.get('grade',{}))
    obj['grade']=grade
    Path(a.out).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    newkeys=sorted(set(grade)-set(json.load(open(a.baseline,encoding='utf-8')).get('grade',{})))
    print(json.dumps({'grade_records':len(grade),'new_keys':newkeys},ensure_ascii=False))
if __name__=='__main__': raise SystemExit(main())
