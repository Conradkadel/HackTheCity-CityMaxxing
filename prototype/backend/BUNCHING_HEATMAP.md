# Bunching heatmap backend / frontend handoff

Backend only: no map, chart, filter, frontend type, CSS or package changes are
included. The eventual frontend can use the two endpoints below independently
of the traffic filter. Both endpoints are read-only and include every imported
operational date of the selected operator in the active vehicle dataset.

## Prepare history

The source is the existing versioned `analysis_runs → bunching_episodes →
bunching_evidence` pipeline. No extra migration or Waze data is required.

```sh
docker compose up -d --build --wait api
docker compose run --rm api python analyze_bunching.py --all-dates --skip-completed
```

This analyzes all observed public lines of every operator on every imported
**operational** date. It is a separate batch operation; HTTP requests never
launch analysis or scan vehicle reports to detect episodes. Repeat the command
after importing a new dataset. Existing compatible completed days are skipped.
To limit a development backfill, add `--operator IA9T6 --line 755 --line 728`.
Omit `--skip-completed` to intentionally recompute. Failure retains a failed run
without exposing its partial results. The command stops if the active dataset
changes between jobs. Existing `--date` and `--week-containing` remain supported.

Until backfill finishes, the endpoints return geometry with explicit missing
coverage and null counts. They do not fabricate zero-event history.

## Map

```http
POST /api/bunching/heatmap/routes
Content-Type: application/json

{"route_keys":["6:118_0","6:204_0"]}
```

Use the actual package/route keys from the routes catalog. Accepts 1–50 keys;
duplicate keys are deduplicated. Each entry in `routes` has:

- `key`, `packageId`, `routeId`, `operatorId`, `line`.
- The common history metadata described below.
- `mappedEpisodeCount`: distinct episodes matched anywhere on these shapes;
  not the sum of the section counts.
- `shapes`: one entry per shape/direction, each with `shapeId`, `directionId`,
  `referenceTripId`, and `sections`.

The longest planned stop pattern is used for each shape/direction. Each section
contains consecutive-stop identifiers and sequence numbers, `fromName`,
`toName`, `points` in **[latitude, longitude]** order, `lengthMeters`,
`geometryAvailable`, `status`, and the following metrics:

```json
{
  "episodeCount": 12,
  "daysWithEpisodes": 4,
  "episodesPerAnalyzedDay": 1.7143
}
```

Those values are illustrative. Geometry follows the selected GTFS shape clipped
between its projected stops. Missing shapes are returned as `points: []` and
`geometryAvailable: false`; stop-to-stop straight lines are not invented.
Choose map colours using `episodeCount`, retaining zero versus unknown as
different states. No palette or relative normalization is hard-coded here.

## Time–space diagram

```http
POST /api/bunching/heatmap/diagram
Content-Type: application/json

{"date":"2026-09-01","agency":"IA9T6","line":"755","direction":"0"}
```

`date` chooses the valid operation plan, **not the history interval**. By default
the reference trip is the line/direction's longest planned trip, matching the
Bunching diagram's stop axis. Analyze line can send both `package_id` and
`trip_id` to use its exact canonical trip. Supplying only one is invalid.

The response includes common metadata, `operatorId`, `line`, `directionId`,
`referenceTripId`, `packageId`, `mappedEpisodeCount` and `sections`. Section
fields match the map contract, plus a dense `cells` array of **48 half-hour
bins**. For example:

```json
{
  "minute": 480,
  "episodeCount": 3,
  "daysWithEpisodes": 2,
  "episodesPerAnalyzedDay": 0.4286
}
```

`minute: 480` is 08:00–08:30 **Europe/Lisbon** time. Counts cover that local clock
band on all analyzed days, including weekends. Place cells using the chart
timestamp's Lisbon time, including after midnight. Autumn's repeated local hour
shares a band. Evidence is assigned by the midpoint of the two reported times
at the stop, not by the episode's start time. An episode can legitimately appear
in more than one bin. The map's all-day count deduplicates it across bins.

Join sections to the chart by ordered stop IDs and sequences. Skip missing or
ambiguous matches; do not match only by display names or reverse the stop pair.

## Coverage and counts

Common metadata includes:

- `datasetVersion`, `detectorVersion`, `detectorParameters` and method
  `incoming-stop-distinct-episodes-v1`.
- `timezone: "Europe/Lisbon"`, `bucketMinutes: 30`, and `period.start/end`, the
  first/last imported operator operational dates.
- `coverage.availableDates`, `analyzedDates`, `missingDates`, `availableDays`,
  `analyzedDays`, `complete`, and `analysisRunIds` for provenance.
- `episodeCount`, `daysWithEpisodes`, `episodesPerAnalyzedDay`: public-line
  totals over all directions, before projection onto selected shapes.
- `unlocatedEvidenceCount`: stop evidence with no resolvable predecessor, such
  as the first stop. Such episodes can remain in the line total.
- `warning` for incomplete history and `evidenceNote` describing interpretation.

Only `multi_stop_candidate` episodes from detector `stop-headway-v1` with its
exact default parameter set are counted. The latest compatible completed run
for each operator/line/date wins. Failed/running runs, other dataset versions,
other detectors, changed parameters and one-stop signals do not contribute.
A later selected-line run can replace that line's older all-line result without
replacing other lines. An all-observed-lines run also certifies zero for lines
not observed on that day. Backfill skipping uses the same compatibility rules.

Each episode is counted **once per directed section**, and once per section/time
bin. Repeated stop reports do not multiply events. The same episode can affect
several sections, so neither section nor time-bin totals may be summed to get
the number of distinct incidents. `mappedEpisodeCount` is deduplicated across
the selected geometry; common `episodeCount` is the deduplicated public-line
total. Overlapping routes may repeat the same historical evidence.

`status` is `available`, `not_analyzed`, or `ambiguous_stop_pair`. With no analyzed
days, all count/rate values are null. With some analyzed days, zero is a genuine
zero **within that analyzed subset**, and `coverage.complete` remains false
until all imported operator days have compatible analysis. Repeated identical
directed pairs in one reference trip are ambiguous and get null metrics.
`episodesPerAnalyzedDay` divides by analyzed operator days, including zero-event
days; it is not a rate per bus trip or a probability.

Historical detections use the evidence trip's actual preceding scheduled stop
and package, then match the displayed plan by public line, direction and ordered
stop pair. This allows multiple plan packages and route variants to contribute
without mixing reversed or skipped-stop pairs. Different road alignments between
the same stop pair are pooled. No evidence is interpolated over intervening
unobserved stops. Stop-based assignment describes where evidence was observed,
not where bunching originated or what caused it. Detector thresholds differ
from the live/prediction overlay; these heatmaps are specifically batch-detector
candidate history.

## Errors and limits

Malformed requests return 422; unavailable routes/trips return 404; no active
dataset returns 503. Missing completed history is a successful response with
null metrics and a warning. Requests use a consistent read-only snapshot and a
30-second SQL timeout. More than 200,000 evidence rows per public line, or more
than 200 selected map shapes, returns 413 without silent truncation. Large
archives should move these same deduplicated metrics to precomputed summaries.

Regression tests are in `test_bunching_heatmap.py`. PostgreSQL tests use an
isolated temporary schema through `TEST_DATABASE_URL`, never the live tables.
