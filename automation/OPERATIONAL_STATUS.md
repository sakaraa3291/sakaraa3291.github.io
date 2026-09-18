# v4.2 local operational status — 2026-09-18

Implemented locally. No GitHub push, workflow run, or deployment was performed.
The app remains **3.8.0**. Production JSONs, UI, Service Worker, courses.json,
and elevation.json are unchanged by this work.

## Ready

- `.github/workflows/keiba-update.yml`: manual dispatch (dry run by default),
  Tuesday 05:23 JST schedule, GitHub-hosted Ubuntu/Python 3.13, contents write,
  serialized runs without cancellation, explicit Pages deployment and public SHA checks.
  The Chromebook is not needed after publication.
- Repository-owned scripts, mappings, dependency pins, and persistent state in
  `automation/`; no runtime dependency on local absolute paths, caches, or artifacts.
- Public data and state are committed together. Ordinary fast-forward push only;
  a concurrent change to main fails instead of being overwritten.
- Hash-bound state/production baseline, aggregate regression before each update,
  static hashes, app/dataset identity, completed JST date bounds, strict target and
  result completeness, preserved historical rows/grade/manual notes, and a
  seven-file transaction allowlist gate publication.
- No-op runs neither rewrite production/state nor create commits/deployments.
  Stale success markers cannot authorize a new run. Unknown/partial discovery pages
  and incomplete meeting lists fail closed. Future targets must be JRA IDs.
- The Pages artifact contains the existing app and version test sites; it excludes
  automation source, state CSVs, and GitHub configuration.

## Bootstrap audit

The supplied `keiba_master_baseline.csv.gz` actually ends on **2026-08-02**, not
July 19. It has 459,452 rows / 39,640 race IDs. Of the cached 512 races, 156 overlap
that master and 356 are new. The merge produces **464,161 rows / 39,996 race IDs**
through **2026-09-13**, plus 218,361 payout rows and 47,164 pedigree rows.

No cached race was fetched again. Overlaps are refreshed from the cache by race ID,
with matching horse keys required and original master row positions preserved.
Untouched rows and all history through July 19 remain cell-for-cell unchanged.
Replacement is explicit via `--allow-replace-race-ids`; ordinary updates reject
unexpected overlaps. Reapplying authorized input does not duplicate results.

The local cache contains **480 JRA and 32 NAR race IDs**. All 512 are retained for
bootstrap fidelity; future automated discovery/updates accept only JRA IDs.
The raw cache also needs **96 race-class corrections** (1,236 horse rows).
`keiba_update_pkg/config/bootstrap_class_overrides.csv` records these by race ID,
from the supplied `state_20260913` master. Its provenance and source hashes are
recorded in `state/bootstrap_audit.json`. Original cache files were not changed.

The local checkout initially held July 19 production JSONs. During this session
it advanced to the package's recorded release commit
`d2c62094f5c20a38618b828d4f893a8ebae2900a`. Final verification uses the actual
September 13 JSON bytes and recorded SHA256 values, not the earlier cutoff.

Other fixes: classify races from the race header instead of navigation text;
exclude scratched/non-starting horses (`取消`, `除外`) from pedigree denominators
while retaining `中止`; make metadata enrichment repeatable; handle an empty grade
increment under pandas 3; retain the last actual race date when a requested window
ends with a non-racing day. Unknown classes block publication.

## Local verification

- Contract/safety tests, Python compilation, and dependency checks pass.
- Full current-baseline regression: **935 lap conditions / 18,256 races** exactly
  match; **1,445 pedigree conditions / 242,454 accepted starts** match with the
  package's numeric tolerance of 1e-12; all **142 grade keys** and manual audit notes
  are preserved. The 31 scratched/excluded cache rows explain the previously
  prepared state's 242,485-start discrepancy.
- Production dry run through 2026-09-13: **NO_CHANGES**, no production/state writes.
- Workflow YAML parses; dispatch, schedule, permissions and concurrency checks pass.
  Pages staging retains the app/test sites and excludes automation/state.
- `VALIDATION_REPORT.json` records final counts/checks and production hashes.
  Detailed local logs are under ignored `automation/runs/`.

The package's old `test_regression_all.py` assumes July 19 and reconstructs grade
history. It is unsuitable for the current manually curated baseline: its historical
condition check passed, but grade reconstruction disagreed with 16 curated records.
Use `automation/verify_state.py`, which checks preservation rather than replacing
manual records. This old diagnostic is not the Actions gate.

The venv is `/home/kenei2473f/keiba_update_v42/.venv`. `ensurepip` was absent and
PyPI DNS was unavailable, so installed local packages were copied into this venv,
with system packaging 25.0; `pip check` passes. Hosted runners install the pinned
requirements normally. Live source fetching, GitHub token/branch permissions,
Pages configuration and deployed public SHA checks remain to be tested on GitHub.

## Exact remaining publish/run steps

These steps are documented only; **do not run the push until publication is authorized**.
From `/home/kenei2473f/sakaraa3291.github.io`:

```bash
PY=/home/kenei2473f/keiba_update_v42/.venv/bin/python
$PY -m pytest -q automation/keiba_update_pkg/tests automation/tests
$PY automation/verify_state.py --out automation/runs/prepublish-verification
$PY automation/run_update.py --to-date 2026-09-13 --workdir automation/runs/prepublish-noop
# Expected: NO_CHANGES. Use a fresh workdir each invocation.
git add -- automation .github/workflows/keiba-update.yml
git diff --cached --stat
git commit -m 'Add hosted horse racing v4.2 automation and persistent state'
git fetch origin
git rebase origin/main
# If upstream data changed, reconcile/revalidate state before continuing.
git push origin main
```

1. In repository Settings → Actions, enable Actions and allow the workflow's write
   permission. Check branch rules permit this bot's data/state commit; otherwise the
   workflow will fail safely at push. Do not silently bypass required reviews.
2. In Settings → Pages, select **GitHub Actions** as the build/deployment source.
   Ensure the `github-pages` environment allows main. The workflow deploys explicitly
   because a GITHUB_TOKEN push does not provide a reliable branch-Pages build trigger.
3. Run the first hosted no-op verification:

   ```bash
   gh workflow run keiba-update.yml --ref main -f to_date=2026-09-13 -f dry_run=true
   gh run list --workflow keiba-update.yml --limit 5
   gh run watch RUN_ID --exit-status
   ```

   Expect successful tests/regression and NO_CHANGES, with commit and deploy skipped.
4. Run a hosted live-source dry run through yesterday (date omitted):

   ```bash
   gh workflow run keiba-update.yml --ref main -f dry_run=true
   ```

   Review its logs and `keiba-run-RUN_ID-ATTEMPT` artifact. A source layout, challenge,
   partial meeting, unknown class or missing data must be resolved before publication.
5. When that succeeds, enable the scheduled workflow for unattended use, or run:

   ```bash
   gh workflow run keiba-update.yml --ref main -f dry_run=false
   ```

   New data should produce one commit containing the three public JSONs and four
   persistent-state files, followed by Pages deployment and five public SHA checks.
   Schedules run automatically once the workflow is on main; disable the workflow
   temporarily while doing initial hosted acceptance if needed.

## Recovery and maintenance

- State is durable in Git, not in an expiring Actions cache. Keep it in the same
  commit as the public JSONs. Current compressed master is about 33 MiB.
- Failed fetches retain per-race checkpoints in the run artifact for 14 days.
  To resume without refetching completed races, download the artifact and use the
  package's `run_incremental_update.py` with its original arguments/workdir; review
  the result before applying it. A new hosted run uses fresh scratch space and may
  refetch an **unpublished** failed window, but excludes all race IDs in committed state.
- If push succeeds but deployment fails, rerun **failed jobs** of that same run;
  the deploy job checks out its exact recorded commit. A new no-op update deliberately
  does not deploy. If public SHA verification fails, inspect Pages/caching and rerun
  the failed deployment job; Git data/state are not rolled back automatically.
- For bootstrap reconstruction use an empty output directory:

  ```bash
  $PY automation/bootstrap_state.py \
    --bootstrap /home/kenei2473f/keiba_update_v42/bootstrap \
    --release-record /home/kenei2473f/keiba_update_v42/keiba_update_pkg/PRODUCTION_RELEASED_20260917.json \
    --out automation/runs/reconstructed-state
  ```

  This is offline and uses the audited correction map. Do not replace newer persistent
  state with bootstrap output. The original package's release manifests describe its
  prior release; the runnable hosted entry point is `automation/run_update.py`, not
  the legacy combined Git publisher. Patched source tools are also synchronized to
  the supplied local package.
