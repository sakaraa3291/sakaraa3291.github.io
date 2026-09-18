#!/usr/bin/env python3
"""Offline bootstrap: reuse the 512 cached races, never make network requests."""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
import pandas as pd
from run_update import digest, write_json, STATE_FILES


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bootstrap', type=Path, required=True)
    ap.add_argument('--release-record', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    b, out = a.bootstrap.resolve(), a.out.resolve()
    if out.exists() and any(out.iterdir()):
        raise SystemExit('output must be empty; existing persistent state is never overwritten')
    out.mkdir(parents=True, exist_ok=True)
    tools = Path(__file__).parent / 'keiba_update_pkg/tools'
    def run(name, *args):
        subprocess.run([sys.executable, str(tools / name), *map(str, args)], check=True)
    def read(path):
        return pd.read_csv(path, dtype=str, low_memory=False).fillna('')
    base = read(b / 'keiba_master_baseline.csv.gz')
    original_delta = b / 'delta_512'
    delta = out / 'bootstrap_delta'
    shutil.copytree(original_delta, delta)
    corrections = read(Path(__file__).parent / 'keiba_update_pkg/config/bootstrap_class_overrides.csv')
    meta = read(delta / 'race_meta_delta.csv')
    if len(meta) != 512 or meta.race_id.nunique() != 512 or (meta.date.min(), meta.date.max()) != ('2026-07-25', '2026-09-13'):
        raise SystemExit('unexpected bootstrap cache coverage')
    lookup = dict(zip(corrections.race_id, corrections.corrected_class))
    mask = meta.race_id.isin(lookup)
    if not meta.loc[mask, 'クラス'].eq('その他').all():
        raise SystemExit('class override precondition changed')
    meta.loc[mask, 'クラス'] = meta.loc[mask, 'race_id'].map(lookup)
    meta.to_csv(delta / 'race_meta_delta.csv', index=False, encoding='utf-8-sig')
    target = out / 'bootstrap_target.csv'
    meta[['race_id','date']].to_csv(target, index=False)
    run('validate_delta_complete.py', '--target', target, '--delta-dir', delta,
        '--base-pedigree', b / 'horse_pedigree_baseline.csv', '--strict', '--allow-nar')
    run('update_master_incremental.py', '--master', b / 'keiba_master_baseline.csv.gz',
        '--delta-dir', delta, '--existing-pedigree', b / 'horse_pedigree_baseline.csv',
        '--out-master', out / STATE_FILES[0], '--out-pedigree', out / STATE_FILES[2],
        '--allow-replace-race-ids', target)
    run('update_payout_incremental.py', '--payout', b / 'payout_baseline.csv.gz',
        '--delta-dir', delta, '--out', out / STATE_FILES[1], '--allow-replace-race-ids', target)
    merged = read(out / STATE_FILES[0])
    if not merged.iloc[:len(base)][['race_id','馬番']].reset_index(drop=True).equals(base[['race_id','馬番']]):
        raise SystemExit('baseline race/horse order changed')
    immutable_cutoff = '2026-07-19'
    old_immutable = base[base['日付'] <= immutable_cutoff].reset_index(drop=True)
    new_immutable = merged[merged['日付'] <= immutable_cutoff].reset_index(drop=True)
    if not new_immutable.equals(old_immutable):
        raise SystemExit(f'bootstrap changed immutable master history through {immutable_cutoff}')
    base_payout = read(b / 'payout_baseline.csv.gz')
    merged_payout = read(out / STATE_FILES[1])
    immutable_ids = set(base.loc[base['日付'] <= immutable_cutoff, 'race_id'])
    if not merged_payout[merged_payout.race_id.isin(immutable_ids)].reset_index(drop=True).equals(
            base_payout[base_payout.race_id.isin(immutable_ids)].reset_index(drop=True)):
        raise SystemExit(f'bootstrap changed immutable payout history through {immutable_cutoff}')
    untouched_ids = set(base.race_id) - set(meta.race_id)
    if not merged[merged.race_id.isin(untouched_ids)].reset_index(drop=True).equals(
            base[base.race_id.isin(untouched_ids)].reset_index(drop=True)):
        raise SystemExit('bootstrap changed or reordered rows outside cached race IDs')
    if not set(meta.race_id) <= set(merged.race_id) or merged['日付'].max() != '2026-09-13':
        raise SystemExit('bootstrap coverage/cutoff invalid')
    release = json.loads(a.release_record.read_text())
    write_json(out / 'manifest.json', {
        'schema_version': 1, 'through': '2026-09-13',
        'files': {name: digest(out / name) for name in STATE_FILES},
        'production': {name: release['public_file_sha256'][name] for name in ('lapdata.json','pedigree_stats.json')},
    })
    write_json(out / 'bootstrap_audit.json', {
        'baseline_cutoff': base['日付'].max(), 'cached_races': 512,
        'cached_jra_races': int(meta.race_id.str.slice(4,6).isin([f'{n:02}' for n in range(1,11)]).sum()),
        'cached_nar_races': int((~meta.race_id.str.slice(4,6).isin([f'{n:02}' for n in range(1,11)])).sum()),
        'overlap_races': len(set(base.race_id) & set(meta.race_id)),
        'added_races': len(set(meta.race_id) - set(base.race_id)),
        'baseline_rows': len(base), 'merged_rows': len(merged), 'merged_races': merged.race_id.nunique(),
        'baseline_race_horse_order_preserved': True,
        'immutable_through': immutable_cutoff,
        'immutable_master_cells_and_order_preserved': True,
        'immutable_payout_cells_and_order_preserved': True,
        'untouched_master_cells_and_order_preserved': True,
        'source_sha256': {p.name: digest(p) for p in sorted(b.iterdir()) if p.is_file()},
        'delta_sha256': {p.name: digest(p) for p in sorted(original_delta.glob('*.csv'))},
        'class_corrections': {'races': len(corrections), 'mapping_sha256': digest(Path(__file__).parent / 'keiba_update_pkg/config/bootstrap_class_overrides.csv'), 'source': 'existing state_20260913, checked against production aggregates'},
        'release_record': release,
    })
    target.unlink()
    shutil.rmtree(delta)
    print('PASS: persistent state initialized through 2026-09-13 without fetching races')

if __name__ == '__main__':
    main()
