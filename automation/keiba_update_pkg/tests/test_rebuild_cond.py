#!/usr/bin/env python3
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from rebuild_lapdata_cond import read_master,build_cond

def main():
    if len(sys.argv) != 3:
        print('usage: test_rebuild_cond.py MASTER BASELINE_LAP', file=sys.stderr)
        return 2
    master=sys.argv[1]
    baseline=sys.argv[2]
    m=read_master(master)
    m=m[m['日付']<='2026-07-19'].copy()
    cond,singletons,_=build_cond(m,2)
    base=json.load(open(baseline,encoding='utf-8'))
    assert cond==base['cond'], f'condition mismatch generated={len(cond)} baseline={len(base["cond"])}'
    assert len(singletons)==63, len(singletons)
    assert sum(x['n'] for x in cond.values())==17759
    assert len(cond)==934
    print('PASS: 934 conditions exact match; 17,759 races; 63 singleton conditions explain legacy difference')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
