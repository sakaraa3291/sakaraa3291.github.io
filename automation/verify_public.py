"""Check deployed hashes with bounded retries for Pages propagation lag."""
import argparse
import hashlib
import json
from pathlib import Path

if __package__:
    from .public_verify import PublicVerifier
else:
    # Also support: python automation/verify_public.py (stdlib only).
    from public_verify import PublicVerifier


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', required=True)
    a = ap.parse_args()
    version = json.loads(Path('data-version.json').read_text())
    expected = dict(version['files'])
    expected['data-version.json'] = hashlib.sha256(Path('data-version.json').read_bytes()).hexdigest()
    verifier = PublicVerifier(a.url)
    for name, sha in expected.items():
        try:
            verifier.verify(name, lambda content: hashlib.sha256(content).hexdigest() == sha,
                            f'public SHA mismatch: {name}')
        except ValueError as exc:
            raise SystemExit(f'{exc}; rerun failed deployment job after checking Pages') from exc
        print(f'PASS: {name}')


if __name__ == '__main__':
    main()
