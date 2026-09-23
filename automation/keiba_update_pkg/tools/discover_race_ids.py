#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re, time
from datetime import date, datetime, timedelta
from pathlib import Path
import pandas as pd
import requests
from bs4 import BeautifulSoup

URL='https://race.sp.netkeiba.com/?pid=race_list&kaisai_date={ymd}'
UA='Mozilla/5.0 (compatible; keiba-data-maintenance/3.0; +https://github.com/sakaraa3291/sakaraa3291.github.io)'
RID_RE=re.compile(r'race_id=(\d{12})')

def days(a:date,b:date):
    while a<=b:
        yield a; a+=timedelta(days=1)

def inspect_page(html:str,d:date):
    ymd=d.strftime('%Y%m%d')
    lower=html.lower()
    for marker in ('verify you are human','challenge-platform','just a moment','captcha'):
        if marker in lower:
            raise RuntimeError(f'challenge page marker detected: {marker}')
    if '</body>' not in lower or '</html>' not in lower:
        raise RuntimeError('truncated race-list page')

    soup=BeautifulSoup(html,'html.parser')
    title=soup.title.get_text(' ',strip=True) if soup.title else ''
    body=soup.body
    section=soup.select_one('section.RaceListArea.Contents_Box')
    heading=soup.select_one('.Title_Sec.RaceList_Sec h2')
    day_root=soup.select_one('#KaisaiListTop.RaceDayWrap .RaceDayWrap_Inner')
    tab_ul=soup.select_one('.Tab_RaceDaySelect ul.Tab.fc')
    description=soup.select_one('.Description_Box')
    guide=soup.select_one('.Description_Box table.Icon_Guide')
    if not (
        'レース一覧' in title and 'レース情報(JRA)' in title and 'netkeiba' in title and
        body is not None and body.get('id')=='Netkeiba_RaceTop' and
        section is not None and heading is not None and heading.get_text(' ',strip=True)=='レース一覧' and
        day_root is not None and tab_ul is not None and
        description is not None and guide is not None and 'レース一覧の見方' in description.get_text(' ',strip=True) and
        soup.footer is not None
    ):
        raise RuntimeError('race-list page structure changed or is incomplete')

    kid_match=re.search(r"_data\.kid\s*=\s*JSON\.parse\('([^']*)'\)",html)
    if not kid_match:
        raise RuntimeError('race-list meeting manifest missing')
    try:
        kids=json.loads(kid_match.group(1))
    except Exception as e:
        raise RuntimeError('race-list meeting manifest invalid') from e
    if not isinstance(kids,list):
        raise RuntimeError('race-list meeting manifest is not a list')
    for meeting in kids:
        if not isinstance(meeting,str) or not re.fullmatch(r'\d{10}',meeting):
            raise RuntimeError('invalid meeting id in race-list manifest')
        if meeting[:4]!=str(d.year) or not (1<=int(meeting[4:6])<=10):
            raise RuntimeError('non-JRA meeting id in race-list manifest')

    tabs=[]
    for li in tab_ul.find_all('li',recursive=False):
        anchors=li.select('a[data-date]')
        if len(anchors)!=1:
            raise RuntimeError('ambiguous meeting date tab')
        value=anchors[0].get('data-date','')
        if not re.fullmatch(r'\d{8}',value):
            raise RuntimeError('invalid meeting date tab')
        tabs.append(value)
    if len(tabs)!=len(set(tabs)):
        raise RuntimeError('duplicate meeting date tab')

    wraps=[]
    for wrap in soup.select('.RaceListDayWrap'):
        dates={li.get('data-kaisaidate','') for li in wrap.select('.jyo_tab li[data-kaisaidate]')}
        dates.discard('')
        if len(dates)!=1:
            raise RuntimeError('ambiguous meeting date body')
        wrap_date=next(iter(dates))
        if wrap_date not in tabs:
            raise RuntimeError('race-day body has no matching date tab')
        wraps.append((wrap_date,wrap))
    wrap_dates=[x[0] for x in wraps]
    if len(wrap_dates)!=len(set(wrap_dates)):
        raise RuntimeError('duplicate race-day body')

    raw_tokens=re.findall(r'race_id=([^&#"\'<>\s]+)',html.replace('&amp;','&'))
    for token in raw_tokens:
        if not re.fullmatch(r'\d{12}',token):
            raise RuntimeError('invalid race_id token in race-list page')
        if token[:4]!=str(d.year) or not (1<=int(token[4:6])<=10):
            raise RuntimeError('non-JRA race_id in race-list page')

    if not tabs and (wraps or kids or raw_tokens):
        raise RuntimeError('empty race-list page contains dated race content')
    if tabs and set(tabs)!=set(wrap_dates):
        raise RuntimeError('date tabs and race-day bodies disagree')
    return soup,ymd,tabs,wraps,kids


def parse_ids(html:str,d:date)->list[str]:
    _,ymd,tabs,wraps,kids=inspect_page(html,d)
    if not tabs:
        return []
    if ymd not in tabs:
        raise RuntimeError(f'requested date missing from race-list page: {ymd}')
    target=[wrap for wrap_date,wrap in wraps if wrap_date==ymd]
    if len(target)!=1:
        raise RuntimeError(f'ambiguous meeting date body for {ymd}')

    out=[]; seen=set()
    for href in (a.get('href','') for a in target[0].find_all('a',href=True)):
        for rid in RID_RE.findall(href.replace('&amp;','&')):
            if rid in seen: continue
            if rid[:4]!=str(d.year) or not (1<=int(rid[4:6])<=10):
                raise RuntimeError(f'non-JRA race_id in target body: {rid}')
            seen.add(rid); out.append(rid)
    if not out:
        raise RuntimeError(f'target date {ymd} contains no race IDs')
    meetings={rid[:10] for rid in out}
    if not meetings<=set(kids):
        raise RuntimeError(f'target race meetings missing from manifest: {sorted(meetings-set(kids))}')
    return sorted(out)


def validate_day(html:str, ids:list[str], d:date):
    _,ymd,tabs,_,_=inspect_page(html,d)
    if not tabs:
        if ids:
            raise RuntimeError('race IDs supplied for a healthy no-meeting page')
        return
    if ymd not in tabs:
        raise RuntimeError(f'requested date missing from race-list page: {ymd}')
    scoped=parse_ids(html,d)
    scoped_set=set(scoped); supplied=set(ids)
    if not supplied<=scoped_set:
        raise RuntimeError(f'race IDs are not scoped to requested date {ymd}')
    meetings={rid[:10] for rid in ids}
    for meeting in meetings:
        numbers={int(rid[-2:]) for rid in ids if rid.startswith(meeting)}
        if numbers!=set(range(1,13)):
            raise RuntimeError(f'incomplete meeting list: {meeting}: {sorted(numbers)}')
    if supplied!=scoped_set:
        raise RuntimeError(f'race IDs are not scoped to requested date {ymd}')

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
        try:
            ids=parse_ids(html,d); validate_day(html,ids,d)
        except RuntimeError as e:
            raise RuntimeError(f'{d}: {e}') from e
        new=[x for x in ids if x not in existing]
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
