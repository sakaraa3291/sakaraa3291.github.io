#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, shutil, subprocess, sys
from pathlib import Path
import pandas as pd

REQ_RACE_FILES = {
    'race_meta_delta.csv':'race_id',
    'race_laps_delta.csv':'race_id',
    'horse_details_delta.csv':'race_id',
    'race_corners_delta.csv':'race_id',
    'payout_delta.csv':'race_id',
}

def ids(path: Path, col='race_id') -> set[str]:
    if not path.exists(): return set()
    try:
        d=pd.read_csv(path,dtype=str,encoding='utf-8-sig',low_memory=False).fillna('')
    except pd.errors.EmptyDataError:
        return set()
    return set(d[col].astype(str)) if col in d.columns else set()

def validate_probe(target: Path, out: Path) -> tuple[bool,dict]:
    t=pd.read_csv(target,dtype=str,encoding='utf-8-sig').fillna('')
    target_ids=set(t['race_id'].astype(str))
    report={'target_count':len(target_ids),'files':{},'pedigree_errors':0}
    ok=True
    for f,col in REQ_RACE_FILES.items():
        have=ids(out/f,col)
        missing=sorted(target_ids-have)
        report['files'][f]={'covered':len(target_ids)-len(missing),'missing':missing}
        if missing: ok=False
    err=out/'errors.csv'
    if err.exists():
        try:
            e=pd.read_csv(err,dtype=str,encoding='utf-8-sig').fillna('')
            if len(e):
                report['race_errors']=e.to_dict('records'); ok=False
        except pd.errors.EmptyDataError: pass
    pe=out/'pedigree_errors.csv'
    if pe.exists():
        try:
            e=pd.read_csv(pe,dtype=str,encoding='utf-8-sig').fillna('')
            report['pedigree_errors']=len(e)
            if len(e): ok=False
        except pd.errors.EmptyDataError: pass
    ped=out/'horse_pedigree_delta.csv'
    report['pedigree_rows']=0
    if ped.exists():
        try:
            report['pedigree_rows']=len(pd.read_csv(ped,dtype=str,encoding='utf-8-sig'))
        except pd.errors.EmptyDataError: pass
    if report['pedigree_rows'] < 1: ok=False
    report['status']='READY_FOR_512' if ok else 'NOT_READY'
    return ok,report

def run(cmd:list[str]):
    print('+',' '.join(cmd),flush=True)
    subprocess.run(cmd,check=True)

def main():
    ap=argparse.ArgumentParser(description='Safe orchestration: 3-race probe, then optional 512-race fetch.')
    ap.add_argument('--mode',choices=['probe','full'],default='probe')
    ap.add_argument('--workdir',default='run_out')
    ap.add_argument('--delay',type=float,default=1.5)
    ap.add_argument('--existing-pedigree',default='')
    ap.add_argument('--keep-existing',action='store_true')
    a=ap.parse_args()
    root=Path(__file__).resolve().parents[1]
    if a.mode=='full' and not a.existing_pedigree:
        print('FULL mode requires --existing-pedigree to avoid re-fetching all historical-known horses.',file=sys.stderr)
        return 2
    out=Path(a.workdir).resolve()
    if out.exists() and not a.keep_existing:
        shutil.rmtree(out)
    out.mkdir(parents=True,exist_ok=True)
    probe=root/'targets'/'probe_3r.csv'
    full=root/'targets'/'app_target_20260725_20260913_512.csv'
    fetch=root/'tools'/'fetch_netkeiba_delta_v2.py'
    # Probe always fetches one pedigree page so the live pedigree parser is actually exercised.
    cmd=[sys.executable,str(fetch),'--input',str(probe),'--out',str(out/'probe'),'--delay',str(a.delay),'--max-pedigrees','1']
    try: run(cmd)
    except subprocess.CalledProcessError:
        pass
    ok,report=validate_probe(probe,out/'probe')
    (out/'probe_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if not ok:
        return 2
    if a.mode=='probe': return 0
    cmd=[sys.executable,str(fetch),'--input',str(full),'--out',str(out/'full'),'--delay',str(a.delay)]
    if a.existing_pedigree: cmd += ['--existing-pedigree',a.existing_pedigree]
    run(cmd)
    vcmd=[sys.executable,str(root/'tools'/'validate_delta_complete.py'),'--target',str(full),'--delta-dir',str(out/'full'),'--base-pedigree',a.existing_pedigree]
    run(vcmd)
    (out/'FULL_READY').write_text('512 race delta validation passed\n',encoding='utf-8')
    return 0

if __name__=='__main__': raise SystemExit(main())
