"""Check deployed bytes once; a mismatch fails the run without rolling back Git."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen, Request

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', required=True)
    a = ap.parse_args()
    version = json.loads(Path('data-version.json').read_text())
    expected = dict(version['files'])
    expected['data-version.json'] = hashlib.sha256(Path('data-version.json').read_bytes()).hexdigest()
    for name, sha in expected.items():
        req = Request(a.url.rstrip('/') + '/' + name + '?sha=' + sha, headers={'Cache-Control': 'no-cache'})
        with urlopen(req, timeout=30) as response:
            actual = hashlib.sha256(response.read()).hexdigest()
        if actual != sha:
            raise SystemExit(f'public SHA mismatch: {name}; rerun failed deployment job after checking Pages')
        print(f'PASS: {name}')
