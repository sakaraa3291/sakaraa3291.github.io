#!/usr/bin/env python3
from __future__ import annotations
import argparse, subprocess, sys, json, gzip
from pathlib import Path


def run(cmd):
    print('+',' '.join(map(str,cmd)),flush=True)
    subprocess.run([str(x) for x in cmd],check=True)

def gzip_csv_rows(path: Path) -> int:
    with gzip.open(path, 'rt', encoding='utf-8-sig', newline='') as f:
        return max(sum(1 for _ in f) - 1, 0)


def main():
    ap=argparse.ArgumentParser(description='Fail-closed postprocess: validate -> merge -> master -> lap/grade -> pedigree.')
    ap.add_argument('--base-dir',required=True,help='Directory containing keiba_2021..2026.csv and historical auxiliary CSVs')
    ap.add_argument('--delta-dir',required=True,help='FULL_READY delta output directory')
    ap.add_argument('--baseline-lap',required=True,help='Current production lapdata.json')
    ap.add_argument('--baseline-pedigree',required=True,help='Current production pedigree_stats.json')
    ap.add_argument('--out-dir',required=True)
    ap.add_argument('--dataset-id',default='UNPACKAGED')
    ap.add_argument('--to-date',required=True,help='Inclusive publication cutoff YYYY-MM-DD')
    a=ap.parse_args()
    root=Path(__file__).resolve().parents[1]
    B=Path(a.base_dir).resolve(); D=Path(a.delta_dir).resolve(); O=Path(a.out_dir).resolve(); O.mkdir(parents=True,exist_ok=True)
    target=root/'targets'/'app_target_20260725_20260913_512.csv'
    if not (D.parent/'FULL_READY').exists() and not (D/'FULL_READY').exists():
        # Full runner writes FULL_READY in work root, while callers may pass work/full.
        print('NOTE: FULL_READY marker not adjacent; completeness validator is authoritative.',flush=True)
    run([sys.executable,root/'tools'/'validate_delta_complete.py','--target',target,'--delta-dir',D,'--base-pedigree',B/'horse_pedigree.csv'])
    merged=O/'merged_sources'; merged.mkdir(exist_ok=True)
    run([sys.executable,root/'tools'/'merge_delta_sources.py','--base-dir',B,'--delta-dir',D,'--out-dir',merged])
    master=O/'keiba_master.csv.gz'
    run([sys.executable,root/'tools'/'build_master_portable.py','--base-dir',B,'--merged-dir',merged,'--out',master])
    lap_cond=O/'lapdata_cond.json'
    run([sys.executable,root/'tools'/'rebuild_lapdata_cond.py','--master',master,'--baseline',a.baseline_lap,'--out',lap_cond,'--dataset-id',a.dataset_id])
    lap_final=O/'lapdata.json'
    run([sys.executable,root/'tools'/'update_grade_records_incremental.py',
         '--master',master,'--baseline',a.baseline_lap,'--cond',lap_cond,'--out',lap_final,
         '--to-date',a.to_date,'--dataset-id',a.dataset_id])
    payout=merged/'払戻データ_全券種.csv'
    pedigree=O/'pedigree_stats.json'
    run([sys.executable,root/'tools'/'rebuild_pedigree_stats.py',
         '--master',master,'--payout',payout,
         '--sire-map',root/'mappings'/'sire_grandsire_major_map.csv',
         '--damsire-map',root/'mappings'/'damsire_major_map.csv',
         '--stallion-map',root/'mappings'/'stallion_display_map.csv',
         '--out',pedigree,'--dataset-id',a.dataset_id])
    l=json.load(open(lap_final,encoding='utf-8')); p=json.load(open(pedigree,encoding='utf-8'))
    report={
        'status':'POSTPROCESS_READY',
        'master_rows':gzip_csv_rows(master),
        'lap_conditions':len(l.get('cond',{})),
        'grade_records':len(l.get('grade',{})),
        'lap_from':l.get('meta',{}).get('from'),
        'lap_to':l.get('meta',{}).get('to'),
        'lap_races':l.get('meta',{}).get('races'),
        'pedigree_conditions':len(p.get('stats',{})),
        'pedigree_source_rows':p.get('meta',{}).get('source_rows'),
        'pedigree_to':p.get('meta',{}).get('audit',{}).get('to'),
    }
    (O/'postprocess_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (O/'POSTPROCESS_READY').write_text('validated merge/master/lap/grade/pedigree complete\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0
if __name__=='__main__': raise SystemExit(main())
