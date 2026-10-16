"""Publication verification tests: no network or real sleeping."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

import pytest

from automation import public_verify, verify_public as hashes
from automation.racecard import verify_public as racecard


@pytest.fixture
def network(monkeypatch):
    class Network:
        now = 0

        def __init__(self):
            self.responses = []
            self.calls = []
            self.sleeps = []

        def open(self, request, timeout):
            self.calls.append((request, timeout))
            result = self.responses.pop(0)
            if isinstance(result, Exception):
                raise result
            return io.BytesIO(result)

        def sleep(self, seconds):
            self.sleeps.append(seconds)
            self.now += seconds

    net = Network()
    monkeypatch.setattr(public_verify, 'urlopen', net.open)
    monkeypatch.setattr(public_verify.time, 'monotonic', lambda: net.now)
    monkeypatch.setattr(public_verify.time, 'sleep', net.sleep)
    return net


def verify(verifier, path='a.json'):
    return verifier.verify(path, lambda data: data == b'correct', f'public bytes mismatch: {path}')


def test_immediate_match(network):
    network.responses = [b'correct']
    assert verify(public_verify.PublicVerifier('https://example.test')) == b'correct'
    assert len(network.calls) == 1
    assert network.sleeps == []


def test_stale_then_correct_only_retries_failing_path(network, capsys):
    network.responses = [b'correct', b'stale', b'correct']
    verifier = public_verify.PublicVerifier('https://example.test/site/')
    verify(verifier, 'first.json')
    verify(verifier, 'second.json')
    urls = [request.full_url for request, _ in network.calls]
    assert [urlsplit(url).path for url in urls] == ['/site/first.json', '/site/second.json', '/site/second.json']
    assert len(set(urlsplit(url).query for url in urls)) == 3
    assert network.sleeps == [5]
    assert 'RETRY: public bytes mismatch: second.json' in capsys.readouterr().out


def test_permanent_mismatch_exhausts_global_budget(network):
    # First path consumes 115 seconds; the second has only 5 seconds left.
    network.responses = [b'stale'] * 23 + [b'correct', b'stale']
    verifier = public_verify.PublicVerifier('https://example.test')
    verify(verifier, 'first.json')
    with pytest.raises(ValueError, match=r'public bytes mismatch: second.json.*120s total'):
        verify(verifier, 'second.json')
    assert sum(network.sleeps) == 120
    assert len(network.calls) == 25
    assert network.calls[-1][1] == 5


@pytest.mark.parametrize('error', [
    HTTPError('https://example.test', code, 'test', {}, None)
    for code in (404, 408, 429, 500, 502, 503, 504)
] + [URLError('connection failed'), TimeoutError(), ConnectionResetError()])
def test_transient_http_and_network_errors_retry(network, error):
    network.responses = [error, b'correct']
    assert verify(public_verify.PublicVerifier('https://example.test')) == b'correct'
    assert network.sleeps == [5]


def test_nontransient_http_fails_immediately(network):
    network.responses = [HTTPError('https://example.test', 403, 'Forbidden', {}, None)]
    with pytest.raises(HTTPError):
        verify(public_verify.PublicVerifier('https://example.test'))
    assert network.sleeps == []


def test_request_time_counts_toward_budget(network, monkeypatch):
    def slow(request, timeout):
        network.now += timeout
        raise TimeoutError()
    monkeypatch.setattr(public_verify, 'urlopen', slow)
    with pytest.raises(ValueError, match='budget exhausted'):
        verify(public_verify.PublicVerifier('https://example.test'))
    assert network.now == 120


def test_hash_entry_point_checks_manifest_and_bytes(network, monkeypatch, tmp_path):
    content = b'{"value":1}\n'
    manifest = json.dumps({'files': {'data.json': hashlib.sha256(content).hexdigest()}}).encode()
    (tmp_path / 'data-version.json').write_bytes(manifest)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, 'argv', ['verify_public', '--url', 'https://example.test'])
    # Equivalent JSON is insufficient: exact bytes/hash must match.
    network.responses = [b'{ "value": 1 }', content, b'{}', manifest]
    hashes.main()
    assert len(network.calls) == 4
    assert network.sleeps == [5, 5]


def test_hash_entry_point_permanent_mismatch_fails(network, monkeypatch, tmp_path):
    (tmp_path / 'data-version.json').write_text(json.dumps({'files': {'data.json': 'wrong'}}))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, 'argv', ['verify_public', '--url', 'https://example.test'])
    network.responses = [b'stale'] * 24
    with pytest.raises(SystemExit, match='public SHA mismatch: data.json.*budget exhausted'):
        hashes.main()
    assert network.now == 120


def test_racecard_entry_point_retries_and_preserves_target(network, monkeypatch, tmp_path, capsys):
    day = '2026-10-17'
    index = json.dumps({'races': []}).encode()
    latest = b'{"target_date":"2026-10-17"}\n'
    directory = tmp_path / 'prediction-data'
    (directory / day).mkdir(parents=True)
    (directory / 'latest.json').write_bytes(latest)
    (directory / day / 'index.json').write_bytes(index)
    monkeypatch.setattr(racecard, 'ROOT', tmp_path)
    monkeypatch.setattr(sys, 'argv', ['verify_public', '--url', 'https://example.test', '--target-date', day])
    network.responses = [latest.rstrip(), latest, index]
    racecard.main()
    assert network.sleeps == [5]
    report = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert report == {'status': 'verified', 'target_date': day, 'public_files_verified': 2}
    assert urlsplit(network.calls[-1][0].full_url).path == f'/prediction-data/{day}/index.json'


def test_standalone_script_import_without_pythonpath(tmp_path):
    script = Path(hashes.__file__).resolve()
    result = subprocess.run([sys.executable, str(script), '--help'], cwd=tmp_path,
                            env={**os.environ, 'PYTHONPATH': ''}, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert '--url' in result.stdout


@pytest.mark.parametrize('source_changed', [False, True])
def test_racecard_keeps_detail_validation_and_source_reconciliation(
        network, monkeypatch, tmp_path, capsys, source_changed):
    day = '2026-10-17'
    path = f'prediction-data/{day}/races/race.json'
    published = dict(race_id='race', target_date=day, venue='Tokyo', race_number=1,
                     start_time=day + 'T12:00:00+09:00', distance_m=1600, race_status='scheduled',
                     horses=[], organization='JRA', source_url='https://source.test/race', source_race_id='1')
    index = {'races': [{'url': path, 'organization': 'JRA'}]}
    payloads = [json.dumps({}).encode(), json.dumps(index).encode(), json.dumps(published).encode()]
    for name, content in zip(['prediction-data/latest.json', f'prediction-data/{day}/index.json', path], payloads):
        file = tmp_path / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(content)
    monkeypatch.setattr(racecard, 'ROOT', tmp_path)
    monkeypatch.setattr(sys, 'argv', ['verify_public', '--url', 'https://example.test', '--target-date', day])
    monkeypatch.setattr(racecard.tempfile, 'mkdtemp', lambda **kwargs: str(tmp_path / 'cache'))
    source_calls = []
    monkeypatch.setattr(racecard.Fetcher, 'get', lambda self, url: source_calls.append(url) or 'html')
    actual = dict(published, distance_m=1800) if source_changed else published
    monkeypatch.setattr(racecard, 'parse_jra', lambda html, race_id, target, stamp: actual)
    validated = []
    monkeypatch.setattr(racecard, 'validate_race', validated.append)
    network.responses = payloads[:2] + [b'stale', payloads[2]]
    if source_changed:
        with pytest.raises(ValueError, match='source race changed since publication'):
            racecard.main()
    else:
        racecard.main()
        assert json.loads(capsys.readouterr().out.splitlines()[-1])['source_reconciliation'] == 'PASS'
    assert validated == [published]
    assert source_calls == [published['source_url']]
    assert network.sleeps == [5]
