# Data findings (tests run 24 Sep) – what we must not miss

Scope: CM corridors (Mira-Sintra, Caneças, EN10, Sesimbra) 31 Aug–6 Sep, 164k stop passages; 98k matched to the timetable.
Carris × Waze test: 35.7k Carris stop passages in the 7 Lisbon Waze zones.

| # | Finding | Number | Consequence |
|---|---|---|---|
| 1 | Definition decides the result | vs typical observed headway 5–9 % bunched; vs timetable (same line) **1.1 %** | State the definition, make it configurable, show both |
| 2 | Bunching is mostly **between different lines** | **77 %** of buses arriving < 60 s apart at the same stop are different lines; only 21 % of those are planned that way in the timetable | Corridor-level view is the main story; line-by-line analysis misses most of it; timetable coordination is an intervention |
| 3 | A **late leader** triggers it | leader > 10 min late → 6.6 % bunched; leader 5–10 min → 1.2 %; leader on time → ~0 % | Leader delay = top ML feature; holding the follower is the natural fix |
| 4 | It **grows along the route** | first 40 % of stops 0.6 % → last 40 % 1.6 % | Put holding / control points early–middle of route |
| 5 | Only **frequent** service matters | scheduled headway ≤ 15 min: 4–5 %; ≥ 30 min: < 0.5 % | Focus lines like 1715, 1709; skip 2-trips/day Sesimbra lines |
| 6 | **Evening peak** is worst | 19–21 h ≈ 2.8 %, 6–7 h ≈ 1.5 %, midday ≈ 0.2 %; Mon–Wed highest, Sunday lowest | Demo the evening peak |
| 7 | Once bunched it **stays** bunched | 80 % still bunched 3 stops later | Prevention ≫ cure → prediction is valuable |
| 8 | A simple threshold misses most onsets | 57 % of new bunching had ratio ≥ 0.5 three stops earlier | ML has room to beat the baseline |
| 9 | **Few positive labels** | only 433 same-line bunching onsets in the week | Use corridor-level label and/or ratio < 0.5 to get more positives; don't over-promise |
| 10 | Timepoint stops bunch more | 1.6 % vs 0.5 % (48 % of stops are timepoints) | Check: timepoints = busy stops → candidate holding points |
| 11 | Overtaking is rare | 0.3 % of passages | Order by actual time is safe; handle the edge case |
| 12 | "Missing trips" ≠ cancellations | 1218/1219: ~10 scheduled trips/day unseen but ~10 unscheduled seen = timetable changed; 1709/1710 on Thu 3 Sep 8–15 % missing | Only flag cancellations when no replacement trip; gaps cause bunching behind them |
| 13 | Waze jams relate to Carris bunching – weakly | zone-hours w/o jams 3.3 % → with jams 4.6–5.4 %; Spearman 0.22 (0.12 within zone, 0.21 with previous-hour jams) | Useful feature in Lisbon, not the headline; confounded by hour |
| 14 | Missing fields have meaning | Carris null stop_id = layover at terminal; driver_id missing per operator | Status "layover"; terminal departure delay feature |
| 15 | Coverage | geofenced squares, some days missing, no schedule for 3103/3116/Carris/MobiCascais | Never show "no data" as "no bunching" |
