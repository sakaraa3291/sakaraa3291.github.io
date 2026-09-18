#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re
from pathlib import Path
import numpy as np
import pandas as pd

GRADE_RE=re.compile(r'\((GI|GII|GIII)\)$')


def read_master(path):
    with open(path,'rb') as f: head=f.read(2)
    return pd.read_csv(path,dtype=str,low_memory=False,compression='gzip' if head==b'\x1f\x8b' else None,encoding='utf-8-sig').fillna('')


def canonical(name:str, existing:set[str])->str:
    s=re.sub(r'^第\d+回','',str(name or '').strip())
    s=GRADE_RE.sub('',s).strip()
    aliases={'朝日セントライト記念':'セントライト記念'}
    s=aliases.get(s,s)
    if s.endswith('C') and s[:-1]+'カップ' in existing:
        s=s[:-1]+'カップ'
    return s


def parse_laps(s):
    try: return [float(x) for x in str(s).split('-') if str(x).strip()]
    except Exception: return []


def segdist(dist:int,n:int):
    return [dist-200*(n-1)]+[200]*(n-1)


def main():
    ap=argparse.ArgumentParser(description='Preserve published grade history and append only newly published graded races.')
    ap.add_argument('--master',required=True)
    ap.add_argument('--baseline',required=True,help='Current production lapdata.json; its grade object is authoritative history.')
    ap.add_argument('--cond',required=True,help='Rebuilt lapdata condition JSON to receive preserved/incremental grade data.')
    ap.add_argument('--out',required=True)
    ap.add_argument('--from-exclusive',default='',help='YYYY-MM-DD. Defaults to baseline meta.to.')
    ap.add_argument('--to-date',required=True,help='Inclusive YYYY-MM-DD upper bound; prevents accidental future-race mixing.')
    ap.add_argument('--dataset-id',default='UNPACKAGED')
    a=ap.parse_args()

    baseline=json.load(open(a.baseline,encoding='utf-8'))
    out=json.load(open(a.cond,encoding='utf-8'))
    grade=json.loads(json.dumps(baseline.get('grade',{}),ensure_ascii=False))
    existing=set(grade)
    from_date=a.from_exclusive or str(baseline.get('meta',{}).get('to',''))
    if not from_date:
        raise SystemExit('baseline meta.to missing and --from-exclusive not supplied')
    if a.to_date <= from_date:
        raise SystemExit(f'--to-date must be later than baseline cutoff: {a.to_date} <= {from_date}')

    m=read_master(a.master)
    m['_rank']=pd.to_numeric(m['着順'],errors='coerce')
    m['_winsec']=pd.to_numeric(m['走破秒'],errors='coerce')
    win=m[m['_rank']==1][['race_id','_winsec']].drop_duplicates('race_id').set_index('race_id')['_winsec'].to_dict()
    r=m[(m['日付']>from_date)&(m['日付']<=a.to_date)&(m['ラップ']!='')].drop_duplicates('race_id').copy()
    r=r.loc[r['レース名'].map(lambda s:bool(GRADE_RE.search(str(s)))).astype(bool)].sort_values(['日付','race_id'])

    added=[]; excluded=[]
    for _,x in r.iterrows():
        ll=parse_laps(x['ラップ'])
        if not ll: continue
        key=canonical(x['レース名'],existing)
        surf='ダート' if x['馬場'] in ('ダ','ダート') else str(x['馬場'])
        dist=int(float(x['距離']))
        if key not in grade:
            g=GRADE_RE.search(str(x['レース名'])).group(1)
            grade[key]={'g':g,'v':str(x['競馬場']),'s':surf,'dist':dist,'avg':ll,'yrs':[],
                        'segment_distances':segdist(dist,len(ll))}
            existing.add(key)
        rec=grade[key]
        expected=[str(rec.get('v')),str(rec.get('s')),int(rec.get('dist')),len(rec.get('segment_distances',[]))]
        actual=[str(x['競馬場']),surf,dist,len(ll)]
        if expected!=actual:
            excluded.append({'race_id':str(x['race_id']),'key':key,'date':str(x['日付']),
                             'reason':'representative_course_mismatch','actual':actual,'expected':expected})
            continue
        wt=win.get(x['race_id'])
        yr={'y':str(x['年']),'d':str(x['日付']),'c':str(x['馬場状態']),'l':ll,
            'w':round(float(wt),1) if wt is not None and pd.notna(wt) else None}
        # Idempotent reruns: replace the same date instead of duplicating it.
        yrs=[y for y in rec.get('yrs',[]) if str(y.get('d'))!=yr['d']]
        yrs.append(yr); yrs=sorted(yrs,key=lambda y:(str(y.get('d','')),str(y.get('y',''))))
        rec['yrs']=yrs
        rec['avg']=np.round(np.asarray([y['l'] for y in yrs],dtype=float).mean(axis=0),2).tolist()
        grade[key]={'g':rec['g'],'v':rec['v'],'s':rec['s'],'dist':rec['dist'],'avg':rec['avg'],
                    'yrs':rec['yrs'],'segment_distances':rec['segment_distances']}
        added.append({'race_id':str(x['race_id']),'key':key,'date':str(x['日付'])})

    out['grade']=grade
    out.setdefault('meta',{})['to']=a.to_date
    out['meta']['dataset_id']=a.dataset_id
    out['meta'].setdefault('audit',{})['incremental_grade_update']={
        'from_exclusive':from_date,'to_inclusive':a.to_date,'added':added,'excluded':excluded,
        'policy':'既存公開gradeを保持し、公開基準日より後かつ更新上限日までの代表コース一致重賞だけ追加'
    }
    Path(a.out).write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({'grade_records':len(grade),'races_seen':len(r),'added':len(added),'excluded':len(excluded),
                      'from_exclusive':from_date,'to_inclusive':a.to_date,
                      'added_dates':sorted(set(x['date'] for x in added))},ensure_ascii=False,indent=2))

if __name__=='__main__': raise SystemExit(main())
