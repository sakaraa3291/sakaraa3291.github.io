#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, shutil, subprocess, sys, tempfile
from pathlib import Path
import pandas as pd

SPECS={
 'race_meta_delta.csv':['race_id'],
 'race_laps_delta.csv':['race_id'],
 'horse_details_delta.csv':['race_id','馬番'],
 'race_corners_delta.csv':['race_id','馬番'],
 'payout_delta.csv':['race_id','券種','組み合わせ'],
 'errors.csv':['race_id'],
}

def rd(p:Path):
    if not p.exists(): return pd.DataFrame()
    try:return pd.read_csv(p,dtype=str,encoding='utf-8-sig',low_memory=False).fillna('')
    except pd.errors.EmptyDataError:return pd.DataFrame()

def wr(d:pd.DataFrame,p:Path):
    tmp=p.with_suffix(p.suffix+'.tmp'); d.to_csv(tmp,index=False,encoding='utf-8-sig'); tmp.replace(p)

def merge_one(dst:Path,src:Path,keys):
    a,b=rd(dst),rd(src)
    if b.empty:return
    if '組合せ' in b.columns and '組み合わせ' not in b.columns:b=b.rename(columns={'組合せ':'組み合わせ'})
    if '組合せ' in a.columns and '組み合わせ' not in a.columns:a=a.rename(columns={'組合せ':'組み合わせ'})
    m=pd.concat([a,b],ignore_index=True,sort=False)
    use=[k for k in keys if k in m.columns]
    if use:m=m.drop_duplicates(use,keep='last')
    wr(m,dst)

def complete_ids(out:Path):
    meta=rd(out/'race_meta_delta.csv'); det=rd(out/'horse_details_delta.csv'); cor=rd(out/'race_corners_delta.csv'); pay=rd(out/'payout_delta.csv'); lap=rd(out/'race_laps_delta.csv')
    if any(x.empty for x in (meta,det,cor,pay)):return set()
    ids=set(meta.race_id)&set(det.race_id)&set(cor.race_id)&set(pay.race_id)
    lapids=set(lap.race_id) if not lap.empty else set()
    surf=dict(zip(meta.race_id.astype(str),meta.get('surface',pd.Series('',index=meta.index)).astype(str)))
    return {r for r in ids if surf.get(str(r))=='障' or str(r) in lapids}

def main():
    ap=argparse.ArgumentParser(description='Checkpointed/resumable race delta fetcher.')
    ap.add_argument('--input',required=True); ap.add_argument('--out',required=True); ap.add_argument('--existing-pedigree',required=True)
    ap.add_argument('--delay',type=float,default=.5); ap.add_argument('--batch-size',type=int,default=12)
    a=ap.parse_args(); root=Path(__file__).resolve().parents[1]; out=Path(a.out); out.mkdir(parents=True,exist_ok=True)
    target=pd.read_csv(a.input,dtype=str,encoding='utf-8-sig',low_memory=False).fillna('').drop_duplicates('race_id')
    done=complete_ids(out); pending=target[~target.race_id.astype(str).isin(done)].copy()
    print(json.dumps({'target':len(target),'already_complete':len(done & set(target.race_id.astype(str))),'pending':len(pending)},ensure_ascii=False),flush=True)
    for start in range(0,len(pending),a.batch_size):
        batch=pending.iloc[start:start+a.batch_size]
        with tempfile.TemporaryDirectory() as td0:
            td=Path(td0); inp=td/'batch.csv'; bo=td/'out'; batch.to_csv(inp,index=False,encoding='utf-8-sig')
            cmd=[sys.executable,str(root/'tools'/'fetch_netkeiba_delta.py'),'--input',str(inp),'--out',str(bo),'--delay',str(a.delay)]
            cp=subprocess.run(cmd)
            for f,keys in SPECS.items(): merge_one(out/f,bo/f,keys)
            # Successful rows supersede an earlier error for the same race.
            e=rd(out/'errors.csv'); c=complete_ids(out)
            if not e.empty: wr(e[~e.race_id.astype(str).isin(c)],out/'errors.csv')
            print(json.dumps({'batch_start':start,'batch_rows':len(batch),'returncode':cp.returncode,'complete_total':len(complete_ids(out))},ensure_ascii=False),flush=True)
    done=complete_ids(out); target_ids=set(target.race_id.astype(str)); missing=sorted(target_ids-done)
    if missing:
        (out/'resume_report.json').write_text(json.dumps({'status':'INCOMPLETE','missing':missing},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(f'INCOMPLETE: {len(missing)} races; rerun resumes from checkpoints',file=sys.stderr); return 2
    # Enrich metadata and fetch only pedigrees not already in historical + this delta.
    cmd=[sys.executable,str(root/'tools'/'fetch_netkeiba_delta_v2.py'),'--input',a.input,'--out',str(out),'--postprocess-only','--existing-pedigree',a.existing_pedigree,'--delay',str(a.delay)]
    cp=subprocess.run(cmd)
    if cp.returncode: return cp.returncode
    (out/'resume_report.json').write_text(json.dumps({'status':'COMPLETE','races':len(target)},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return 0
if __name__=='__main__': raise SystemExit(main())
