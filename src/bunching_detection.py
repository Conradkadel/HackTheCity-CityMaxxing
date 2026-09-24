"""
Detect bunching from GPS pings.

Owner:  A
Input:  pings + GTFS
Output: stop_passages, headways, bunching_events, kpis

TODO
  [ ] stop_passages(): time when stop_id (next stop) switches = bus passed the stop; skip layover rows
  [ ] headways(): leader = previous bus same line/direction/stop/day; scheduled headway from GTFS (fallback: typical observed)
  [ ] headway_ratio + flags (bunched < 0.25, gap > 1.5)
  [ ] bunching_events(): group bunched passages into leader/follower episodes, start stop
  [ ] kpis(): bunch rate, headway CV, excess wait time per corridor/line/stop/hour
  [ ] causes(): late terminal departure, long dwell, slow segment, Waze jam (Lisbon only)
"""
