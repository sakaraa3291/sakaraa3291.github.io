#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json
from datetime import datetime, timezone
from pathlib import Path

HEX64=lambda s:isinstance(s,str) and len(s)==64 and all(c in '0123456789abcdef' for c in s)
def sha(p:Path)->str:return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    ap=argparse.ArgumentParser(description='Package a data-only release while keeping static course/elevation JSON byte-identical.')
    ap.add_argument('--lap',required=True)
    ap.add_argument('--pedigree',required=True)
    ap.add_argument('--out-dir',required=True)
    ap.add_argument('--dataset-id',required=True)
    ap.add_argument('--app-version',default='3.8.0')
    ap.add_argument('--courses-sha',required=True)
    ap.add_argument('--elevation-sha',required=True)
    a=ap.parse_args()
    if not HEX64(a.courses_sha) or not HEX64(a.elevation_sha): raise SystemExit('static SHA256 must be lowercase 64-hex')
    O=Path(a.out_dir); O.mkdir(parents=True,exist_ok=True)
    lap=json.load(open(a.lap,encoding='utf-8')); ped=json.load(open(a.pedigree,encoding='utf-8'))
    for x in (lap,ped):
        x.setdefault('meta',{})['schema_version']=2
        x['meta']['dataset_id']=a.dataset_id
    # fail closed on core invariants before writing
    assert lap['meta']['races']==sum(int(r['n']) for r in lap['cond'].values())
    assert lap['meta']['to']
    assert isinstance(lap.get('grade'),dict) and len(lap['grade'])>0
    assert isinstance(ped.get('stats'),dict) and int(ped['meta']['source_rows'])>=0
    for name,obj in [('lapdata.json',lap),('pedigree_stats.json',ped)]:
        (O/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    files={
        'lapdata.json':sha(O/'lapdata.json'),
        'courses.json':a.courses_sha,
        'elevation.json':a.elevation_sha,
        'pedigree_stats.json':sha(O/'pedigree_stats.json'),
    }
    version={
        'schema_version':2,'app_version':a.app_version,'dataset_id':a.dataset_id,
        'updated_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),'files':files,
    }
    (O/'data-version.json').write_text(json.dumps(version,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    manifest={
        'type':'data-only-incremental','app_version':a.app_version,'dataset_id':a.dataset_id,
        'changed_files':['lapdata.json','pedigree_stats.json','data-version.json'],
        'unchanged_files':['courses.json','elevation.json'],'files':files,'shell_changes_required':False,
    }
    (O/'release_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False,indent=2))
if __name__=='__main__': raise SystemExit(main())
