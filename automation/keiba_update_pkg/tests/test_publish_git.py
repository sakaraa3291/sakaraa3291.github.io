from __future__ import annotations
import hashlib, json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUB = ROOT / "tools" / "publish_release_git.py"


def sha(p: Path):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run(cmd, cwd=None, check=True):
    return subprocess.run([str(x) for x in cmd], cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check)


def setup_repo(tmp_path: Path):
    bare = tmp_path / "remote.git"
    run(["git", "init", "--bare", bare])
    seed = tmp_path / "seed"
    run(["git", "init", "-b", "main", seed])
    run(["git", "config", "user.name", "Test"], cwd=seed)
    run(["git", "config", "user.email", "test@example.com"], cwd=seed)
    (seed / "courses.json").write_text('{"course":"x"}\n', encoding="utf-8")
    (seed / "elevation.json").write_text('{"elevation":"x"}\n', encoding="utf-8")
    (seed / "lapdata.json").write_text('{"old":1}\n', encoding="utf-8")
    (seed / "pedigree_stats.json").write_text('{"old":1}\n', encoding="utf-8")
    current_ver = {
        "schema_version": 2,
        "app_version": "3.8.0",
        "dataset_id": "test-dataset",
        "updated_at": "2026-09-13T00:00:00Z",
        "files": {
            "lapdata.json": sha(seed / "lapdata.json"),
            "pedigree_stats.json": sha(seed / "pedigree_stats.json"),
            "courses.json": sha(seed / "courses.json"),
            "elevation.json": sha(seed / "elevation.json"),
        },
    }
    (seed / "data-version.json").write_text(json.dumps(current_ver, indent=2) + "\n", encoding="utf-8")
    run(["git", "add", "."], cwd=seed)
    run(["git", "commit", "-m", "seed"], cwd=seed)
    run(["git", "remote", "add", "origin", bare], cwd=seed)
    run(["git", "push", "-u", "origin", "main"], cwd=seed)
    run(["git", "--git-dir", bare, "symbolic-ref", "HEAD", "refs/heads/main"])
    repo = tmp_path / "repo"
    run(["git", "clone", bare, repo])
    run(["git", "config", "user.name", "Test"], cwd=repo)
    run(["git", "config", "user.email", "test@example.com"], cwd=repo)
    return repo, bare


def make_candidate(tmp_path: Path, repo: Path):
    W = tmp_path / "work"
    R = W / "release"
    R.mkdir(parents=True)
    (W / "UPDATE_READY").write_text("ready\n", encoding="utf-8")
    (R / "lapdata.json").write_text('{"meta":{"to":"2026-09-20"},"cond":{},"grade":{}}\n', encoding="utf-8")
    (R / "pedigree_stats.json").write_text('{"meta":{"source_rows":1},"stats":{}}\n', encoding="utf-8")
    ver = {
        "schema_version": 2,
        "app_version": "3.8.0",
        "dataset_id": "test-dataset",
        "updated_at": "2026-09-20T00:00:00Z",
        "files": {
            "lapdata.json": sha(R / "lapdata.json"),
            "pedigree_stats.json": sha(R / "pedigree_stats.json"),
            "courses.json": sha(repo / "courses.json"),
            "elevation.json": sha(repo / "elevation.json"),
        },
    }
    (R / "data-version.json").write_text(json.dumps(ver, indent=2) + "\n", encoding="utf-8")
    report = {"status": "PASS", "to": "2026-09-20", "hashes": ver["files"]}
    (R / "validation_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return W


def test_publish_pushes_only_three_files(tmp_path):
    repo, bare = setup_repo(tmp_path)
    W = make_candidate(tmp_path, repo)
    p = run([sys.executable, PUB, "--workdir", W, "--repo", repo, "--skip-public-check"])
    result = json.loads(p.stdout)
    assert result["status"] == "PUSHED"
    show = run(["git", "--git-dir", bare, "show", "--pretty=format:", "--name-only", "main"]).stdout.splitlines()
    assert sorted(x for x in show if x.strip()) == ["data-version.json", "lapdata.json", "pedigree_stats.json"]
    assert run(["git", "status", "--porcelain"], cwd=repo).stdout.strip() == ""


def test_dirty_worktree_is_refused(tmp_path):
    repo, _ = setup_repo(tmp_path)
    W = make_candidate(tmp_path, repo)
    (repo / "junk.txt").write_text("x", encoding="utf-8")
    p = run([sys.executable, PUB, "--workdir", W, "--repo", repo, "--dry-run"], check=False)
    assert p.returncode != 0
    assert "REFUSE_DIRTY_WORKTREE" in (p.stdout + p.stderr)


def test_bad_candidate_hash_is_refused(tmp_path):
    repo, _ = setup_repo(tmp_path)
    W = make_candidate(tmp_path, repo)
    (W / "release" / "lapdata.json").write_text("tampered\n", encoding="utf-8")
    p = run([sys.executable, PUB, "--workdir", W, "--repo", repo, "--dry-run"], check=False)
    assert p.returncode != 0
    assert "candidate hash mismatch" in (p.stdout + p.stderr)


def test_no_changes_safe_exit(tmp_path):
    repo, _ = setup_repo(tmp_path)
    W = make_candidate(tmp_path, repo)
    for name in ("lapdata.json", "pedigree_stats.json", "data-version.json"):
        (repo / name).write_bytes((W / "release" / name).read_bytes())
    run(["git", "add", "."], cwd=repo)
    run(["git", "commit", "-m", "already current"], cwd=repo)
    p = run([sys.executable, PUB, "--workdir", W, "--repo", repo, "--skip-public-check"])
    result = json.loads(p.stdout)
    assert result["status"] == "NO_CHANGES"
