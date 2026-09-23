# Prediction racecards v1

The daily workflow discovers every JRA race from netkeiba's date-scoped meeting
manifest and NAR JpnI/JpnII/JpnIII races from the official monthly calendar and
each actual meeting's race menu. Dates are never kept in a hand-maintained list.
NAR S/H grades and ordinary races are excluded. An unpublished meeting, changed
layout, missing entry, challenge or ambiguous cancellation fails closed.

## Reading public data

1. Fetch `/prediction-data/latest.json` and compare `target_date` with the user's
   requested **Asia/Tokyo** date. Latest means the most recent target date published,
   which may be tomorrow after 21:00. It is not an assertion that the data is today.
2. For another date use `/prediction-data/YYYY-MM-DD/index.json`.
3. Select a race by `venue` + `race_number` or `race_name`, and fetch its `url`.
4. Check `race_status`, `entry_status`, `availability`, `fetched_at` and per-field
   observation times before using the facts. The index contains hashes for details.
5. `dataset_context` contains exact v4.2 condition keys for that venue, surface and
   distance. Keys still include class and going; these are alternatives, not a
   blended estimate. `derived_from` pins the source dataset and hashes. Historical
   replays mark `contains_target_or_later_results`; they must not be used as a
   leakage-free historical forecast.

`predictions` is separate from acquired facts and starts entirely null. No
running-style or suitability judgement is fabricated. History keeps raw source
text alongside structured fields. Missing source IDs remain null in history;
they are never guessed from names. Current JRA IDs use the netkeiba namespace;
official NAR IDs use the nar namespace. They are not interchangeable.

## Operations

UTC crons `0 12`, `0 22`, `30 2` correspond to 21:00, 07:00, 11:30 JST. The first
targets the next day; the others target the current day. A delayed scheduled run
uses the most recent scheduled JST slot. Manual dispatch accepts `target_date`;
empty means today before 21:00, tomorrow thereafter. Historical replays never
move latest backwards. GitHub may delay schedules; this is not a realtime feed.

`python -m automation.racecard.run --target-date YYYY-MM-DD` fetches and validates
without publication. Add `--apply` to atomically exchange the entire public
prediction directory on Linux. Both sources must succeed before any production
change. Diagnostics are retained in the run artifact, independently by source.

JRA history is cached per horse, target date and JST retrieval date. The public
five-slot card may include rest intervals; v4.2 history supplements it using horse
ID plus race ID. No separate horse-page fetch is needed. The source may have fewer
than five actual starts. NAR includes its five historical columns with the card,
so there are no extra NAR history HTTP requests. Existing v4.2 state is read-only.

Actual JRA odds come from the same public odds response used by the racecard.
`yoso` is not actual betting data and produces null/not_published. A failed odds
request fails the candidate. `not_available` describes values the source does not
expose (e.g. unmeasurable body weight); it does not mean zero. Missing mandatory
identity or field-size metadata fails validation. Removed horses/races without
explicit source status also fail instead of silently deleting published entries.

Only material content changes update JSON. On NO_CHANGES, timestamps retain the
last material observation, and no commit/push happens. Timestamps are not an
availability heartbeat. The schema's major version is checked on all reads.

Both production workflows share `keiba-production-update` concurrency for their
entire update/deploy lifetime. They verify checkout HEAD against live main before
staging and immediately before deployment. Non-fast-forward pushes and stale
deployments abort. No force push or automatic rebase is used. The racecard bot
can commit only `prediction-data/**/*.json` and `automation/racecard-state/cache.json`.

After deployment, every JSON is fetched again from Pages and byte/schema-checked.
One real race is fetched freshly from its source and compared for race identity,
distance, start time, all horses, jockey IDs/names, carried weights and entry status.
Completion requires successful hosted execution and this public/source comparison.
See `ACCEPTANCE.md` for observed evidence; local tests alone do not establish completion.
