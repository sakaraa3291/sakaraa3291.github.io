# v4.2 operational status — 2026-09-18

## Result

GitHub Actions based automatic updating is installed on production `main` and the first
`workflow_dispatch` production no-op run has completed successfully.

- automation install commit: `1ca9bf4e0270a0a5a694462424d057f5c1fde769`
- workflow: `Horse racing v4.2 update`
- first run: `35296287793`
- first run conclusion: `success`
- requested cutoff: `2026-09-13`
- update result: `NO_CHANGES`
- Pages build type: `workflow`
- Pages status after installation: `built`
- app version remains `3.8.0`
- dataset id remains `fbeec520667fb2bf4794407b`

The Chromebook is no longer required for scheduled execution. The schedule is
Tuesday 05:23 JST (`23 20 * * 1`) and manual dispatch remains available.

## Production invariants

The install did not alter production data or the PWA shell. Verified SHA256:

- `lapdata.json`: `d31d02a7f97e6caa292940ed66012b9db3fe0b36fa83cf5226c7cd5eb7612f61`
- `pedigree_stats.json`: `d89c62f41e87a67b64baee90165db727c40218f40ebdf65de5977ce2bc840692`
- `courses.json`: `71a84783890fc812a58726f8f73b7363b8b2876729b78651d380423524a52d30`
- `elevation.json`: `a39c9c64e6dfb94a1c48c60d68e46dcf499068c723c3fedbab6a82efa3bc49a3`

Public verification after the first Actions run passed for all five public data/version files.

## Reproduction blocker resolution

The preserved `state-before-overlap-fix` snapshot exactly reproduces the reported blocker:

- 950 lap conditions / 18,081 races
- 16 extra condition keys / 1 missing condition key
- 135 shared condition keys with differing values

The audited baseline ends on 2026-08-02. Of the cached 512 races, 156 overlap the
baseline and 356 are new. Bootstrap now refreshes only explicitly authorized overlaps
in place and appends only truly new race IDs while preserving untouched history/order.

The cache also required 96 recorded class corrections in
`bootstrap_class_overrides.csv`, hash-bound in `bootstrap_audit.json`.

Saved-state progression confirms the fix:

- before overlap fix: 950 conditions / 18,081 races
- after overlap handling: 957 conditions / 18,238 races
- corrected/final bootstrap: 935 conditions / 18,256 races
- current persistent state: 935 conditions / 18,256 races, exact production match

Pedigree reproduction previously counted 242,485 accepted starts. The corrected
non-starter rule excludes 31 additional blank-rank / blank-odds non-starters, yielding
the released 242,454 accepted starts. `中止` remains included.

## Verification completed before push

- pytest: 29 passed
- strict cached delta: 512/512 metadata, 498/498 flat laps, 512/512 details,
  512/512 corners, 512/512 payout, 4,997/4,997 pedigree coverage
- offline bootstrap: PASS without network refetch
- historical lap: 934 conditions / 17,759 races exact
- historical pedigree: 1,444 conditions exact
- current lap: 935 conditions / 18,256 races exact
- current pedigree: 1,445 conditions / 242,454 starts exact
- grade keys preserved: 142
- production dry run through 2026-09-13: NO_CHANGES
- state manifest/hash checks: PASS
- workflow YAML parse: PASS

## First hosted production run

GitHub Actions run `35296287793` executed from commit `1ca9bf4`.

- dependency installation: PASS
- contract and safety tests: 29 passed
- persistent state exact regression: PASS
- pedigree baseline exact match: 1,445 conditions
- lap result: 935 conditions / 18,256 races
- pedigree accepted starts: 242,454
- validate/update: `NO_CHANGES`
- commit step: correctly skipped
- deploy step: correctly skipped because no data changed
- overall workflow conclusion: `success`

Pages was changed from legacy branch deployment to GitHub Actions deployment mode.
The existing public site remained built and runtime verification passed after the change.

## Operating behavior

Future scheduled runs discover completed JRA races, exclude committed race IDs, fetch
only deltas, enforce completeness, update persistent state and public JSON in one
transaction, push with fast-forward semantics only, deploy Pages only when data changed,
and verify public hashes after deployment. Failures are fail-closed.

Do not modify `courses.json`, `elevation.json`, the UI/PWA shell, or app version as part
of data automation. The 512 cached races and their pedigree data are bootstrap evidence
and must not be fetched again merely to reconstruct state.

## Final operational acceptance — 2026-09-23

**Completion status: operational.** Both the automatic schedule trigger path and
end-to-end hosted production execution path have been demonstrated. A successful
natural schedule run after the fix has not yet been observed. The 2026-09-18
sections above remain the historical acceptance record.

### Automatic schedule and production fixes

- The Tuesday 2026-09-22 schedule automatically triggered
  [run `35667241529`](https://github.com/sakaraa3291/sakaraa3291.github.io/actions/runs/35667241529),
  confirming the schedule trigger itself works.
- That natural scheduled run used pre-fix code and failed at `Validate and update`.
  Non-meeting-day detection depended on obsolete wording, and race discovery lacked
  per-day scoping for race-list HTML containing multiple dates.
- Operational debugging also found and fixed missing valid results for new races at
  `db.netkeiba.com/race/{id}`, parser incompatibility with current result HTML, and
  a starter-count bug that used the entire batch's count instead of each race's count.
- Fix commit: `10917fbb040b0ad152a2f91848da81cdcae84fd0`
  (`Fix hosted race discovery and current result parsing`).
- Codex final tests: **59 passed**.
- Protected production/state/UI SHA values were unchanged by the fix commit; its
  changes were limited to discovery, result fetching/parsing, and tests.

### Successful hosted production update after the fix

The same `Horse racing v4.2 update` workflow completed a production
`workflow_dispatch` in
[run `35807486208`](https://github.com/sakaraa3291/sakaraa3291.github.io/actions/runs/35807486208)
with `to_date=2026-09-22` and `dry_run=false`. Workflow conclusion: **success**;
both the update job and deploy job succeeded.

- Discovered/fetched actual new race data: **72 races**, for 2026-09-14 through
  2026-09-22.
- Pedigree requested / fetched / errors: **193 / 193 / 0**.
- Strict delta validation: **PASS**.
- Master: **464,161 → 465,102 rows**; delta **72 races / 941 rows**.
- Payout: **72 races / 855 delta rows**; total **219,216 rows**.
- Rebuilt lap: **935 conditions / 18,325 races / through 2026-09-22**.
- Rebuilt pedigree: **1,445 conditions / source_rows 244,266 /
  accepted_rows 243,355 / excluded 911 / through 2026-09-22**.
- `UPDATE_READY`: `applied=true`.
- Actions committed persistent state and public data together, then pushed to `main`:
  `f4290e26b99b5796c09580a47109482d8b91a604`
  (`Update horse racing data and persistent state`).
- Pages deployment: **success**.
- Public SHA verification: **PASS** for `lapdata.json`, `courses.json`,
  `elevation.json`, `pedigree_stats.json`, and `data-version.json`.
- `PAGE_URL`: https://sakaraa3291.github.io/

This proves the complete hosted production path: fetch 72 new races → validate →
commit state/public data → push → Pages deploy → public SHA verification.

### Accepted production metadata and invariants

The latest `origin/main` production data commit
`f4290e26b99b5796c09580a47109482d8b91a604` was synchronized locally with
`git pull --ff-only origin main` before this documentation update.
Its `data-version.json` and `automation/state/manifest.json` agree on the production
lap and pedigree SHA256 values; local file hashes also match. The state manifest
records `through=2026-09-22`, and `data-version.json` records
`updated_at=2026-09-23T01:51:30+00:00`.

| Production file | SHA256 |
| --- | --- |
| `lapdata.json` | `537a3162f847f39f96793a3bd9d5f7f9cf1dec91d6c1a03af46d3c988577b689` |
| `pedigree_stats.json` | `89a197b446425cb1c67b1e5d224f0ebd6fae6ce3f9ca6a4f833a68b27a69b196` |
| `courses.json` | `71a84783890fc812a58726f8f73b7363b8b2876729b78651d380423524a52d30` |
| `elevation.json` | `a39c9c64e6dfb94a1c48c60d68e46dcf499068c723c3fedbab6a82efa3bc49a3` |
| `data-version.json` | `30cc57fd04a676e9e47a155c26374a4eaae7d9722bbecf9be48daa187f61aa43` |

The `courses.json` and `elevation.json` hashes are unchanged from the 2026-09-18
record. The UI/PWA shell remains unchanged; app version remains `3.8.0` and dataset
id remains `fbeec520667fb2bf4794407b`. These remain protected invariants and must not
be changed by data automation. This acceptance update changes only
`automation/OPERATIONAL_STATUS.md`, with no production JSON or state edits.

The Chromebook is not required. The next scheduled execution uses the same hosted
GitHub Actions workflow on `main`, with the fixes in place, at Tuesday 05:23 JST
(`23 20 * * 1`). Operational acceptance rests on the demonstrated automatic trigger
and the successful end-to-end hosted production dispatch; it does not claim that a
post-fix natural scheduled run has already succeeded.
