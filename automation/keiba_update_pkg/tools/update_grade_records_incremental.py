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


# These are explicitly checked abbreviations of the same race title.
# Do not alias the historical Procyon/Tokai race-name swaps: a unique lap
# is not by itself proof that an event belongs under another race title.
VERIFIED_ALIASES={
    'アイビスサマーD': ('アイビスSD',),
    'エルムステークス': ('エルムS',),
    'クイーンステークス': ('クイーンS',),
    'レパードステークス': ('レパードS',),
    '中京2歳ステークス': ('中京2歳S',),
    '新潟2歳ステークス': ('新潟2歳S',),
    '日刊スポシンザン記念': ('シンザン記念',),
    '東海ステークス': ('東海S',),
    '関西TVローズS': ('ローズS',),
}


def rebuild_yearly_course_groups(grade, master, to_date):
    '''Recalculate averages from individually verified same-course seasons.

    This does not insert omitted historical seasons or replace original manual
    lap/time figures. Unmatched annual records remain in yrs and are reported,
    but never participate in a course average.
    '''
    from collections import defaultdict
    names=set(grade)
    dates={str(y['d']) for r in grade.values() for y in r['yrs']}
    m=master[(master['日付'].isin(dates)) & (master['日付']<=to_date)].drop_duplicates('race_id').copy()
    m['_canonical']=m['レース名'].map(lambda v:canonical(v,names))
    by_name=defaultdict(list)
    by_date=defaultdict(list)
    for x in m.to_dict('records'):
        by_name[(str(x['_canonical']),str(x['日付']))].append(x)
        by_date[str(x['日付'])].append(x)

    verified=0
    alias_verified=[]
    unresolved=[]
    group_count=0
    mixed_count=0
    for race,r in grade.items():
        buckets=defaultdict(list)
        for i,y in enumerate(r['yrs']):
            when=str(y['d'])
            matches=by_name.get((race,when),[])
            matched_by='exact_name'
            if not matches:
                for alias in VERIFIED_ALIASES.get(race,()):
                    matches.extend(by_name.get((alias,when),[]))
                matched_by='verified_alias'
            candidate=None
            if len(matches)==1:
                candidate=matches[0]
                if matched_by=='verified_alias':
                    # Require complete lap agreement before resolving aliases.
                    try:
                        raw=[float(v) for v in str(candidate['ラップ']).split('-')]
                    except (TypeError,ValueError):
                        raw=[]
                    known=[float(v) for v in y['l']]
                    if len(raw)!=len(known) or any(abs(a-b)>0.001 for a,b in zip(raw,known)):
                        candidate=None
            if candidate is None:
                # A same-date, exact-lap candidate may help manual reconciliation;
                # it must not automatically migrate across different race titles.
                possible=[]
                for x in by_date.get(when,[]):
                    try: raw=[float(v) for v in str(x['ラップ']).split('-')]
                    except (TypeError,ValueError):continue
                    if len(raw)==len(y['l']) and all(abs(a-float(b))<=0.001 for a,b in zip(raw,y['l'])):
                        possible.append({'race_id':str(x['race_id']),'name':str(x['レース名'])})
                unresolved.append({'race':race,'date':when,
                                   'reason':'no_unique_verified_race_name_and_laps',
                                   'possible_source_records':possible[:3]})
                continue
            try:
                venue=str(candidate['競馬場'])
                surface={'ダ':'ダート'}.get(str(candidate['馬場']),str(candidate['馬場']))
                distance=int(float(candidate['距離']))
                rid=str(candidate['race_id'])
                if surface not in {'芝','ダート'}:
                    raise ValueError('not flat-racing surface')
                if len(y['l'])!=(distance+199)//200:
                    raise ValueError('lap length inconsistent with actual course')
            except (ValueError,TypeError,KeyError) as exc:
                raise ValueError(f'course provenance invalid: {race} {when}: {exc}') from exc
            # A rerun must never overwrite an already verified different source.
            for field,value in [('v',venue),('s',surface),('dist',distance),('race_id',rid)]:
                if field in y and y[field]!=value:
                    raise ValueError(f'year source conflict: {race} {when} {field}')
                y[field]=value
            buckets[(venue,surface,distance)].append(i)
            verified+=1
            if matched_by=='verified_alias':
                alias_verified.append({'race':race,'date':when,'source_name':candidate['レース名'],'race_id':rid})

        # A new publication must be explicit about all grouped averages.
        if not buckets:
            # Synthetic/legacy archives lacking provenance must keep their
            # original manual rows. Publication validation rejects empty groups
            # in a real full-dataset candidate; do not manufacture a venue.
            r.pop('groups',None)
            continue
        primary=(str(r['v']),str(r['s']),int(r['dist']))
        if primary not in buckets:
            raise ValueError(f'representative grade course not source-verified: {race} {primary}')
        groups=[]
        for (venue,surface,distance),indices in buckets.items():
            lengths={len(r['yrs'][i]['l']) for i in indices}
            if lengths!={(distance+199)//200}:
                raise ValueError(f'inconsistent course-group lap lengths: {race}')
            avg=np.round(np.asarray([r['yrs'][i]['l'] for i in indices],dtype=float).mean(axis=0),2).tolist()
            groups.append({'v':venue,'s':surface,'dist':distance,
                           'avg':avg,'segment_distances':segdist(distance,len(avg)),
                           'year_indices':indices})
        groups.sort(key=lambda g:( (g['v'],g['s'],g['dist'])!=primary,
                                  -int(max(r['yrs'][i]['d'] for i in g['year_indices']).replace('-','')),
                                  -len(g['year_indices']),g['v'],g['s'],g['dist']))
        r['groups']=groups
        r['avg']=next(g['avg'] for g in groups if (g['v'],g['s'],g['dist'])==primary)
        r['segment_distances']=segdist(primary[2],len(r['avg']))
        group_count+=len(groups)
        mixed_count+=len(groups)>1
    return {'verified_years':verified,'alias_verified':alias_verified,
            'unresolved':unresolved,'groups':group_count,
            'multi_course_races':mixed_count,
            'policy':'歴代年別ラップを保持し、元マスタと競走名・日付を照合した開催場・芝ダート・距離が一致する年だけで平均する。内外回りは未分類。'}


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
    # The source's grade icon is now kept in a dedicated master column.
    # Historic '(GI)' suffixes remain supported without renaming races.
    if 'grade' not in r:
        r['grade']=''
    suffix_grade=r['レース名'].map(lambda s: GRADE_RE.search(str(s)).group(1) if GRADE_RE.search(str(s)) else '')
    collision=r['grade'].ne('') & suffix_grade.ne('') & r['grade'].ne(suffix_grade)
    if collision.any():
        raise ValueError('explicit grade conflicts with name suffix')
    r['_grade_code']=r['grade'].where(r['grade'].ne(''),suffix_grade)
    r=r.loc[r['_grade_code'].isin({'GI','GII','GIII'})].sort_values(['日付','race_id'])

    added=[]; excluded=[]; course_variants=[]
    for _,x in r.iterrows():
        ll=parse_laps(x['ラップ'])
        if not ll: continue
        key=canonical(x['レース名'],existing)
        surf='ダート' if x['馬場'] in ('ダ','ダート') else str(x['馬場'])
        dist=int(float(x['距離']))
        if key not in grade:
            g=str(x['_grade_code'])
            grade[key]={'g':g,'v':str(x['競馬場']),'s':surf,'dist':dist,'avg':ll,'yrs':[],
                        'segment_distances':segdist(dist,len(ll))}
            existing.add(key)
        rec=grade[key]
        expected=[str(rec.get('v')),str(rec.get('s')),int(rec.get('dist')),len(rec.get('segment_distances',[]))]
        actual=[str(x['競馬場']),surf,dist,len(ll)]
        if expected!=actual:
            # Keep both actual courses as separate groups instead of silently
            # mixing or discarding a valid relocation season.
            course_variants.append({'race_id':str(x['race_id']),'key':key,'date':str(x['日付']),
                                    'actual':actual,'nominal':expected})
        wt=win.get(x['race_id'])
        yr={'y':str(x['年']),'d':str(x['日付']),'c':str(x['馬場状態']),'l':ll,
            'w':round(float(wt),1) if wt is not None and pd.notna(wt) else None}
        # Idempotent reruns: replace the same date instead of duplicating it.
        yrs=[y for y in rec.get('yrs',[]) if str(y.get('d'))!=yr['d']]
        yrs.append(yr); yrs=sorted(yrs,key=lambda y:(str(y.get('d','')),str(y.get('y',''))))
        rec['yrs']=yrs
        # A race may have changed distance; do not compute a combined average.
        # Verified same-course averages are built after all seasons are merged.
        grade[key]={'g':rec['g'],'v':rec['v'],'s':rec['s'],'dist':rec['dist'],'avg':rec['avg'],
                    'yrs':rec['yrs'],'segment_distances':rec['segment_distances']}
        added.append({'race_id':str(x['race_id']),'key':key,'date':str(x['日付'])})

    course_audit=rebuild_yearly_course_groups(grade,m,a.to_date)
    out['grade']=grade
    out.setdefault('meta',{})['to']=a.to_date
    out['meta']['dataset_id']=a.dataset_id
    out['meta'].setdefault('audit',{})['grade_course_groups']=course_audit
    out['meta'].setdefault('audit',{})['incremental_grade_update']={
        'from_exclusive':from_date,'to_inclusive':a.to_date,'added':added,
        'excluded':excluded,'course_variants':course_variants,
        'policy':'既存の年別ラップを保持し、新規重賞は実開催コース別に追加。単一コースの年だけで平均する'
    }
    Path(a.out).write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({'grade_records':len(grade),'races_seen':len(r),'added':len(added),'excluded':len(excluded),
                      'from_exclusive':from_date,'to_inclusive':a.to_date,
                      'added_dates':sorted(set(x['date'] for x in added))},ensure_ascii=False,indent=2))

if __name__=='__main__': raise SystemExit(main())
