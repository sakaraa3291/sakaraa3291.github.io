#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, shutil, subprocess, sys
from datetime import datetime, timedelta
from pathlib import Path
import pandas as pd

def run(cmd):
    print('+',' '.join(map(str,cmd)),flush=True); subprocess.run([str(x) for x in cmd],check=True)
def readj(p):return json.load(open(p,encoding='utf-8'))
def main():
    ap=argparse.ArgumentParser(description='End-to-end resumable JRA data update: discover -> fetch -> validate -> master/payout -> PWA JSON -> release gate.')
    ap.add_argument('--master',required=True); ap.add_argument('--payout',required=True); ap.add_argument('--pedigree',required=True); ap.add_argument('--baseline-lap',required=True)
    ap.add_argument('--to-date',required=True); ap.add_argument('--from-date',default=''); ap.add_argument('--target-csv',default='',help='Optional prebuilt target; skips live discovery')
    ap.add_argument('--workdir',required=True); ap.add_argument('--delay',type=float,default=.5); ap.add_argument('--batch-size',type=int,default=12)
    ap.add_argument('--release-config',default='',help='JSON with app_version,dataset_id,courses_sha256,elevation_sha256')
    ap.add_argument('--dataset-id',default=''); ap.add_argument('--courses-sha',default=''); ap.add_argument('--elevation-sha',default=''); ap.add_argument('--app-version',default='3.8.0')
    a=ap.parse_args(); root=Path(__file__).resolve().parents[1]; W=Path(a.workdir).resolve(); W.mkdir(parents=True,exist_ok=True)
    # Terminal markers are per-run outputs. Never let a previous successful run make a later NO_CHANGES/failed run look publishable.
    for marker in ('UPDATE_READY','NO_CHANGES','PRODUCTION_PUBLISHED.json'):
        (W/marker).unlink(missing_ok=True)
    if a.release_config:
        c=readj(a.release_config); a.app_version=c['app_version']; a.dataset_id=c['dataset_id']; a.courses_sha=c['courses_sha256']; a.elevation_sha=c['elevation_sha256']
    if not (a.dataset_id and a.courses_sha and a.elevation_sha): raise SystemExit('release config/static hashes missing')
    base=readj(a.baseline_lap); prev_to=str(base.get('meta',{}).get('to',''))
    if a.from_date: start=a.from_date
    else:
        if not prev_to: raise SystemExit('baseline lap meta.to missing; supply --from-date')
        start=(datetime.strptime(prev_to,'%Y-%m-%d').date()+timedelta(days=1)).isoformat()
    if start>a.to_date:
        (W/'NO_CHANGES').write_text(f'baseline already through {prev_to}\n',encoding='utf-8'); print(json.dumps({'status':'NO_CHANGES','baseline_to':prev_to,'requested_to':a.to_date},ensure_ascii=False)); return 0
    target=W/'target.csv'
    if a.target_csv:
        shutil.copyfile(a.target_csv,target)
    else:
        run([sys.executable,root/'tools'/'discover_race_ids.py','--from-date',start,'--to-date',a.to_date,'--existing-master',a.master,'--out',target,'--delay',str(min(a.delay,.5))])
    t=pd.read_csv(target,dtype=str,encoding='utf-8-sig',low_memory=False).fillna('')
    if not {'race_id','date'} <= set(t.columns): raise SystemExit('target race_id/date required')
    if t['race_id'].duplicated().any() or not t['race_id'].str.fullmatch(r'\d{12}').all(): raise SystemExit('invalid/duplicate target race IDs')
    if not t['race_id'].str.slice(4,6).isin([f'{n:02}' for n in range(1,11)]).all(): raise SystemExit('non-JRA target race ID')
    if not t['date'].between(start,a.to_date).all(): raise SystemExit('target outside requested date range')
    existing=pd.read_csv(a.master,dtype=str,usecols=['race_id'])['race_id']
    t=t[~t['race_id'].isin(set(existing))]
    t.to_csv(target,index=False,encoding='utf-8-sig')
    if t.empty:
        (W/'NO_CHANGES').write_text(f'no new races {start}..{a.to_date}\n',encoding='utf-8'); print(json.dumps({'status':'NO_CHANGES','from':start,'to':a.to_date},ensure_ascii=False)); return 0
    # Published/state cutoff tracks actual race data, not an empty trailing calendar day.
    a.to_date=t['date'].max()
    delta=W/'delta'
    if (delta/'race_meta_delta.csv').exists():
        cached=pd.read_csv(delta/'race_meta_delta.csv',dtype=str)
        if not set(cached.race_id)<=set(t.race_id): raise SystemExit('checkpoint contains races outside current target; use a fresh workdir')
    run([sys.executable,root/'tools'/'fetch_delta_resumable.py','--input',target,'--out',delta,'--existing-pedigree',a.pedigree,'--delay',str(a.delay),'--batch-size',str(a.batch_size)])
    run([sys.executable,root/'tools'/'validate_delta_complete.py','--target',target,'--delta-dir',delta,'--base-pedigree',a.pedigree,'--strict'])
    state=W/'state'; state.mkdir(exist_ok=True)
    master2=state/'keiba_master.csv.gz'; pedcsv=state/'horse_pedigree.csv'; payout2=state/'payout.csv.gz'
    run([sys.executable,root/'tools'/'update_master_incremental.py','--master',a.master,'--delta-dir',delta,'--existing-pedigree',a.pedigree,'--out-master',master2,'--out-pedigree',pedcsv])
    run([sys.executable,root/'tools'/'update_payout_incremental.py','--payout',a.payout,'--delta-dir',delta,'--out',payout2])
    build=W/'build'; build.mkdir(exist_ok=True)
    cond=build/'lapdata_cond.json'; lap=build/'lapdata.json'; pedstats=build/'pedigree_stats.json'
    run([sys.executable,root/'tools'/'rebuild_lapdata_cond.py','--master',master2,'--baseline',a.baseline_lap,'--out',cond,'--dataset-id',a.dataset_id])
    run([sys.executable,root/'tools'/'update_grade_records_incremental.py','--master',master2,'--baseline',a.baseline_lap,'--cond',cond,'--out',lap,'--to-date',a.to_date,'--dataset-id',a.dataset_id])
    run([sys.executable,root/'tools'/'rebuild_pedigree_stats.py','--master',master2,'--payout',payout2,'--sire-map',root/'mappings'/'sire_grandsire_major_map.csv','--damsire-map',root/'mappings'/'damsire_major_map.csv','--stallion-map',root/'mappings'/'stallion_display_map.csv','--out',pedstats,'--dataset-id',a.dataset_id,'--to-date',a.to_date])
    release=W/'release'
    run([sys.executable,root/'tools'/'package_data_release_incremental.py','--lap',lap,'--pedigree',pedstats,'--out-dir',release,'--dataset-id',a.dataset_id,'--app-version',a.app_version,'--courses-sha',a.courses_sha,'--elevation-sha',a.elevation_sha])
    run([sys.executable,root/'tools'/'validate_release_candidate.py','--release-dir',release,'--baseline-lap',a.baseline_lap,'--to-date',a.to_date,'--dataset-id',a.dataset_id])
    rep={'status':'UPDATE_READY','from':start,'to':a.to_date,'new_races':len(t),'workdir':str(W),'release':str(release),'state_master':str(master2),'state_payout':str(payout2),'state_pedigree':str(pedcsv)}
    (W/'update_report.json').write_text(json.dumps(rep,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); (W/'UPDATE_READY').write_text('all fail-closed gates passed\n',encoding='utf-8'); print(json.dumps(rep,ensure_ascii=False,indent=2)); return 0
if __name__=='__main__': raise SystemExit(main())
