# Findings: where, when and why buses bunch, and what to change

The **Findings** tab is the first thing the app shows. It answers the operator's question directly, without needing the tool:
*on these lines, from this terminal, in these hours, buses bunch every weekday, for this reason, and this is the change that fixes it.*

The **Risk prediction**, **Simulation** and **Explore data** tabs are the evidence behind it and the tools to follow it up.

## How it is built

```sh
cd code/prototype/backend
../.venv/bin/python build_findings.py --passages <passages_line.csv.gz>   # ~1 min, no database -> models/findings.json
docker compose -p project7-prototype up -d --build   # the API image must include the new file
```

| Input | Made by |
| --- | --- |
| `models/experiments/passages_line.csv.gz`: every CARRIS stop passage of the week (1.15 M) | `export_passages.py` |
| `models/simulator_validation.json`: held-out results of every timing change | `validate_simulator.py` |
| `models/stop_coords.json`: approximate stop positions from GPS (fallback only) | `build_findings.py --vehicles <folder>` |

`GET /api/findings` serves `findings.json`. Stop names and exact positions are added from the plan tables in the database; without the database, stops show their ids.

## What it shows

| Question | How it is measured |
| --- | --- |
| **Which lines** | Share of all weekday bunched passages per line and direction. 5 lines (742, 767, 728, 727, 758) carry 41 % of bunching but only 17 % of stop visits. |
| **When** | Bunching rate per line, direction and hour, and per weekday. A *problem slot* is a line + time block with at least 2× the network rate on **all 5 weekdays**. There are 11 of them, and they hold 19 % of all weekday bunching. The outlined hours are those at ≥ 2× on at least 4 of 5 weekdays. |
| **Where** | The terminal each problem trip starts from, and the 5 stops with the highest bunching rate that bunch on 5/5 weekdays. The map colours the route stop by stop. |
| **Why** | Gap to the bus in front when the trip left the terminal. Trips that leave with < 50 % of the planned gap bunch 68 % of the time (4.6 % when on plan). The 11 % of trips that leave with < 80 % cause 59 % of bunching. |
| **Cause per line** | The simulator's held-out recommendation where one exists (5 lines, 16–20 h). Otherwise a data rule: "turnaround too short" if the share of trips starting after a > 5 min late previous trip is ≥ 1.5× the network; "leaves too close" if the share of departures below 80 % of the planned gap is ≥ 1.3× the network; else "gaps open on the road". |
| **What to change** | Wait for a proper gap at the terminal (backend code D2), 2 more minutes of break at the terminal (T2-2) or short holds mid-route on early warning (M-90). Each has a **Simulate** button that opens the *Simulation* tab on that line, in its problem hours, on a held-out weekday (Fri 4 Sep), and runs it. |
| **Between lines** | Two lines that share ≥ 5 stops "run together" when their buses pass the same stops < 60 s apart for ≥ 3 stops in a row. This happens about 1,086 times per weekday, and in 28 % of the cases the timetable already has them < 2 min apart. The fix is to offset the two timetables on the shared stretch. |

## Limits

- One week of data (31 Aug – 6 Sep 2026), one operator (CARRIS). "Every weekday" means 5 of 5 weekdays in that week.
- Impact is in seconds of excess wait per passenger, because passenger loads are not in the data.
- The tested impacts come from the simulator's validation window (16–20 h). Other hours are flagged *not simulated yet*.
- Driver breaks are not modelled, so the turnaround and dispatch changes may be harder in practice than shown.
