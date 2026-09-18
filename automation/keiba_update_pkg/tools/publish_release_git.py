#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

CHANGED = ("lapdata.json", "pedigree_stats.json", "data-version.json")
STATIC = ("courses.json", "elevation.json")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def run(cmd, cwd: Path, capture: bool = True) -> str:
    p = subprocess.run(
        [str(x) for x in cmd], cwd=str(cwd), check=True,
        text=True, stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    return p.stdout.rstrip("\n") if capture else ""


def git(repo: Path, *args: str, capture: bool = True) -> str:
    return run(["git", *args], repo, capture=capture)


def ensure_clean(repo: Path):
    status = git(repo, "status", "--porcelain")
    if status.strip():
        raise SystemExit("REFUSE_DIRTY_WORKTREE\n" + status)


def validate_candidate(workdir: Path, repo: Path | None = None):
    release = workdir / "release"
    ready = workdir / "UPDATE_READY"
    if not ready.exists():
        raise SystemExit(f"UPDATE_READY missing: {ready}")
    report_path = release / "validation_report.json"
    if not report_path.exists():
        raise SystemExit(f"validation_report.json missing: {report_path}")
    report = load_json(report_path)
    if report.get("status") != "PASS":
        raise SystemExit(f"validation status is not PASS: {report.get('status')}")

    for name in CHANGED:
        if not (release / name).is_file():
            raise SystemExit(f"release file missing: {name}")

    ver = load_json(release / "data-version.json")
    if ver.get("schema_version") != 2:
        raise SystemExit("unexpected schema_version")
    files = ver.get("files", {})
    for name in ("lapdata.json", "pedigree_stats.json"):
        actual = sha256(release / name)
        if files.get(name) != actual:
            raise SystemExit(f"candidate hash mismatch: {name}: manifest={files.get(name)} actual={actual}")
        rep_hash = report.get("hashes", {}).get(name)
        if rep_hash and rep_hash != actual:
            raise SystemExit(f"validation report hash mismatch: {name}")

    for name in STATIC:
        expected = files.get(name, "")
        if len(expected) != 64:
            raise SystemExit(f"static hash missing/invalid in data-version: {name}")
        if repo is not None:
            path = repo / name
            if not path.is_file():
                raise SystemExit(f"static repo file missing: {name}")
            actual = sha256(path)
            if actual != expected:
                raise SystemExit(f"REFUSE_STATIC_CHANGE {name}: expected={expected} actual={actual}")

    return release, ver, report


def changed_paths(repo: Path) -> list[str]:
    out = git(repo, "status", "--porcelain")
    paths = []
    for raw in out.splitlines():
        if not raw:
            continue
        # porcelain v1: XY<space>PATH, rename may contain ' -> '
        path = raw[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.append(path)
    return sorted(paths)


def public_fetch_hash(url: str, timeout: int) -> str:
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache", "User-Agent": "keiba-data-publisher/4.2"})
    h = hashlib.sha256()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        while True:
            b = r.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def verify_public(base_url: str, release: Path, retries: int, interval: float, timeout: int):
    base = base_url.rstrip("/") + "/"
    expected = {name: sha256(release / name) for name in CHANGED}
    errors = []
    for attempt in range(1, retries + 1):
        errors = []
        nonce = f"keiba_pub={int(time.time())}_{attempt}"
        for name, want in expected.items():
            url = urllib.parse.urljoin(base, name) + "?" + nonce
            try:
                got = public_fetch_hash(url, timeout)
            except Exception as e:
                errors.append(f"{name}: fetch error {type(e).__name__}: {e}")
                continue
            if got != want:
                errors.append(f"{name}: sha256 {got} != {want}")
        if not errors:
            return {"status": "PASS", "attempt": attempt, "hashes": expected}
        if attempt < retries:
            time.sleep(interval)
    raise SystemExit("PUBLIC_VERIFY_FAILED\n" + "\n".join(errors))


def main():
    ap = argparse.ArgumentParser(description="Fail-closed Git publisher for a validated keiba data release.")
    ap.add_argument("--workdir", required=True, help="Update workdir containing UPDATE_READY and release/")
    ap.add_argument("--repo", required=True, help="Local git checkout of sakaraa3291.github.io")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--remote", default="origin")
    ap.add_argument("--public-base", default="https://sakaraa3291.github.io/")
    ap.add_argument("--message", default="Update horse racing data")
    ap.add_argument("--dry-run", action="store_true", help="Validate everything but do not copy/commit/push")
    ap.add_argument("--skip-push", action="store_true", help="Commit locally but do not push/public-verify; for tests only")
    ap.add_argument("--skip-public-check", action="store_true", help="Push but skip public hash verification")
    ap.add_argument("--public-retries", type=int, default=18)
    ap.add_argument("--public-interval", type=float, default=10.0)
    ap.add_argument("--http-timeout", type=int, default=30)
    a = ap.parse_args()

    W = Path(a.workdir).resolve()
    repo = Path(a.repo).resolve()
    if not (repo / ".git").exists():
        raise SystemExit(f"not a git checkout: {repo}")
    current = git(repo, "branch", "--show-current")
    if current != a.branch:
        raise SystemExit(f"REFUSE_WRONG_BRANCH current={current!r} expected={a.branch!r}")
    ensure_clean(repo)
    release, ver, report = validate_candidate(W, repo)
    current_ver_path = repo / "data-version.json"
    if current_ver_path.is_file():
        current_ver = load_json(current_ver_path)
        if current_ver.get("app_version") != ver.get("app_version"):
            raise SystemExit(f"REFUSE_APP_VERSION_CHANGE current={current_ver.get('app_version')} candidate={ver.get('app_version')}")
        if current_ver.get("dataset_id") != ver.get("dataset_id"):
            raise SystemExit(f"REFUSE_DATASET_ID_CHANGE current={current_ver.get('dataset_id')} candidate={ver.get('dataset_id')}")

    plan = {
        "status": "VALIDATED",
        "branch": a.branch,
        "changed_files": list(CHANGED),
        "app_version": ver.get("app_version"),
        "dataset_id": ver.get("dataset_id"),
        "to": report.get("to"),
    }
    if a.dry_run:
        print(json.dumps({**plan, "dry_run": True}, ensure_ascii=False, indent=2))
        return 0

    backup = {name: (repo / name).read_bytes() if (repo / name).exists() else None for name in CHANGED}
    committed = False
    try:
        for name in CHANGED:
            shutil.copyfile(release / name, repo / name)

        paths = changed_paths(repo)
        unexpected = sorted(set(paths) - set(CHANGED))
        if unexpected:
            raise SystemExit("REFUSE_UNEXPECTED_CHANGES\n" + "\n".join(unexpected))
        if not paths:
            out = {**plan, "status": "NO_CHANGES", "commit": git(repo, "rev-parse", "HEAD")}
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 0

        # Every candidate file should either change or already be byte-identical.
        for name in CHANGED:
            if sha256(repo / name) != sha256(release / name):
                raise SystemExit(f"copy verification failed: {name}")

        git(repo, "add", "--", *CHANGED)
        staged = git(repo, "diff", "--cached", "--name-only").splitlines()
        if sorted(staged) != sorted(paths):
            raise SystemExit(f"REFUSE_STAGE_MISMATCH staged={staged} paths={paths}")
        git(repo, "commit", "-m", a.message)
        committed = True
        commit = git(repo, "rev-parse", "HEAD")
    except BaseException:
        if not committed:
            subprocess.run(["git", "reset", "--quiet", "HEAD", "--", *CHANGED], cwd=str(repo), check=False)
            for name, data in backup.items():
                path = repo / name
                if data is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(data)
        raise

    if a.skip_push:
        print(json.dumps({**plan, "status": "COMMITTED_LOCAL", "commit": commit}, ensure_ascii=False, indent=2))
        return 0

    git(repo, "push", a.remote, f"HEAD:{a.branch}", capture=False)
    result = {**plan, "status": "PUSHED", "commit": commit}
    if not a.skip_public_check:
        result["public_verify"] = verify_public(a.public_base, release, a.public_retries, a.public_interval, a.http_timeout)
        result["status"] = "PUBLISHED_VERIFIED"

    out = W / "PRODUCTION_PUBLISHED.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
