#!/usr/bin/env python3
from __future__ import annotations
import argparse, subprocess, sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description="Run incremental update and publish the validated three-file release to GitHub.")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--public-base", default="https://sakaraa3291.github.io/")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--remote", default="origin")
    ap.add_argument("--message", default="Update horse racing data")
    args, update_args = ap.parse_known_args()
    root = Path(__file__).resolve().parents[1]
    if "--workdir" not in update_args:
        raise SystemExit("--workdir is required for the update runner")
    wi = update_args.index("--workdir")
    try:
        workdir = update_args[wi + 1]
    except IndexError:
        raise SystemExit("--workdir value missing")
    subprocess.run([sys.executable, str(root / "tools" / "run_incremental_update.py"), *update_args], check=True)
    W = Path(workdir)
    if (W / "NO_CHANGES").exists() and not (W / "UPDATE_READY").exists():
        print("NO_CHANGES: publish skipped")
        return 0
    subprocess.run([
        sys.executable, str(root / "tools" / "publish_release_git.py"),
        "--workdir", workdir,
        "--repo", args.repo,
        "--branch", args.branch,
        "--remote", args.remote,
        "--public-base", args.public_base,
        "--message", args.message,
    ], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
