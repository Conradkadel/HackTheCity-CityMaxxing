# Typical traffic on routes

Select planned routes in **Routes**, then turn on **Typical traffic** above the
map's area selector. Selected route sections change from route colours to a
yellow–orange–red congestion scale. Grey dashed sections have no matched Waze
evidence. Hover a section for its speed estimate, report count and days with
reports. Switch the filter off to restore route colours.

The first version uses **all imported Waze dates and all hours**, independently
of vehicle replay and its analysis window. The legend shows the actual source
date range, days containing reports and percentage of selected shape length
with matches. This is typical *reported congestion*, not a live traffic layer
or an estimate of how often the road is congested. Waze jam data alone cannot
establish free-flow conditions when no report exists.

## Calculation

`POST /api/traffic/routes` accepts `{"route_keys":["<package>:<route>"]}` (1–100
routes). It returns route sections, evidence counts, coverage and method
`daily-mean-reported-speed-band-v1`. The backend matching module is independent
of Leaflet and can be reused when adding traffic to time–space diagrams.

- Parse the imported Portuguese speed-relative-to-free-flow bands using their
  midpoints: 70.5%, 50.5%, 30.5%, 10.5%; blocked-road reports contribute 0%.
  Unknown labels or unsupported geometry are excluded and counted in the UI.
- Split route geometry into pieces at most 25 metres long. Match each midpoint
  to Waze LINESTRING geometry within 25 metres and with local alignment within
  30 degrees. Use a metric grid index and a local Lisbon projection. Reversed
  geometry order is accepted; travel direction is not inferred.
- Within each piece, combine matching reports into a mean for each reported
  day, then average those daily means equally. Days without reports are not
  filled with zeros. Each Waze geometry contributes once per route piece, even
  if several of its edges match. Report counts are local to each section and
  must not be summed across adjacent sections.
- Colour the mean speed ratio: above 60% light, above 40% moderate, above 20%
  heavy, and 0–20% very heavy. An average including historical closures is not
  a claim that the road is currently closed. Speed in km/h is supplementary;
  it does not determine colour.
- Stop-to-stop fallback shapes have no road match. Missing routes, query
  failures, empty imports and unrecognized observations are explicit states.

This proximity match can still confuse close parallel roads, carriageways or
roads at different elevations. It is not a directed road-network match.
Repeated jam reports are not independent traffic samples. Coverage is measured
over selected shapes, so overlapping route variants count separately.

Queries use a consistent read-only snapshot and a 30-second SQL timeout. More
than 100,000 grouped geometry/day/intensity records returns an explicit error,
without silently truncating history. Larger archives should use precomputed
spatial summaries. No database migration or reimport is required.

After changing the backend, rebuild the local API with
`docker compose up -d --build api`. Frontend development uses `npm run dev`.

## Time–space diagrams

Both **Analyze line** and the **Bunching** diagram have a **Typical traffic by
time of day** checkbox. It softly shades the area between consecutive stops
only where the average reported speed band is heavy (at most 40% of free-flow
speed) or very heavy (at most 20%). Vehicle paths and bunching markers stay on
top. Hover the background for the stop pair, local time band, report count,
days with evidence and percentage of the section matched. Single-day evidence
is paler and explicitly labelled. Unshaded areas can have lighter traffic or
no evidence; missing reports are never treated as free flow.

Unlike the all-hours map filter, this overlay groups reports into **30-minute
Europe/Lisbon clock-time bands across all imported days**. The selected service
date chooses the valid plan; it does not restrict traffic history. Absolute
chart timestamps select the corresponding local band, including after midnight
and during daylight-saving changes. Reports in the repeated autumn hour share
the same local-time band. Weekdays and weekends are pooled.

`POST /api/traffic/diagram` accepts `date`, `agency`, `line`, and `direction`.
Optional `package_id` and `trip_id` must be supplied together to select the exact
trip used as the Analyze line chart's stop axis. Otherwise the longest planned
trip of the line/direction is used, matching the Bunching diagram's reference
route. Other lines in a corridor use that primary route's background.

Stops are projected in order onto the trip's actual GTFS shape, with a maximum
stop-to-shape distance of 100 metres. Missing shape geometry is not replaced by
straight stop-to-stop lines. Each section is sampled in pieces of at most 25
metres and matched with the same proximity/alignment rules as the map. Within
each time band, report-weighted piece means are length-weighted over the matched
part of each day's section, then those daily means are averaged equally.
Coverage measures the union of matched section length across reported days.
Reports are counted once per stop section/time band even if their road geometry
matches multiple pieces. Missing days and unmatched lengths are excluded rather
than imputed. Repeated stop pairs use sequence numbers where available; ambiguous
or non-adjacent pairs are not assigned evidence from another section.

This is historical context for examining whether bunching follows a congested
section. It does not prove congestion on the selected day or establish causation,
and it does not alter bunching detections, predictions or simulations.
