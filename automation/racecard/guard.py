"""Restrict automation writes and fail deployment from a stale checkout."""
import argparse
import subprocess
from pathlib import PurePosixPath

from .core import require


def allowed(path):
    parts = PurePosixPath(path).parts
    return '..' not in parts and not path.startswith('/') and (
        (parts and parts[0] == 'prediction-data' and path.endswith('.json'))
        or path == 'automation/racecard-state/cache.json')


def check_changes():
    commands = [['git', 'diff', '--name-only', 'HEAD', '-z'],
                ['git', 'ls-files', '--others', '--exclude-standard', '-z']]
    paths = set()
    for cmd in commands:
        paths.update(subprocess.check_output(cmd).decode().split('\0'))
    paths.discard('')
    require(all(allowed(p) for p in paths), f'unexpected changed paths: {sorted(p for p in paths if not allowed(p))}')
    return paths


def assert_current(local, remote):
    require(local == remote, f'stale checkout: {local} != main {remote}; abort Pages deployment')


def check_head():
    local = subprocess.check_output(['git', 'rev-parse', 'HEAD']).decode().strip()
    remote = subprocess.check_output(['git', 'ls-remote', '--exit-code', 'origin', 'refs/heads/main']).decode().split()[0]
    assert_current(local, remote)
    return local


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=['changes', 'head'])
    mode = ap.parse_args().mode
    print(check_changes() if mode == 'changes' else check_head())
