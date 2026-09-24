"""
What-if simulator for interventions.

Owner:  E
Input:  real headways, travel/dwell times
Output: sim_results (before/after KPIs)

TODO
  [ ] calibrate(): travel time per segment/hour, dwell from stationary pings
  [ ] simulate(policy): buses move stop to stop, dwell grows with headway
  [ ] policies: none, holding at control stops, bus lane speed-up, express
  [ ] compare(): bunch rate, headway CV, excess wait time before vs after
"""
