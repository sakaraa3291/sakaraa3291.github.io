#!/usr/bin/env python3
from __future__ import annotations
import argparse, subprocess, sys, tempfile
from pathlib import Path
import pandas as pd

def read(path):
    with open(path,'rb') as f: head=f.read(2)
    return pd.read_csv(path,dtype=str,low_memory=False,compression='gzip' if head==b'\x1f\x8b' else None,encoding='utf-8-sig').fillna('')

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--base-dir',required=True); ap.add_argument('--expected-master',required=True); a=ap.parse_args()
    root=Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as td:
        out=Path(td)/'rebuilt.csv.gz'
        subprocess.run([sys.executable,str(root/'tools'/'build_master_portable.py'),'--base-dir',a.base_dir,'--out',out],check=True)
        x,y=read(a.expected_master),read(out)
        assert list(x.columns)==list(y.columns), 'master columns differ'
        assert x.shape==y.shape, f'master shape differs {x.shape} != {y.shape}'
        assert x.equals(y), 'master values/order differ'
    print(f'PASS: master exact match rows={len(x)} cols={len(x.columns)}')
if __name__=='__main__': raise SystemExit(main())
