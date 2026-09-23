"""Exclude automation state and source tools from the Pages artifact."""
import argparse
import shutil
import subprocess
from pathlib import Path


def public_path(path):
    p = Path(path)
    return ((p.parts[0] == 'prediction-data' and p.suffix == '.json') or
            (len(p.parts) == 1 or (len(p.parts) == 2 and p.parts[0].startswith('v') and p.parts[0].endswith('-test')))
            and p.suffix in {'.html', '.js', '.css', '.json', '.png', '.ico', '.svg', '.webmanifest', '.txt'}
            or path in {'CNAME', '.nojekyll'})

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    if a.out.exists():
        raise SystemExit('site output must not already exist')
    for path in subprocess.check_output(['git', 'ls-files', '-z']).decode().split('\0'):
        if path and public_path(path):
            target = a.out / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
