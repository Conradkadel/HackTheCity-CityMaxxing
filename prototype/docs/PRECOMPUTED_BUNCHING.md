# Precomputed bunching analysis

The replay map and line modal calculate exploratory candidates on demand. The pre-analysis pipeline adds a reproducible database layer for line/day statistics and stable links back to the evidence.

## What is stored

The pipeline deliberately separates five concepts:

```text
analysis_runs ──< bunching_episodes ──< bunching_evidence
```

- `analysis_runs` records the active vehicle dataset, date, operator, detector version, parameters, execution status, and totals.
- `bunching_episodes` consolidates repeated detections for the same two vehicle trips into one occurrence.
- `bunching_evidence` preserves every stop-level detection supporting an episode.

## Current detector: `stop-headway-v1`

The first batch detector intentionally reuses the same conservative stop evidence as the line-analysis modal:

1. Resolve each vehicle event through the operation plan valid for its operator and operational date.
2. Match its trip exactly and obtain the public line, route, and direction.
3. For each vehicle/trip/reported-stop group, use the earliest report as reported-stop evidence.
4. At the same scheduled stop, create a raw candidate when two different trips were reported no more than 180 seconds apart but were planned at least 300 seconds apart.
5. Group detections for the same unordered vehicle-trip pair, route, and direction when successive evidence points are no more than 1,200 seconds apart.
6. Classify an episode as `multi_stop_candidate` when it contains at least two distinct stops. Otherwise retain it as `single_point` evidence.

Default parameters are stored with every run:

```json
{
  "maximumObservedGapSeconds": 180,
  "minimumPlannedGapSeconds": 300,
  "maximumEvidenceGapSeconds": 1200,
  "minimumDistinctStops": 2,
  "usesPositionInterpolation": false
}
```

The parameters belong to the run, so later algorithms or thresholds can coexist without overwriting earlier results. Statistics count `multi_stop_candidate` episodes by default; they do not count every affected stop as a separate bunch.

## Run the analysis

After the API has started once and applied migration `006_bunching_analysis.sql`, analyze one operator and date:

```sh
docker compose run --rm api \
  python analyze_bunching.py --date 2026-09-01 --operator IA9T6
```

Restrict a validation run to one or more public lines:

```sh
docker compose run --rm api \
  python analyze_bunching.py --date 2026-09-01 \
  --operator IA9T6 --line 755 --line 28E
```

Omitting `--operator` analyzes every operator with availability on that date. Omitting `--line` analyzes every public line that has an exact observed-trip match for the selected operator.

Analyze the complete Monday–Sunday week containing a date:

```sh
docker compose run --rm api \
  python analyze_bunching.py --week-containing 2026-09-01 \
  --operator IA9T6
```

The same optional repeated `--line` restriction applies. When an operator is explicitly supplied, a run is written for every date in the week, including dates with no matching episodes, so the UI can distinguish “analysis completed with zero candidates” from “not analyzed.”

Each invocation creates a new `analysis_runs` row. It does not delete or mutate earlier completed runs. The row records whether it covers `all_observed_lines` or only `selected_lines`, plus the exact analyzed line list. An unfiltered operator summary uses only a complete all-lines run; a line-filtered request may use the latest run containing that line. This prevents a quick one-line validation run from silently replacing complete operator statistics. A failed execution is retained with its error and cannot become the current result.

## Read stored statistics

Summary for the latest completed run:

```http
GET /api/bunching/summary?date=2026-09-01&operator=IA9T6
```

Optional `line` and `detector_version` filters are supported. The response contains run metadata and exact parameters, episode totals by line, supporting evidence counts, and observed/planned headway ranges.

Retrieve qualified episodes:

```http
GET /api/bunching/episodes?date=2026-09-01&operator=IA9T6&line=755
```

Set `include_single_point=true` to include one-stop signals. A response is capped at 5,000 episodes. Retrieve complete support for one episode with `GET /api/bunching/episodes/{episode_id}/evidence`.

The route-tab weekly modal uses:

```http
GET /api/bunching/week?date=2026-09-01&operator=IA9T6&line=755
```

The supplied date selects its Lisbon Monday–Sunday week. The response contains seven explicit day entries, an `analysisAvailable` flag for each day, exact episode time ranges and stops, and week totals. It returns only qualified `multi_stop_candidate` episodes.

The Routes-tab ranking and line badges use one compact aggregate request:

```http
GET /api/bunching/week-summary?date=2026-09-01
```

It returns per-line candidate totals and analyzed-day coverage for the same
Monday–Sunday week. Opening a line still loads its full evidence separately.
These totals are not normalized by departures, trips, vehicle-hours, or passenger
volume and therefore should not be interpreted as a probability or fair service
quality comparison without an exposure denominator.

The endpoints return valid empty responses with an explanation when no completed run exists. The current replay UI continues to calculate its time-specific map overlay from loaded observations; it has not yet been changed to present stored daily statistics.

## How to interpret an episode

A `multi_stop_candidate` means the same two matched vehicle trips repeatedly satisfied the stop-headway rule at two or more distinct stops. It does **not** establish an exact physical arrival time, door opening, continuous proximity, traffic causation, or continued bunching after the final evidence point.

The current source generally reports at intervals, and the pipeline does not interpolate between coordinates. Stored coordinates are scheduled-stop coordinates used as a stable approximate episode location, not reconstructed vehicle positions.

## Recommended next detector version

A stronger detector should be introduced under a new version such as `route-progress-v2`, leaving `stop-headway-v1` intact. It should:

- map observations to the correct route shape;
- interpolate route progress and approximate stop-passing time between reports;
- evaluate headway continuously rather than only through supplied stop IDs;
- require persistence across distance or consecutive stops;
- distinguish terminal layovers, diversions, missing reports, and direction changes;
- calculate a confidence score and retain the raw supporting observations.

Never rewrite old analysis rows to make a new detector look equivalent. Re-run with a new `detector_version`, compare results, and document the validation basis.
