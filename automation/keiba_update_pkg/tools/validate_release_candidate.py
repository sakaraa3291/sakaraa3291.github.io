#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, math, re
from pathlib import Path
import pandas as pd

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):return json.load(open(p,encoding='utf-8'))
def segdist(dist,n):return [dist-200*(n-1)]+[200]*(n-1)
def read_master(p):
    p=Path(p); comp='gzip' if p.read_bytes()[:2]==b'\x1f\x8b' else None
    return pd.read_csv(p,dtype=str,encoding='utf-8-sig',compression=comp,low_memory=False).fillna('')
def check_laps(l,dist,ds=None):
    assert isinstance(l,list) and len(l)==math.ceil(dist/200) and all(isinstance(x,(int,float)) and math.isfinite(x) and x>0 for x in l)
    if ds is not None: assert ds==segdist(dist,len(l))
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--release-dir',required=True); ap.add_argument('--baseline-lap',required=True); ap.add_argument('--to-date',required=True); ap.add_argument('--dataset-id',required=True)
    ap.add_argument('--target-master',default=''); ap.add_argument('--target-payout',default=''); ap.add_argument('--expected-target-races',type=int,default=0); ap.add_argument('--expected-added-grade',type=int,default=-1)
    a=ap.parse_args(); R=Path(a.release_dir); ver=load(R/'data-version.json'); lap=load(R/'lapdata.json'); ped=load(R/'pedigree_stats.json'); base=load(a.baseline_lap)
    assert ver['schema_version']==2 and ver['app_version']=='3.8.0' and ver['dataset_id']==a.dataset_id
    assert lap['meta']['dataset_id']==ped['meta']['dataset_id']==a.dataset_id
    assert sha(R/'lapdata.json')==ver['files']['lapdata.json']; assert sha(R/'pedigree_stats.json')==ver['files']['pedigree_stats.json']
    assert re.fullmatch(r'[a-f0-9]{64}',ver['files']['courses.json']); assert re.fullmatch(r'[a-f0-9]{64}',ver['files']['elevation.json'])
    # Lap/core-like validation.
    total=0
    for k,r in lap['cond'].items():
        p=k.split('|'); assert len(p)==5 and p[1] in {'芝','ダート'}; dist=int(p[2]); check_laps(r['l'],dist,r['segment_distances']); assert int(r['n'])>0; total+=int(r['n'])
    assert total==int(lap['meta']['races']); assert lap['meta']['to']<=a.to_date
    for k,r in lap['grade'].items():
        assert r['s'] in {'芝','ダート'}; dist=int(r['dist']); check_laps(r['avg'],dist,r['segment_distances'])
        assert r['yrs']
        for y in r['yrs']:
            yd=int(y.get('dist',dist))
            check_laps(y['l'],yd,y.get('segment_distances'))
            assert y['d']<=a.to_date or y in base.get('grade',{}).get(k,{}).get('yrs',[])
        # Every published average is for one source-verified course only.
        gs=r.get('groups')
        assert isinstance(gs,list) and gs,('missing grade course groups',k)
        used=set(); group_keys=set(); home=None
        for group in gs:
            venue,surf,gd=group['v'],group['s'],int(group['dist'])
            ident=(venue,surf,gd)
            assert venue and surf in {'芝','ダート'} and ident not in group_keys,(k,ident)
            group_keys.add(ident)
            check_laps(group['avg'],gd,group['segment_distances'])
            ix=group['year_indices']
            assert isinstance(ix,list) and len(ix)>0 and ix==sorted(set(ix)),('bad year indices',k)
            for i in ix:
                assert isinstance(i,int) and 0<=i<len(r['yrs']) and i not in used,(k,i)
                used.add(i)
                year=r['yrs'][i]
                assert (year.get('v'),year.get('s'),year.get('dist'))==ident,(k,year['d'])
                assert str(year.get('race_id','')).isdigit(),('unverified grade year',k,year['d'])
            for j,a_value in enumerate(group['avg']):
                mean=sum(float(r['yrs'][i]['l'][j]) for i in ix)/len(ix)
                assert abs(float(a_value)-mean)<=0.011,('mixed grade average',k,ident,j)
            if ident==(r['v'],r['s'],dist):
                home=group
        assert home is not None and home['avg']==r['avg'],('representative grade average differs',k)
        for i,y in enumerate(r['yrs']):
            tagged=any(key in y for key in ('v','s','dist','race_id'))
            assert (i in used)==tagged,('verified grade year omitted from group',k,y['d'])
    # Existing annual lap/time/notes remain unchanged; new source-course fields are additive.
    added=[]
    for k,br in base['grade'].items():
        assert k in lap['grade']; fr=lap['grade'][k]
        for field in ('v','s','g','dist'): assert fr.get(field)==br.get(field),(k,field,fr.get(field),br.get(field))
        fys={(str(y.get('y')),str(y.get('d'))):y for y in fr.get('yrs',[])}
        for y in br.get('yrs',[]):
            updated=fys.get((str(y.get('y')),str(y.get('d'))))
            assert updated is not None,('grade history missing',k,y.get('d'))
            assert all(updated.get(f)==value for f,value in y.items()),('grade historical changed',k,y.get('d'))
            assert set(updated)-set(y) <= {'v','s','dist','race_id'},('unexpected grade year metadata',k,y.get('d'))
        bkeys={(str(y.get('y')),str(y.get('d'))) for y in br.get('yrs',[])}
        added.extend((k,y) for y in fr.get('yrs',[]) if (str(y.get('y')),str(y.get('d'))) not in bkeys)
    if a.expected_added_grade>=0: assert len(added)==a.expected_added_grade,(len(added),a.expected_added_grade)
    # Pedigree/core-like validation.
    assert ped['meta']['schema_version']==2 and int(ped['meta']['source_rows'])>=0 and ped['meta']['audit']['to']<=a.to_date
    for k,r in ped['stats'].items():
        p=k.split('|'); assert len(p)==5 and p[1] in {'芝','ダート'}; n=int(r['n']); assert n>0
        for layer in ('sire_line','damsire_line','cross_major','stallion'):
            assert isinstance(r[layer],list)
            for x in r[layer]:
                assert str(x['name']).strip() and 0<int(x['starts'])<=n
                for f in ('win_rate','top2_rate','place_rate'):
                    v=x[f]; assert v is None or 0<=float(v)<=100
    target={}
    if a.target_master:
        m=read_master(a.target_master); rr=m.drop_duplicates('race_id')
        target={'rows':len(m),'races':m.race_id.nunique(),'surface':rr['馬場'].value_counts().to_dict(),'unique_horses':m.loc[m['馬ID']!='','馬ID'].nunique(),'horse_id_blank':int((m['馬ID']=='').sum())}
        if a.expected_target_races: assert target['races']==a.expected_target_races
        flat=rr[rr['馬場'].isin(['芝','ダート'])]; obs=rr[rr['馬場']=='障害']; target['flat_races']=len(flat); target['flat_lap']=int(flat['ラップ'].str.strip().ne('').sum()); target['obstacle_races']=len(obs); target['obstacle_lap']=int(obs['ラップ'].str.strip().ne('').sum())
        assert target['flat_lap']==target['flat_races']; assert target['obstacle_lap']==0; assert target['horse_id_blank']==0
        for c in ('レース名','距離','馬場状態'): assert rr[c].astype(str).str.strip().ne('').all()
        rank=m['着順'].astype(str).str.replace('.0','',regex=False); winners=m[rank=='1']; assert winners.race_id.nunique()==target['races']; assert winners['タイム'].str.strip().ne('').all()
    payout={}
    if a.target_payout:
        p=pd.read_csv(a.target_payout,dtype=str,encoding='utf-8-sig',sep='\t',low_memory=False).fillna(''); payout={'rows':len(p),'races':p.race_id.nunique()}; assert payout['races']==target.get('races',payout['races'])
    rep={'status':'PASS','dataset_id':a.dataset_id,'lap_conditions':len(lap['cond']),'lap_races':lap['meta']['races'],'grade_keys':len(lap['grade']),'grade_rows_added':len(added),'pedigree_conditions':len(ped['stats']),'pedigree_source_rows':ped['meta']['source_rows'],'to':lap['meta']['to'],'target':target,'payout':payout,'hashes':ver['files']}
    (R/'validation_report.json').write_text(json.dumps(rep,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(json.dumps(rep,ensure_ascii=False,indent=2))
if __name__=='__main__':raise SystemExit(main())
