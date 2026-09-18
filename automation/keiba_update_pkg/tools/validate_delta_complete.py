#!/usr/bin/env python3
from pathlib import Path
import argparse, pandas as pd

def rd(path):
    p=Path(path)
    if not p.exists(): return pd.DataFrame()
    try: return pd.read_csv(p,dtype=str,encoding='utf-8-sig',low_memory=False).fillna('')
    except pd.errors.EmptyDataError: return pd.DataFrame()

def ids(path,col='race_id'):
    d=rd(path)
    return set(d[col].astype(str)) if not d.empty and col in d else set()

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--target',required=True); ap.add_argument('--delta-dir',required=True); ap.add_argument('--base-pedigree',default=''); ap.add_argument('--strict',action='store_true'); ap.add_argument('--allow-nar',action='store_true',help='Offline legacy bootstrap only'); a=ap.parse_args()
    t=pd.read_csv(a.target,dtype=str,encoding='utf-8-sig',low_memory=False).fillna('')
    want_all=set(t.race_id.astype(str)); D=Path(a.delta_dir)
    # Dynamic targets may contain only race_id/date. Determine jump races from fetched metadata,
    # never from race-name text (e.g. 新潟JS does not contain the word 障害).
    meta=rd(D/'race_meta_delta.csv')
    if not meta.empty and 'surface' in meta.columns:
        obstacle=set(meta.loc[meta['race_id'].astype(str).isin(want_all) & meta['surface'].astype(str).eq('障'),'race_id'].astype(str))
    else:
        # Backward compatibility for old/static targets used by contract tests.
        obstacle=set(t.loc[t.get('レース名',pd.Series('',index=t.index)).astype(str).str.contains('障害',na=False),'race_id'].astype(str))
    want_lap=want_all-obstacle
    checks={
      'meta':(ids(D/'race_meta_delta.csv'),want_all), 'laps':(ids(D/'race_laps_delta.csv'),want_lap),
      'details':(ids(D/'horse_details_delta.csv'),want_all), 'corners':(ids(D/'race_corners_delta.csv'),want_all),
      'payout':(ids(D/'payout_delta.csv'),want_all),
    }
    bad=False; print(f'target: {len(want_all)} races (flat lap-required {len(want_lap)}, obstacle lap-exempt {len(obstacle)})')
    for name,(got,want) in checks.items():
        miss=sorted(want-got); print(f'{name}: {len(got & want)}/{len(want)} required races')
        if miss: bad=True; print('  missing sample:', ','.join(miss[:10]))
    for fn,label in [('errors.csv','race_errors'),('pedigree_errors.csv','pedigree_errors')]:
        d=rd(D/fn)
        if len(d): bad=True; print(f'{label}: {len(d)} present')
    c=rd(D/'race_corners_delta.csv')
    target_horses=set(c.loc[c.get('race_id',pd.Series('',index=c.index)).astype(str).isin(want_all),'馬ID'].astype(str)) if '馬ID' in c else set()
    target_horses.discard('')
    delta_ped=ids(D/'horse_pedigree_delta.csv','馬ID')
    base_ped=ids(a.base_pedigree,'馬ID') if a.base_pedigree else set()
    covered=target_horses & (base_ped|delta_ped); missing_horses=sorted(target_horses-(base_ped|delta_ped))
    if a.base_pedigree:
        print(f'pedigree horse coverage: {len(covered)}/{len(target_horses)}')
        if missing_horses:
            bad=True; print('  missing horse pedigree sample:', ','.join(missing_horses[:10]))
    else:
        print(f'pedigree horse coverage: base not supplied; delta has {len(delta_ped)} rows')
    if bad: raise SystemExit(2)
    if a.strict:
        from strict_delta import validate
        validate(t,D,a.base_pedigree,allow_nar=a.allow_nar)
    print('PASS: target delta complete')
if __name__=='__main__': main()
