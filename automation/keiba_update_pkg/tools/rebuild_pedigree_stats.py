#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
CENTRAL=['札幌','函館','福島','新潟','東京','中山','中京','京都','阪神','小倉']
DEFAULT_FROM_DATE='2021-01-02'
MAJOR=['サンデーサイレンス系','ミスタープロスペクター系','ノーザンダンサー系','ロベルト系','ナスルーラ系','その他系','不明']

def read_master(path):
    with open(path,'rb') as f:head=f.read(2)
    return pd.read_csv(path,dtype=str,low_memory=False,compression='gzip' if head==b'\x1f\x8b' else None,encoding='utf-8-sig').fillna('')
def read_csv(path):return pd.read_csv(path,dtype=str,low_memory=False,encoding='utf-8-sig').fillna('')
def horse_no(x):
    s=str(x or '').strip()
    if not s:return ''
    try:return str(int(float(s)))
    except Exception:
        m=re.search(r'\d+',s);return m.group(0) if m else s
def money(x):
    s=str(x or '').replace(',','').replace('円','').strip()
    if not s:return None
    try:return float(s)
    except Exception:return None
def load_map(path,key,value):
    d=read_csv(path)
    if key not in d or value not in d:raise SystemExit(f'mapping columns missing in {path}: expected {key},{value}')
    return dict(zip(d[key].astype(str),d[value].astype(str)))
def nonstarter_mask(frame):
    rank=frame['着順'].astype(str).str.strip()
    # 取消/除外 never started; 中止 did start and remains in the denominator.
    return rank.isin({'取消','除外','出走取消','競走除外'}) | (rank.eq('') & frame['単勝'].astype(str).str.strip().eq(''))

def confidence(n):return '高' if n>=100 else ('中' if n>=30 else '低')

def build_records(df,col,min_starts):
    d=df[['key',col,'rank','win_payout','place_payout']].copy();d['_win']=(d['rank']==1).astype(int);d['_top2']=(d['rank']<=2).astype(int);d['_place']=(d['place_payout']>0).astype(int);d['_ord']=np.arange(len(d),dtype=np.int64)
    g=d.groupby(['key',col],sort=False,dropna=False).agg(starts=('_win','size'),wins=('_win','sum'),top2=('_top2','sum'),places=('_place','sum'),win_sum=('win_payout','sum'),place_sum=('place_payout','sum'),first_ord=('_ord','min')).reset_index()
    g=g[g['starts']>=min_starts].copy();g['win_rate']=g['wins']/g['starts']*100;g['top2_rate']=g['top2']/g['starts']*100;g['place_rate']=g['places']/g['starts']*100;g['win_return']=g['win_sum']/g['starts'];g['place_return']=g['place_sum']/g['starts']
    g=g.sort_values(['key','place_rate','win_rate','starts','first_ord'],ascending=[True,False,False,False,True],kind='mergesort');g['rankpos']=g.groupby('key').cumcount();g=g[g['rankpos']<7]
    out={}
    for k,kg in g.groupby('key',sort=False):
        out[str(k)]=[{'name':getattr(r,col),'starts':int(r.starts),'win_rate':float(r.win_rate),'top2_rate':float(r.top2_rate),'place_rate':float(r.place_rate),'win_return':float(r.win_return),'place_return':float(r.place_return),'place_missing':0,'win_payout_missing':0,'place_payout_missing':0,'confidence':confidence(int(r.starts))} for r in kg.itertuples(index=False)]
    return out

def compare_baseline(obj,baseline_path,tol=1e-12):
    base=json.load(open(baseline_path,encoding='utf-8'))
    if set(obj['stats'])!=set(base['stats']):raise SystemExit(f'baseline key mismatch: generated={len(obj["stats"])} baseline={len(base["stats"])}')
    fields=['name','starts','win_rate','top2_rate','place_rate','win_return','place_return','place_missing','win_payout_missing','place_payout_missing','confidence']
    for k in base['stats']:
        if obj['stats'][k]['n']!=base['stats'][k]['n']:raise SystemExit(f'n mismatch {k}')
        for typ in ('sire_line','damsire_line','cross_major','stallion'):
            a=obj['stats'][k][typ];b=base['stats'][k][typ]
            if len(a)!=len(b):raise SystemExit(f'len mismatch {k} {typ}')
            for i,(x,y) in enumerate(zip(a,b)):
                for f in fields:
                    xv,yv=x[f],y[f]
                    if isinstance(xv,float):
                        if abs(xv-float(yv))>tol:raise SystemExit(f'value mismatch {k} {typ}[{i}].{f}: {xv} != {yv}')
                    elif xv!=yv:raise SystemExit(f'value mismatch {k} {typ}[{i}].{f}: {xv!r} != {yv!r}')
    print(f'PASS: pedigree baseline exact match ({len(obj["stats"])} conditions)')

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--master',required=True);ap.add_argument('--payout',required=True);ap.add_argument('--sire-map',required=True);ap.add_argument('--damsire-map',required=True);ap.add_argument('--stallion-map',required=True);ap.add_argument('--out',required=True);ap.add_argument('--dataset-id',default='UNPACKAGED');ap.add_argument('--from-date',default=DEFAULT_FROM_DATE);ap.add_argument('--to-date',default='');ap.add_argument('--compare-baseline',default='');a=ap.parse_args()
    m=read_master(a.master);required={'race_id','日付','競馬場','レース名','クラス','条件','馬場','距離','馬場状態','馬番','馬名','馬ID','着順','単勝','父','父父','母父'};miss=required-set(m.columns)
    if miss:raise SystemExit(f'master missing columns: {sorted(miss)}')
    m['_date']=pd.to_datetime(m['日付'],errors='coerce');mask=(m['競馬場'].isin(CENTRAL))&(m['_date']>=pd.Timestamp(a.from_date))
    if a.to_date:mask&=(m['_date']<=pd.Timestamp(a.to_date))
    src=m[mask].copy();obstacle=src['条件'].str.contains('障害',na=False)|src['レース名'].str.contains('障害',na=False);src=src[~obstacle].copy();source_rows=len(src)
    nonstarter=nonstarter_mask(src);accepted=src[~nonstarter].copy();excluded=int(nonstarter.sum());dup=int(accepted.duplicated(['race_id','馬番']).sum())
    if dup:raise SystemExit(f'duplicate accepted starts: {dup}')
    accepted['dist']=pd.to_numeric(accepted['距離'],errors='coerce').astype('Int64')
    if accepted['dist'].isna().any():raise SystemExit(f'distance missing in accepted starts: {int(accepted["dist"].isna().sum())}')
    accepted['surface']=accepted['馬場'].map({'芝':'芝','ダ':'ダート','ダート':'ダート'})
    if accepted['surface'].isna().any():raise SystemExit(f'unknown surface: {accepted.loc[accepted["surface"].isna(),"馬場"].value_counts().to_dict()}')
    allowed={'未勝利','新馬','1勝','2勝','3勝','オープン'};bad=sorted(set(accepted['クラス'])-allowed)
    if bad:raise SystemExit(f'unknown classes: {bad}')
    accepted['going']=np.where(accepted['馬場状態'].eq('良'),'良','道悪')
    sm=load_map(a.sire_map,'父父','大血統');dm=load_map(a.damsire_map,'母父','大血統');tm=load_map(a.stallion_map,'父','表示名')
    us=sorted(set(accepted.loc[accepted['父父']!='','父父'])-set(sm));ud=sorted(set(accepted.loc[accepted['母父']!='','母父'])-set(dm))
    # Future-proof: new pedigree names must not stop the whole data update.
    # Unknown non-empty names fall back to その他系 and are recorded in meta.audit.
    accepted['sire_line']=accepted['父父'].map(lambda x:sm.get(x,'その他系') if x else '不明');accepted['damsire_line']=accepted['母父'].map(lambda x:dm.get(x,'その他系') if x else '不明');accepted['cross_major']=accepted['sire_line']+' × '+accepted['damsire_line'];accepted['stallion']=accepted['父'].map(lambda x:tm.get(x,re.sub(r'\([^)]*\)$','',x).strip()) if x else '不明')
    p=read_csv(a.payout)
    if '組合せ' in p.columns and '組み合わせ' not in p.columns:p=p.rename(columns={'組合せ':'組み合わせ'})
    need={'race_id','券種','組み合わせ','払戻金'}
    if not need.issubset(p.columns):raise SystemExit(f'payout missing columns: {sorted(need-set(p.columns))}')
    p['horse_no']=p['組み合わせ'].map(horse_no);p['amount']=p['払戻金'].map(money)
    if p.loc[p['券種'].isin(['単勝','複勝']),'amount'].isna().any():raise SystemExit('unparseable win/place payout amount')
    wp=p[p['券種']=='単勝'][['race_id','horse_no','amount']].drop_duplicates(['race_id','horse_no']).rename(columns={'amount':'win_payout'});pp=p[p['券種']=='複勝'][['race_id','horse_no','amount']].drop_duplicates(['race_id','horse_no']).rename(columns={'amount':'place_payout'})
    accepted['horse_no']=accepted['馬番'].map(horse_no);accepted=accepted.merge(wp,on=['race_id','horse_no'],how='left').merge(pp,on=['race_id','horse_no'],how='left');accepted['rank']=pd.to_numeric(accepted['着順'],errors='coerce')
    missing_win=int(((accepted['rank']==1)&accepted['win_payout'].isna()).sum());race_ids=set(accepted['race_id'].astype(str));missing_place=sorted(race_ids-set(pp['race_id'].astype(str)))
    if missing_win or missing_place:raise SystemExit(f'payout incomplete: missing winner payout={missing_win}, races missing place payout={len(missing_place)} sample={missing_place[:10]}')
    accepted['win_payout']=accepted['win_payout'].fillna(0.0);accepted['place_payout']=accepted['place_payout'].fillna(0.0)
    accepted['key_specific']=accepted.apply(lambda r:f"{r['競馬場']}|{r['surface']}|{int(r['dist'])}|{r['クラス']}|{r['going']}",axis=1);accepted['key_all']=accepted.apply(lambda r:f"{r['競馬場']}|{r['surface']}|{int(r['dist'])}|{r['クラス']}|全",axis=1);long=pd.concat([accepted.assign(key=accepted['key_specific']),accepted.assign(key=accepted['key_all'])],ignore_index=True)
    counts=long['key'].value_counts().to_dict();sire=build_records(long,'sire_line',10);dam=build_records(long,'damsire_line',10);cross=build_records(long,'cross_major',10);stall=build_records(long,'stallion',5);stats={k:{'n':int(counts[k]),'sire_line':sire.get(k,[]),'damsire_line':dam.get(k,[]),'cross_major':cross.get(k,[]),'stallion':stall.get(k,[])} for k in sorted(counts)}
    now=datetime.now(timezone.utc).isoformat();obj={'meta':{'schema_version':2,'dataset_id':a.dataset_id,'generated_at':now,'source_rows':len(accepted),'class_rule':'血統のみG1/G2/G3等の重賞をオープンへ統合','payout_rule':'100円あたり払戻。欠損はnull、有効件数のみ分母。複勝率は払戻の有無で判定。','audit':{'generated_at':now,'source_rows':source_rows,'accepted_rows':len(accepted),'excluded_rows':excluded,'duplicate_rows':dup,'reasons':{'非出走':excluded},'from':str(accepted['日付'].min()),'to':str(accepted['日付'].max()),'missing_win_payout':0,'missing_place_payout':0,'unmapped_sire_grandsire_count':len(us),'unmapped_sire_grandsire':us,'unmapped_damsire_count':len(ud),'unmapped_damsire':ud},'line_rule':'大系統はサンデーサイレンス系／ミスタープロスペクター系／ノーザンダンサー系／ロベルト系／ナスルーラ系／その他系（判定不能のみ不明）へ正規化。細分系統の元情報は再集計元CSVに保持。','major_line_categories':MAJOR,'top_n':7},'stats':stats}
    if a.compare_baseline:compare_baseline(obj,a.compare_baseline)
    Path(a.out).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps({'conditions':len(stats),'source_rows':source_rows,'accepted_rows':len(accepted),'excluded_rows':excluded,'from':obj['meta']['audit']['from'],'to':obj['meta']['audit']['to']},ensure_ascii=False));return 0
if __name__=='__main__':raise SystemExit(main())
