"""Reusable observations must not turn no-op runs into Git changes."""
import copy
import sys
from datetime import date
from types import SimpleNamespace

import pytest

from automation.racecard import run

DAY = date(2026, 9, 23)
STAMP = '2026-09-23T12:00:00+09:00'


def state(horses=None):
    return {'schema_version': 1, 'horses': horses or {}}


@pytest.mark.parametrize('value', [None, {}, [], False, {'schema_version': 2, 'horses': {}},
    {'schema_version': True, 'horses': {}}, {'schema_version': 1},
    {'schema_version': 1, 'horses': []}])
@pytest.mark.parametrize('location', ['reusable.json', 'automation/racecard-state/cache.json'])
def test_cache_rejects_invalid_schema(tmp_path, value, location):
    path = tmp_path / location
    run.write(path, value)
    with pytest.raises(ValueError, match='cache'):
        run.read_cache(path)


def test_missing_empty_and_malformed_cache(tmp_path):
    path = tmp_path / 'cache.json'
    assert run.read_cache(path) == state()
    run.write(path, state())
    assert run.read_cache(path) == state()
    path.write_text('{')
    with pytest.raises(ValueError):
        run.read_cache(path)


def test_build_merges_without_mutating_inputs(tmp_path, monkeypatch):
    committed = state({'shared': {'value': ['committed']}, 'committed': {}})
    reusable = state({'shared': {'value': ['restored']}, 'reusable': {}})
    before = copy.deepcopy(reusable)
    path = tmp_path / 'automation/racecard-state/cache.json'
    run.write(path, committed)
    def collect(fetch, target, cache, stamp):
        assert cache['shared'] == committed['horses']['shared']
        assert set(cache) == {'shared', 'committed', 'reusable'}
        cache['reusable']['observed'] = True
        return [], {'status': 'complete'}
    monkeypatch.setattr(run, 'collect_jra', collect)
    monkeypatch.setattr(run, 'collect_nar', lambda *args: ([], {'status': 'complete'}))
    monkeypatch.setattr(run, 'supplement_history', lambda *args: None)
    _, _, merged = run.build(tmp_path, DAY, None, STAMP, reusable)
    assert merged['horses']['reusable'] == {'observed': True}
    assert reusable == before
    assert run.read_cache(path) == committed
    with pytest.raises(ValueError, match='cache'):
        run.build(tmp_path, DAY, None, STAMP, {})


@pytest.mark.parametrize('apply', [False, True])
@pytest.mark.parametrize('changed', [False, True])
@pytest.mark.parametrize('use_reusable', [False, True])
def test_main_cache_persistence(tmp_path, monkeypatch, apply, changed, use_reusable):
    root = tmp_path / 'repo'
    committed = root / 'automation/racecard-state/cache.json'
    reusable = tmp_path / 'runner-temp/cache.json'
    diagnostics = tmp_path / 'diagnostics'
    output = tmp_path / 'output'
    old, fresh = state({'old': {}}), state({'old': {}, 'new': {}})
    run.write(committed, old)
    sources = {org: {'status': 'complete'} for org in ('JRA', 'NAR')}
    if not changed:
        run.publish(run.prepare(root, DAY, [], sources, STAMP), root / 'prediction-data')
    before = run.tree_hash(root / 'prediction-data')
    def build(root, target, fetch, stamp, restored):
        assert restored == (state() if use_reusable else None)
        return [], sources, fresh
    monkeypatch.setattr(run, 'ROOT', root)
    monkeypatch.setattr(run, 'build', build)
    monkeypatch.setattr(run, 'Fetcher', lambda path: SimpleNamespace(count=0))
    monkeypatch.setenv('GITHUB_OUTPUT', str(output))
    args = ['racecard', '--target-date', str(DAY), '--diagnostics', str(diagnostics)]
    if apply:
        args += ['--apply']
    if use_reusable:
        args += ['--cache-file', str(reusable)]
    monkeypatch.setattr(sys, 'argv', args)
    run.main()
    published = changed and apply
    assert run.read_cache(committed) == (fresh if published else old)
    assert reusable.exists() == use_reusable
    if use_reusable:
        assert run.read_cache(reusable) == fresh
    if not published:
        assert run.tree_hash(root / 'prediction-data') == before
    assert run.read(diagnostics / 'report.json')['status'] == (
        'UPDATED' if published else 'VALIDATED' if changed else 'NO_CHANGES')
    assert output.read_text() == f'changed={str(published).lower()}\ntarget_date={DAY}\n'


@pytest.mark.parametrize('failure', ['build', 'prepare'])
def test_failed_run_does_not_persist_cache(tmp_path, monkeypatch, failure):
    reusable = tmp_path / 'cache.json'
    run.write(reusable, state({'old': {}}))
    before = reusable.read_bytes()
    monkeypatch.setattr(run, 'ROOT', tmp_path)
    monkeypatch.setattr(run, 'Fetcher', lambda path: SimpleNamespace(count=0))
    monkeypatch.setattr(run, 'build', lambda *args: ([], {}, state({'new': {}})))
    def fail(*args):
        raise ValueError('incomplete candidate')
    monkeypatch.setattr(run, failure, fail)
    monkeypatch.setattr(sys, 'argv', ['racecard', '--target-date', str(DAY),
        '--cache-file', str(reusable), '--diagnostics', str(tmp_path / 'diagnostics'), '--apply'])
    with pytest.raises(ValueError, match='incomplete'):
        run.main()
    assert reusable.read_bytes() == before
    assert not (tmp_path / 'automation/racecard-state/cache.json').exists()
