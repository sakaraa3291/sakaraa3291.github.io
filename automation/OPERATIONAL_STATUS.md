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
