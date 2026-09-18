#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, shutil
from datetime import datetime, timezone
from pathlib import Path

DATA=('lapdata.json','courses.json','elevation.json','pedigree_stats.json')
def sha_bytes(b): return hashlib.sha256(b).hexdigest()
def canonical(o): return json.dumps(o,sort_keys=True,ensure_ascii=False,allow_nan=False).encode('utf-8')

def main():
    ap=argparse.ArgumentParser(description='Create fail-closed data-only release payload for current app shell.')
    ap.add_argument('--app-dir',required=True,help='Current app checkout containing courses/elevation/data-version and existing data')
    ap.add_argument('--lap',required=True)
    ap.add_argument('--pedigree',required=True)
    ap.add_argument('--out-dir',required=True)
    a=ap.parse_args(); A=Path(a.app_dir); O=Path(a.out_dir); O.mkdir(parents=True,exist_ok=True)
    for f in ('courses.json','elevation.json','data-version.json'):
        if not (A/f).exists(): raise SystemExit(f'missing current app file: {A/f}')
    payload={
      'lapdata.json':json.load(open(a.lap,encoding='utf-8')),
      'courses.json':json.load(open(A/'courses.json',encoding='utf-8')),
      'elevation.json':json.load(open(A/'elevation.json',encoding='utf-8')),
      'pedigree_stats.json':json.load(open(a.pedigree,encoding='utf-8')),
    }
    for obj in payload.values():
        obj.setdefault('meta',{}).pop('dataset_id',None); obj['meta']['schema_version']=2
    ident=sha_bytes(canonical(payload))[:24]
    for obj in payload.values(): obj['meta']['dataset_id']=ident
    # Deterministic formatting compatible with current app tooling.
    for f in ('lapdata.json','courses.json','elevation.json'):
        (O/f).write_text(json.dumps(payload[f],ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    (O/'pedigree_stats.json').write_text(json.dumps(payload['pedigree_stats.json'],ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    current=json.load(open(A/'data-version.json',encoding='utf-8'))
    version={
      'schema_version':2,
      'app_version':current.get('app_version','3.8.0'),
      'dataset_id':ident,
      'updated_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),
      'files':{f:sha_bytes((O/f).read_bytes()) for f in DATA},
    }
    (O/'data-version.json').write_text(json.dumps(version,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for f in DATA:
        obj=json.load(open(O/f,encoding='utf-8'))
        assert obj['meta']['dataset_id']==ident
        assert sha_bytes((O/f).read_bytes())==version['files'][f]
    manifest={'type':'data-only','app_version':version['app_version'],'dataset_id':ident,'files':version['files'],'shell_changes_required':False}
    (O/'release_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False,indent=2)); return 0
if __name__=='__main__': raise SystemExit(main())
