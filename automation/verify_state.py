#!/usr/bin/env python3
"""Offline aggregate regression against the current, hash-validated public baseline."""
import argparse
import json
import sys
from pathlib import Path
from run_update import check_baseline, run_tool, read_json, write_json, PACKAGE
sys.path.insert(0, str(PACKAGE / 'tools'))
from rebuild_lapdata_cond import read_master, build_cond


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--repo',type=Path,default=Path(__file__).resolve().parents[1])
    ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args();repo=a.repo.resolve();state=repo/'automation/state'
    a.out.mkdir(parents=True,exist_ok=True)
    manifest=check_baseline(repo,state)
    cond,singletons,_=build_cond(read_master(state/'keiba_master.csv.gz'),2)
    baseline=read_json(repo/'lapdata.json')
    if cond!=baseline['cond']:
        raise SystemExit('rebuilt conditions differ from current production')
    run_tool('rebuild_pedigree_stats.py','--master',state/'keiba_master.csv.gz','--payout',state/'payout.csv.gz',
             '--sire-map',PACKAGE/'mappings/sire_grandsire_major_map.csv',
             '--damsire-map',PACKAGE/'mappings/damsire_major_map.csv',
             '--stallion-map',PACKAGE/'mappings/stallion_display_map.csv',
             '--out',a.out/'pedigree_stats.json','--to-date',manifest['through'],
             '--dataset-id',baseline['meta']['dataset_id'],'--compare-baseline',repo/'pedigree_stats.json')
    # Exercise grade updater on an empty next-day interval, preserving all manual records and notes.
    from datetime import date,timedelta
    next_day=(date.fromisoformat(manifest['through'])+timedelta(days=1)).isoformat()
    run_tool('update_grade_records_incremental.py','--master',state/'keiba_master.csv.gz',
             '--baseline',repo/'lapdata.json','--cond',repo/'lapdata.json','--out',a.out/'grade-check.json',
             '--to-date',next_day,'--dataset-id',baseline['meta']['dataset_id'])
    grade=read_json(a.out/'grade-check.json')
    if grade['grade']!=baseline['grade']:
        raise SystemExit('published grade history changed')
    for key,value in baseline['meta'].get('audit',{}).items():
        if key!='incremental_grade_update' and grade['meta']['audit'].get(key)!=value:
            raise SystemExit(f'manual audit changed: {key}')
    report={'status':'PASS','through':manifest['through'],'lap_conditions':len(cond),
            'lap_races':sum(r['n'] for r in cond.values()),'singleton_conditions':len(singletons),
            'pedigree_conditions':len(read_json(repo/'pedigree_stats.json')['stats']),
            'pedigree_source_rows':read_json(repo/'pedigree_stats.json')['meta']['source_rows'],
            'grade_keys_preserved':len(baseline['grade'])}
    write_json(a.out/'verification.json',report)
    print(json.dumps(report))

if __name__=='__main__':
    main()
