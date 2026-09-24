# Bus-line schedule comparison

The Routes tab provides an **Analyze** action for every date-valid public line. It opens a large modal rather than placing a dense service-day chart in the sidebar.

## How the intended schedule is found

The application does not infer a schedule from the vehicle's coordinates. It uses exact identifiers already present in the two datasets:

1. Select the operation-plan package whose `event_agency_id` matches the vehicle operator and whose validity range contains the observation's `operational_date`.
2. Match `vehicle_events.trip_id` exactly to `schedule_trips.trip_id` inside that package.
3. Join the trip's package-scoped `route_id` to `schedule_routes` to obtain the public line, direction, and route name.
4. Load the ordered planned stop visits from `schedule_stop_visits` for that exact trip.
5. Compare the vehicle's reported `stop_id` with the planned stops for the same trip.

This resolves examples such as vehicle trip `6656_20260606_118_0_2` to route variant `118_0`, public line `755`, direction `0`, and its complete planned stop sequence. Package IDs are never hardcoded.

Only observed, exactly matched vehicle trips are drawn. The chart therefore answers “which vehicles were recorded driving this line on this operational day?” rather than displaying every theoretical trip in the GTFS package.

## Reading the chart

The visualization is a time–space diagram:

- stops run from left to right;
- Lisbon service time runs from top to bottom;
- each vehicle–trip run has a dashed planned path and a solid reported-stop path;
- selecting a solid path or stop marker reveals the vehicle ID, exact trip ID, route, planned time span, observed time span, and report counts;
- red rings mark possible convergence between two trips;
- direction `0` and direction `1` are separated because their ordered stop sequences run in opposite directions;
- the current map time window is shown initially, with an option to inspect the whole service day.

A physical vehicle may complete multiple trips during one day. Each vehicle–trip pair is therefore a separate run in the chart, while runs belonging to the same vehicle keep the same color.

## Candidate bunching rule

A candidate is reported when two different matched trips:

- report the same scheduled stop within 180 seconds of each other; and
- were planned to reach that stop at least 300 seconds apart.

The endpoint returns both the observed and planned gaps, the two vehicle and trip IDs, direction, route, stop, and report times. These are intentionally described as **candidates**, not confirmed bunching events.

## Interpretation limits

The source vehicle event contains a `stop_id`, but the metadata does not prove that its timestamp is a door-open arrival timestamp. It may describe the current or next associated stop. For that reason:

- the interface says “reported stop evidence,” not “actual arrival”;
- unmatched stop IDs remain counted and visible as a warning;
- missing reports do not imply that a bus skipped a stop;
- route or stop matches are never manufactured from proximity alone;
- candidate convergence should be corroborated with position traces and repeated downstream stops before it is treated as operational bus bunching.

This phase provides the visual evidence needed to investigate headway collapse. A later detection phase can refine the rule using map-matched progress, repeated-stop confirmation, and configurable thresholds.

The separate [precomputed bunching pipeline](PRECOMPUTED_BUNCHING.md) now persists versioned `stop-headway-v1` results and requires evidence at two distinct stops for its normal episode statistics. It still uses reported-stop evidence without interpolation; route-progress reconstruction remains future work.

The Routes tab exposes these stored results through **Week** beside each public line. The modal shows Monday–Sunday episode times and explicitly labels dates where pre-analysis has not been run.

## Replay-map candidates

The replay map evaluates the vehicles visible at the current replay time. A pair is highlighted only when it satisfies the schedule rule above **and** its current reported coordinates are no more than 300 metres apart.

- both vehicle markers receive a red halo;
- a dashed red connector shows the pair's geographic separation;
- the connector midpoint exposes the line, vehicle IDs, reported gap, planned gap, and distance;
- the map status reports the current number of candidate pairs and provides a Show/Hide control;
- candidates update as the replay slider moves or plays;
- clicking either bus still opens its ordinary vehicle Details tab.

The additional distance test is specific to the live map overlay. It prevents two vehicles from being marked on the map merely because they share a reported stop identifier while their coordinates are far apart.

## API

```http
GET /api/lines/{operator_id}/{public_line}/day?date=YYYY-MM-DD
```

The response contains:

- operator, public line, date, and mode;
- one entry per observed vehicle–trip run;
- the complete ordered schedule and matched reported-stop evidence for each run;
- coverage counts and partial-data warnings;
- candidate convergence events and the thresholds used;
- an explicit evidence note for downstream clients.

The endpoint aggregates observations in PostgreSQL and limits a response to 500 matched runs and 50,000 reported-stop groups. Missing plans, trips, stop schedules, or observations produce valid partial or empty responses rather than fabricated matches.
