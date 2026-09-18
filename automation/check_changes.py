"""Refuse any tracked changes outside the data/state transaction."""
import subprocess

ALLOWED = {
    'lapdata.json', 'pedigree_stats.json', 'data-version.json',
    'automation/state/keiba_master.csv.gz', 'automation/state/payout.csv.gz',
    'automation/state/horse_pedigree.csv', 'automation/state/manifest.json',
}
if __name__ == '__main__':
    changed = set(subprocess.check_output(['git', 'diff', '--name-only', 'HEAD', '-z']).decode().split('\0')) - {''}
    untracked = set(subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard', '-z']).decode().split('\0')) - {''}
    if (changed | untracked) - ALLOWED:
        raise SystemExit(f'unexpected changed paths: {sorted((changed | untracked) - ALLOWED)}')
