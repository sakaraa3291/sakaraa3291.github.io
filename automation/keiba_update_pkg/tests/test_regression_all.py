#!/usr/bin/env python3
from __future__ import annotations
import argparse, subprocess, sys, tempfile
from pathlib import Path

def run(cmd): subprocess.run([str(x) for x in cmd],check=True)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--master',required=True)
    ap.add_argument('--lap',required=True)
    ap.add_argument('--payout',required=True)
    ap.add_argument('--pedigree-baseline',required=True)
    a=ap.parse_args(); root=Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as td0:
        td=Path(td0)
        run([sys.executable,root/'tests'/'test_rebuild_cond.py',a.master,a.lap])
        # Grade is curated publication history. Incremental updates preserve it;
        # rebuilding it from raw rows would deliberately discard manual fixes.
        run([sys.executable,root/'tools'/'rebuild_pedigree_stats.py','--master',a.master,'--payout',a.payout,
             '--sire-map',root/'mappings'/'sire_grandsire_major_map.csv','--damsire-map',root/'mappings'/'damsire_major_map.csv','--stallion-map',root/'mappings'/'stallion_display_map.csv',
             '--out',td/'ped.json','--to-date','2026-07-19','--compare-baseline',a.pedigree_baseline])
    print('PASS: lap + grade + pedigree baseline regression')
if __name__=='__main__': raise SystemExit(main())
