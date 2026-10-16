"""Bounded Pages propagation retries shared by both publication verifiers."""
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class PublicVerifier:
    # One deadline for all public paths, including requests and retry sleeps.
    TOTAL_SECONDS = 120
    RETRY_SECONDS = 5
    REQUEST_SECONDS = 30

    def __init__(self, base_url):
        self.base_url = base_url.rstrip('/') + '/'
        self.deadline = time.monotonic() + self.TOTAL_SECONDS

    def verify(self, path, matches, mismatch):
        attempt = 0
        reason = mismatch
        while True:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError(f'{reason}; public verification budget exhausted '
                                 f'({self.TOTAL_SECONDS}s total), path: {path}, attempts: {attempt}')
            attempt += 1
            request = Request(self.base_url + path + '?verify=' + uuid.uuid4().hex,
                              headers={'Cache-Control': 'no-cache'})
            try:
                with urlopen(request, timeout=min(self.REQUEST_SECONDS, remaining)) as response:
                    content = response.read()
                if matches(content):
                    if attempt > 1:
                        print(f'PASS after retry: {path}; attempt {attempt}', flush=True)
                    return content
                reason = mismatch
            except HTTPError as exc:
                exc.close()
                if exc.code not in (404, 408, 429, 500, 502, 503, 504):
                    raise
                reason = f'public HTTP {exc.code}: {path}'
            except (URLError, TimeoutError, ConnectionError) as exc:
                reason = f'public transient {type(exc).__name__}: {path}'
            remaining = max(0, self.deadline - time.monotonic())
            delay = min(self.RETRY_SECONDS, remaining)
            print(f'RETRY: {reason}; attempt {attempt}; wait {delay:.1f}s; '
                  f'budget remaining {remaining:.1f}s', flush=True)
            if delay:
                time.sleep(delay)
