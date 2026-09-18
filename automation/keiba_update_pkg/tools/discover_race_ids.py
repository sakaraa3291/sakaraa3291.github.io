#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re, time
from datetime import date, datetime, timedelta
from pathlib import Path
import pandas as pd
import requests

URL='https://race.sp.netkeiba.com/?pid=race_list&kaisai_date={ymd}'
UA='Mozilla/5.0 (compatible; keiba-data-maintenance/3.0; +https://github.com/sakaraa3291/sakaraa3291.github.io)'
RID_RE=re.compile(r'race_id=(\d{12})')

def days(a:date,b:date):
    while a<=b:
        yield a; a+=timedelta(days=1)

def parse_ids(html:str,d:date)->list[str]:
    out=[]; seen=set()
    for rid in RID_RE.findall(html.replace('&amp;','&')):
        if rid in seen or rid[:4]!=str(d.year): continue
        try: venue=int(rid[4:6])
        except ValueError: continue
        if not (1<=venue<=10): continue  # JRA 10 venues only
        seen.add(rid); out.append(rid)
    return sorted(out)

def validate_day(html, ids):
    # An HTTP 200 challenge/changed layout is not evidence of an empty meeting day.
    from bs4 import BeautifulSoup
    text=BeautifulSoup(html,'html.parser').get_text(' ',strip=True)
    if not ids:
        if not re.search(r'(?:開催|レース)(?:は|が)ありません',text):
            raise RuntimeError('no race IDs and no explicit no-meeting notice; refusing to advance cutoff')
        return
    meetings={rid[:10] for rid in ids}
    for meeting in meetings:
        numbers={int(rid[-2:]) for rid in ids if rid.startswith(meeting)}
        if numbers!=set(range(1,13)):
            raise RuntimeError(f'incomplete meeting list: {meeting}: {sorted(numbers)}')

def read_existing(path:str)->set[str]:
    if not path: return set()
    p=Path(path)
    if not p.exists(): return set()
    comp='gzip' if p.read_bytes()[:2]==b'\x1f\x8b' else None
    d=pd.read_csv(p,dtype=str,encoding='utf-8-sig',compression=comp,low_memory=False,usecols=['race_id']).fillna('')
    return set(d['race_id'].astype(str))

def fetch(session,url,retries=3):
    last=None
    for i in range(retries):
        try:
            r=session.get(url,timeout=20); r.raise_for_status()
            if len(r.content)<1000: raise RuntimeError(f'short response {len(r.content)}')
            return r.text
        except Exception as e:
            last=e
            if i+1<retries: time.sleep(1.5*(i+1))
    raise RuntimeError(f'list fetch failed: {url}: {last}')

def atomic_csv(df:pd.DataFrame,path:Path):
    tmp=path.with_suffix(path.suffix+'.tmp')
    df.to_csv(tmp,index=False,encoding='utf-8-sig'); tmp.replace(path)

def main():
    ap=argparse.ArgumentParser(description='Discover JRA race_ids from netkeiba mobile race-list pages.')
    ap.add_argument('--from-date',required=True)
    ap.add_argument('--to-date',required=True)
    ap.add_argument('--existing-master',default='')
    ap.add_argument('--out',required=True)
    ap.add_argument('--delay',type=float,default=.25)
    a=ap.parse_args()
    lo=datetime.strptime(a.from_date,'%Y-%m-%d').date(); hi=datetime.strptime(a.to_date,'%Y-%m-%d').date()
    if hi<lo: raise SystemExit('to-date precedes from-date')
    existing=read_existing(a.existing_master)
    s=requests.Session(); s.headers.update({'User-Agent':UA,'Accept-Language':'ja,en;q=0.8'})
    rows=[]; audit=[]; out=Path(a.out); out.parent.mkdir(parents=True,exist_ok=True)
    for i,d in enumerate(days(lo,hi)):
        html=fetch(s,URL.format(ymd=d.strftime('%Y%m%d')))
        ids=parse_ids(html,d); validate_day(html,ids); new=[x for x in ids if x not in existing]
        rows.extend({'race_id':x,'date':d.isoformat()} for x in new)
        audit.append({'date':d.isoformat(),'found':len(ids),'new':len(new)})
        atomic_csv(pd.DataFrame(rows,columns=['race_id','date']).drop_duplicates('race_id'),out)
        if i and a.delay: time.sleep(a.delay)
    df=pd.DataFrame(rows,columns=['race_id','date']).drop_duplicates('race_id').sort_values(['date','race_id']) if rows else pd.DataFrame(columns=['race_id','date'])
    atomic_csv(df,out)
    rep={'from':lo.isoformat(),'to':hi.isoformat(),'found_new':len(df),'existing_ids':len(existing),'days':audit}
    out.with_suffix('.report.json').write_text(json.dumps(rep,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'from':rep['from'],'to':rep['to'],'new_races':rep['found_new']},ensure_ascii=False))
if __name__=='__main__': raise SystemExit(main())
