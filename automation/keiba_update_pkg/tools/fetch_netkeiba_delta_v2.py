#!/usr/bin/env python3
"""Run the race delta collector, enrich race metadata, then fetch only missing pedigrees."""
from __future__ import annotations
import argparse, json, re, subprocess, sys, time
from io import StringIO
from pathlib import Path
import pandas as pd
import requests
from bs4 import BeautifulSoup

UA='Mozilla/5.0 (compatible; keiba-data-maintenance/2.0; +https://github.com/sakaraa3291/sakaraa3291.github.io)'
PED='https://db.netkeiba.com/horse/ped/{horse_id}/'

def t2s(t):
    if pd.isna(t): return None
    s=str(t).strip()
    m=re.match(r'^(\d+):(\d+)\.(\d+)$',s)
    if m: return int(m[1])*60+int(m[2])+int(m[3])/10
    m=re.match(r'^(\d+)\.(\d+)$',s)
    if m: return int(m[1])+int(m[2])/10
    return None

def grade_from_name(name):
    s=str(name or '')
    for g in ('JpnIII','JpnII','JpnI','GIII','GII','GI'):
        if f'({g})' in s: return g
    if re.search(r'\(L\)',s): return 'L'
    if re.search(r'\(OP\)',s): return 'OP'
    return ''

def enrich_meta(outdir:Path):
    mp=outdir/'race_meta_delta.csv'; hp=outdir/'horse_details_delta.csv'
    if not mp.exists(): raise FileNotFoundError(mp)
    m=pd.read_csv(mp,dtype=str,encoding='utf-8-sig',low_memory=False).fillna('')
    # Repeated postprocessing must not create winner_time_x / winner_time_y columns.
    m=m.drop(columns=['winner_time','winner_time_x','winner_time_y'],errors='ignore')
    if hp.exists():
        h=pd.read_csv(hp,dtype=str,encoding='utf-8-sig',low_memory=False).fillna('')
        w=h[h['着順'].astype(str).str.strip()=='1'][['race_id','タイム']].drop_duplicates('race_id')
        w['winner_time']=w['タイム'].map(t2s)
        m=m.merge(w[['race_id','winner_time']],on='race_id',how='left')
    else: m['winner_time']=''
    m['grade']=m['レース名'].map(grade_from_name)
    m.to_csv(mp,index=False,encoding='utf-8-sig')
    return m

def decode(content:bytes):
    cand=[]
    for enc in ('euc_jp','utf-8','cp932'):
        try:
            t=content.decode(enc,errors='replace'); score=t.count('5代血統表')+t.count('血統')
            cand.append((score,t))
        except Exception: pass
    return max(cand,key=lambda x:x[0])[1] if cand else content.decode('utf-8',errors='replace')

def clean_ped_cell(x):
    s=re.sub(r'\s+',' ',str(x or '')).strip()
    # read_html cells contain the horse name first, followed by birth year / coat / helper links.
    s=re.split(r'\s+(?:18|19|20)\d{2}\s',s,maxsplit=1)[0].strip()
    s=re.sub(r'\s*\[血統\].*$','',s).strip()
    return s

def parse_pedigree(html:str,horse_id:str):
    soup=BeautifulSoup(html,'lxml')
    h1=soup.find('h1'); horse_name=h1.get_text(' ',strip=True) if h1 else ''
    table=soup.find('table',class_=lambda c: c and 'blood_table' in (c if isinstance(c,str) else ' '.join(c)))
    if table is None:
        # Fallback: pedigree table is the wide table with many rowspans.
        cand=[]
        for t in soup.find_all('table'):
            score=sum(int(td.get('rowspan','1'))>1 for td in t.find_all('td'))
            cand.append((score,t))
        table=max(cand,key=lambda x:x[0])[1] if cand and max(x[0] for x in cand)>5 else None
    if table is None: raise ValueError('pedigree table not found')
    frames=pd.read_html(StringIO(str(table)))
    if not frames: raise ValueError('pedigree table unreadable')
    df=frames[0]
    if df.shape[1]<2 or len(df)<8: raise ValueError(f'unexpected pedigree shape {df.shape}')
    n=len(df); half=n//2; q3=(3*n)//4
    vals={
        '馬ID':horse_id,'馬名':horse_name,
        '父':clean_ped_cell(df.iloc[0,0]),
        '母':clean_ped_cell(df.iloc[half,0]),
        '母父':clean_ped_cell(df.iloc[half,1]),
        '父父':clean_ped_cell(df.iloc[0,1]),
        '母母':clean_ped_cell(df.iloc[q3,1]),
    }
    if not vals['父'] or not vals['母']: raise ValueError(f'pedigree names missing {vals}')
    return vals

def fetch_pedigrees(outdir:Path,existing:str|None,delay:float,max_count:int=0):
    corners=outdir/'race_corners_delta.csv'
    if not corners.exists(): return {'requested':0,'fetched':0,'errors':0}
    c=pd.read_csv(corners,dtype=str,encoding='utf-8-sig',low_memory=False).fillna('')
    ids=[x for x in c['馬ID'].astype(str).unique().tolist() if x]
    known=set(); rows=[]; errs=[]
    if existing and Path(existing).exists():
        p=pd.read_csv(existing,dtype=str,encoding='utf-8-sig',usecols=['馬ID'],low_memory=False).fillna('')
        known=set(p['馬ID'].astype(str))
    # Resume pedigree work from this delta directory instead of fetching the same horse twice.
    own=outdir/'horse_pedigree_delta.csv'
    if own.exists():
        try:
            prev=pd.read_csv(own,dtype=str,encoding='utf-8-sig',low_memory=False).fillna('')
            rows=prev.to_dict('records'); known.update(prev.get('馬ID',pd.Series(dtype=str)).astype(str))
        except pd.errors.EmptyDataError: pass
    pe=outdir/'pedigree_errors.csv'
    if pe.exists():
        try:
            errs=pd.read_csv(pe,dtype=str,encoding='utf-8-sig',low_memory=False).fillna('').to_dict('records')
        except pd.errors.EmptyDataError: pass
    todo=[x for x in ids if x not in known]
    if max_count:
        todo=todo[:max_count]
    session=requests.Session(); session.headers.update({'User-Agent':UA,'Accept-Language':'ja,en;q=0.8'})
    for i,hid in enumerate(todo):
        try:
            r=session.get(PED.format(horse_id=hid),timeout=30); r.raise_for_status()
            rows.append(parse_pedigree(decode(r.content),hid)); errs=[e for e in errs if str(e.get('馬ID',''))!=hid]
            print(f'PED OK {hid}',flush=True)
        except Exception as e:
            errs.append({'馬ID':hid,'error':repr(e)}); print(f'PED ERROR {hid}: {e!r}',flush=True)
        pd.DataFrame(rows,columns=['馬ID','馬名','父','母','母父','父父','母母']).drop_duplicates('馬ID').to_csv(outdir/'horse_pedigree_delta.csv',index=False,encoding='utf-8-sig')
        pd.DataFrame(errs,columns=['馬ID','error']).to_csv(outdir/'pedigree_errors.csv',index=False,encoding='utf-8-sig')
        if i+1<len(todo): time.sleep(delay)
    return {'requested':len(todo),'fetched':len(rows),'errors':len(errs)}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--input',required=True)
    ap.add_argument('--out',default='delta_out')
    ap.add_argument('--delay',type=float,default=1.5)
    ap.add_argument('--limit',type=int,default=0)
    ap.add_argument('--existing-pedigree',default='')
    ap.add_argument('--postprocess-only',action='store_true')
    ap.add_argument('--skip-pedigree',action='store_true')
    ap.add_argument('--max-pedigrees',type=int,default=0)
    a=ap.parse_args(); out=Path(a.out); out.mkdir(parents=True,exist_ok=True)
    if not a.postprocess_only:
        cmd=[sys.executable,str(Path(__file__).with_name('fetch_netkeiba_delta.py')),'--input',a.input,'--out',str(out),'--delay',str(a.delay)]
        if a.limit: cmd += ['--limit',str(a.limit)]
        subprocess.run(cmd,check=True)
    meta=enrich_meta(out)
    ped={'requested':0,'fetched':0,'errors':0} if a.skip_pedigree else fetch_pedigrees(out,a.existing_pedigree or None,a.delay,a.max_pedigrees)
    print(json.dumps({'races':len(meta),'pedigree':ped},ensure_ascii=False))
    if ped['errors']: return 3
    return 0
if __name__=='__main__': raise SystemExit(main())
