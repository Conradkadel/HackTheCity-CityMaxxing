# Dataset design – Challenge #7 (bus bunching)

*24 Sep 2026. Every claim below is backed by a check you can re-run with `code/analysis/dataset_evidence.py` (from the challenge folder) or `code/notebooks/03_bunching_deep_eda_and_model.ipynb`. Numbers marked **[E-x]** refer to the evidence list in §7.*

---

## 0. The answer in one paragraph
Bunching is a relation between **two buses at the same stop**, so the dataset must not be a pile of GPS pings. It has **stop passages** at its centre: one row per bus per stop, enriched with its schedule, its leader and the headway. Around that sit small dimension tables (stops, trips/patterns, lines→corridors, day periods), plus two context tables (zone coverage, Waze). The modelling table comes out of the passages. Raw pings are kept only as a cleaned layer for the map replay and to derive passages. About 60 % of the raw columns and most GTFS/Waze columns are dropped, each for a demonstrated reason.

```
 raw CSV (20M rows, 12 cols)            GTFS x4 plans         Waze          calendario
        │ clean + dedup (§2)                 │                  │               │
        ▼                                    ▼                  ▼               ▼
 silver.pings  ──derive──►  gold.stop_passages  ◄── dim_trip / dim_pattern_stop / dim_stop / dim_line
 (replay only)                    │   (+ leader, headway, sched headway, delay)
                                  ├──► gold.bunching_events        (episodes, for UI & KPIs)
                                  ├──► ml.onset_pairs               (model table, §4)
 silver.zone_coverage ◄───────────┘    context.waze_zone_slot (Lisbon only)   dim_period
```

---

## 1. Why the grain is the stop passage, not the ping (proof)
| Test | Result | Consequence |
|---|---|---|
| Ping-level "headway" (LAG over pings at same stop & line, as in `treinar_modelo_bunching.py`) | **89.4 %** of rows are labelled bunched, and **98.9 %** of those positives are the **same bus pinging twice** [E-D2] | A ping-level label measures the GPS ping rate, not bunching. Its ROC-AUC of 0.84 is meaningless. |
| Ping-level events with a different bus (as in `processar_filtros_backend.py`) | 11,104 "CRÍTICO" rows = **957** real bus pairs; 93 % are A-B-A-B interleaving [E-D3] | One episode is counted about 12×. Headways must be taken between **passages**, and episodes deduplicated. |
| Ping cadence | CM median 10 s (2–60 s); 24 % of pings are stationary [notebook §2] | Pings are irregular and redundant. A stop passage is the natural, regular event. |
| Passage timing precision | gap between the last "old next-stop" ping and the first new one: median 8 s, p95 15 s (CM); ≈30 s for Carris [E-D4] | Headways are accurate to ±15 s, which is good enough for a 2-minute bunching threshold. |
| Control actions (holding, alerts) | happen at stops | The prediction unit is naturally "bus *i* at stop *k*". |

Passages are derived from the **next-stop semantics of `stop_id`**: when it changes, the bus has just served the previous stop (the distance to `stop_id` shrinks in 94 % of segments).

---

## 2. Cleaning pipeline – ordered, each step justified
| # | Rule | Evidence | If you skip it |
|---|---|---|---|
| 1 | Read **all IDs as strings** (`all_varchar` / `dtype=str`) | `stop_id` has leading zeros ("020317"); `driver_id` is inferred as VARCHAR in one file and BIGINT in another [raw check] | Joins to GTFS fail silently and type drift appears across files. |
| 2 | Keep bus agencies only: LA77N, BNA17, YA15B, A2L1N, IA9T6, HF16N | N18KL/7NTB1 (trains) have 100 % null `stop_id`; IA2N9 (metro) stop codes are letters (RA, SS…) [E-A1] | Trains and metro create false "buses". |
| 3 | `UNAVAILABLE_STOP_ID` → null | **80,258** rows (CM only) [E-A2]; 1.7 % of current passages are fake passages at this "stop" | Every drop-out creates two fake passages. |
| 4 | **De-dup on (agency_id, vehicle_id, created_at), keep the LAST `received_at`, and prefer a copy with a real stop_id** | 31 % of rows are re-sends; within duplicate groups, copies **disagree** on stop_id in 5–11 % of groups and on position in 10–28 % [E-A4]. The last-received copy matches the neighbouring pings 74–77 % of the time vs 61–69 % for the first | The current `prep.py` keeps the *first in file order*, which is effectively random. |
| 5 | Key = **(agency_id, vehicle_id)**, never vehicle_id alone | **343** vehicle_ids are used by more than one agency [E-A3] | Two different buses get merged into one track. |
| 6 | Trip key = **(operational_date, trip_id)** | 45.6 % of trip_ids repeat on several days (they are timetable ids) [E-D1] | Leaders and passages leak across days. |
| 7 | Drop GPS jumps > 120 km/h | 0.16 % of pings | Spurious passages and speed spikes. |
| 8 | Remove terminal waiting: Carris `stop_id` null (3.3 %), MobiCascais/CM stationary pings at the first stop before departure | Carris null stop_id = layover [team finding #14] | False "departures" and fake bunching at terminals. |
| 9 | Build passages; then **drop repeated (date, trip, vehicle, stop)** – keep the last one | 5.9 % of passages were repeats caused by stop_id flicker [notebook §3] | Same-trip "headways" of about 2 minutes. |
| 10 | Drop passages where the time between the two pings used is > 120 s | 2 % are geofence exit/re-entry [E-D4] | Passage time is unknown by up to several minutes. |
| 11 | Pair buses only when **both** were observed at that stop | Trip coverage median 73 %; missingness depends on corridor/day (Cramér's V 0.28–0.33), not on hour (V ≈ 0.01) | An unobserved bus looks like a big gap, followed by a fake bunch. |

---

## 3. Tables

### 3.1 `silver.pings` (replay + passage derivation only; ≈12.5 M rows all agencies, ≈1.2 M on CM corridors)
| column | type | from | keep why |
|---|---|---|---|
| agency_id | str | raw | part of every key [E-A3] |
| vehicle_id | str | raw | track identity |
| operational_date | int | raw | partition key. It is derivable (created_at − 5 h matches 100 %), but it is free and it removes timezone bugs |
| ts | int64 ms UTC | raw `created_at` | the GPS time; all ordering uses this |
| lat, lon | float32 | raw | float32 ≈ 1 m precision is enough |
| trip_id | str | raw | → dim_trip |
| next_stop_id | str / null | raw `stop_id` after rule 3 | passage derivation |
| status | enum | derived | `moving` / `layover` / `off_route` for the replay |

**Dropped:** `_id` (unique hash per row, no information; see rule 4 for the real key), `received_at` (only for the latency statement: CM ≈ 2 s, Carris ≈ 33 s; keep one summary number in `meta.json`), `driver_id` (personal data; 1.5 % of trips change driver mid-trip; no use for bunching that we can defend), `geohash_5` (recomputing it from lat/lon matches **100 %**; it only records which file the row came from).

### 3.2 Dimensions
**`dim_trip`** – grain (agency_id, trip_id)

| column | source | note |
|---|---|---|
| line_id, pattern_id | **parsed from trip_id** | trip_id starts with pattern_id in **100 %** of GTFS trips in all 4 plans [GTFS check]. This also works for trips with no timetable (3103/3116) |
| direction_id, shape_id, block_id | GTFS trips | pattern-token-based direction agrees only 85–98 % → take it from GTFS, parse only as a fallback |
| day_type | **trip_id suffix** (7/8/9, VER_DU/SAB/DOM) | ⚠️ *not* from calendar_dates: plan 41 says Sat = service 5 and Sun = 6, but the buses ran service **8** and **9** [E-B2] |
| has_schedule | bool | false for 3103, 3116, 3650, Carris, MobiCascais |
| sched_start_ts | GTFS first departure | |

**`dim_pattern_stop`** – grain (pattern_id, stop_sequence): stop_id, **shape_dist_traveled** (monotonic in 100 % of trips → distance-based speed and holding), sched offset. `arrival_time` is dropped because it equals `departure_time` in **~100 %** of rows. Parse times ≥ 24:00 (2–3 % of rows) as seconds from service-day midnight.

**`dim_stop`** – stop_id, name, lat, lon, municipality, `is_shared` (served by ≥ 2 corridor lines), `is_terminal`. **23 of the 30 columns in stops.txt are empty or constant** [E-B3], so they are dropped. 536 stop_ids appear in several plans with slightly different coordinates → take the most common one.

**`dim_line_corridor`** – line_id → corridor (from the challenge brief), agency, colour (routes.txt).

**`dim_period`** – from calendario sheet `periodos_dia` (PPM, PM, CM…): for charts only. The `calendário` sheet's day_type duplicates the trip_id suffix for our week, so it is used only as a cross-check.

### 3.3 `gold.stop_passages` – **the core table** (≈154 k rows on the CM corridors; `_processed/passages_v2.parquet` is a first version)
Grain and PK: **(operational_date, agency_id, trip_id, vehicle_id, stop_id)**, which is unique after rule 9.

| column | how | why it's needed |
|---|---|---|
| ts_pass | midpoint of the last old / first new next-stop ping | ±8 s instead of ±15 s |
| stop_sequence, dist_m | dim_pattern_stop | position along route: deviation grows from 0.12 to 0.17 along the route |
| sched_ts, delay_s | GTFS | leader-late / follower-early is the mechanism (65 % / 45 % of bunched pairs) |
| leader_trip, leader_vehicle, headway_s | previous passage, **same pattern**, same stop and date | line-level bunching |
| sched_headway_s, headway_ratio | from the two trips' schedules | the definition that doesn't depend on observed data (the observed-median reference overstated Sesimbra) |
| any_leader_line, headway_any_s, sched_headway_any_s | previous passage of **any corridor line** at the stop | **~75 % of arrivals less than 1–2 min apart involve two different lines** (ours 75 %, team 77 %), and ~half of them are planned ≤ 5 min apart |
| prev_trip_end_delay_s, sched_layover_s | same (agency, vehicle), previous trip | 52 % of late starts (> 5 min) are inherited from the vehicle's previous trip |
| is_timepoint | GTFS | ⚠️ usable **only for plan 43**: plan 41 has timepoint = 1 on 100 % of stops and plan 42 has 0 % [E-B1] |
| quality flags | `leader_observed`, `ts_uncertainty_s`, `has_schedule` | lets you filter instead of silently mixing |

### 3.4 `ml.onset_pairs` – model table (derived; ≈91 k rows, ≈1 % positive)
One row = follower passage at stop *k* with its same-pattern leader, **only if the pair is not bunched yet** (ratio ≥ 0.5) and both buses were observed.
- **Label:** min(headway_ratio) around stop *k+10* < 0.5. At H = 10 the model gains most over persistence: PR-AUC 0.40 vs 0.31.
- **Features:** use only information known at ts_pass: ratio, headway, scheduled headway, follower and leader delay, leader−follower delay gap, 3-stop trends, stops left, hour, dow, line, prev_trip_end_delay, layover.
- **Split:** by **day**. A random split mixes neighbouring stops of the same pair between train and test (the headway ratio correlates 0.97 three stops ahead).
- **Always report against persistence** (current ratio). It is a strong baseline.
- Planned second table `ml.onset_pairs_corridor`: same logic with the any-line leader, which has about 10× more positives.

### 3.5 Context tables
**`silver.zone_coverage`** – geohash5 × date × hour → n_pings, n_vehicles. Needed so that the UI and KPIs can say "no data" instead of "no bunching": eyckp/eyckx have only 1 day, eyckw 4, and Tuesday is thin.

**`context.waze_zone_slot`** (Lisbon only) – geohash6 × date × 15 min: n_jams, jam_length_m, mean_delay_s, n_blocked.
- **Keep:** geohash6 (split `"eyckpw / eyckpy"` labels, 3 variants), data+Hora+Minuto → ts, atraso, comprimento, velocidade_kmh, one geometry column.
- **Drop:** `velocidade` (= kmh / 3.6, 100 %), `geo` (= geowkt, 99.4 %), `cidade` (constant "LISBOA"), `zona` (1:1 with geohash6), `localizacao_dicofre`.
- ⚠️ **Do not use `nivel_de_intensidade`.** The labels are **reversed**: "Estrada bloqueada" rows have median speed 25 km/h and positive delay, while "80–61 %" rows have 0 km/h and delay = −1 (the blocked sentinel) [E-C4]. Recompute the level from speed/delay if you need it.
- ⚠️ Waze is **sparse**: median **44 of 1,440 minutes** per zone-day have any record [E-C5]. After controlling for zone × hour, its partial correlation with bus speed is ≈ 0 (notebook §6). Use it as a map layer and trigger explanation, not a core feature.

---

## 4. Keep / drop – every source, every field
| Source | KEEP | DROP (reason) |
|---|---|---|
| vehicles | agency_id, vehicle_id, created_at→ts, lat, lon, trip_id, stop_id→next_stop_id, operational_date | `_id` (row hash); `received_at` (latency number only); `driver_id` (privacy, no defended use); `geohash_5` (100 % derivable) |
| GTFS trips | trip_id, route_id, pattern_id, direction_id, block_id, shape_id | service_id (use the trip_id suffix), shift ids, headsign (UI only), demand, calendar_desc |
| GTFS stop_times | trip_id, stop_id, stop_sequence, departure_time, shape_dist_traveled, timepoint (plan 43 only) | arrival_time (= departure), pickup/drop_off_type, continuous_* |
| GTFS stops | stop_id, name, lat, lon, municipality | 23 empty/constant columns |
| GTFS routes | line_short_name, long_name, color | fares, contract, sort order |
| GTFS calendar_dates | – | doesn't cover the week (plans 42/43/44 end ≤ 30 Jun 2026) and is **wrong** for 41 at weekends |
| GTFS shapes | shape_id, points | map only |
| GTFS layovers | block_id, start/end, location | optional: *scheduled* layover per block (plans 41/42/43; missing in 44) |
| GTFS blocks, dead_runs | – | vehicle specs per *scheduled* block (seats 37 / standing 52), but no link to the vehicle that actually ran, so no reliable capacity |
| fare_*, agency, feed_info, resources | – | irrelevant |
| Waze | see §3.5 | see §3.5 |
| calendario | periodos_dia | calendário day_type (duplicate of trip suffix) |

---

## 5. What in the current team code must change (proven)
1. `analysis/treinar_modelo_bunching.py`: the label is wrong (98.9 % of positives are the same bus), there is no future horizon (it predicts the present), and it uses a random split. **Replace it with `ml.onset_pairs`.**
2. `analysis/processar_filtros_backend.py`: ping-level headways inflate events about 12× and there is no date in the window partition. Build headways from `gold.stop_passages`, and turn episodes into `bunching_events`.
3. `analysis/processar_dados.py`: loads raw CSVs with no de-dup (31 % re-sends in the tested file), keeps trains/metro/ferry, and uses `ignore_errors=true` (it dropped 0 rows in the files tested, but it hides future errors). Read ids as strings and add rules 2–6.
4. `_processed/prep.py`: de-dup keeps the first copy in file order → switch to last-received with the real-stop preference.
5. Team finding #10 ("timepoints bunch more") only holds for plan 43, where timepoint means something (§3.2).

---

## 6. Limits we should state openly
- One summer week, 5 weekdays → about 430 same-line onsets. The model will be modest; the corridor-level table gives more positives.
- There is no timetable for 3103/3116/3650, Carris and MobiCascais. For those lines the reference is the observed headway and it is flagged `has_schedule = false`. Ask TML for the Sept-2026 GTFS and the Carris GTFS.
- Passages exist only inside the geofenced boxes, so "no data" is not "no bunching".
- No passenger or load data, so passenger impact is only an estimate (Excess Wait Time from headways).

## 7. Evidence index (output of `dataset_evidence.py`)
- **E-A1:** trains N18KL/7NTB1 have 100 % null stop_id; metro IA2N9 stop codes are all non-numeric.
- **E-A2:** 80,258 `UNAVAILABLE_STOP_ID` values.
- **E-A3:** 343 vehicle_ids are shared across agencies.
- **E-A4:** 31.4 % re-sends in eycks 2 Sep; 5.1 % of duplicate groups conflict on stop_id and 10.5 % on position (11 % / 28 % in eyce8).
- **E-B1:** timepoint = 1 share per plan: 43 → 0.071, 44 → 1.0, 41 → 1.0, 42 → 0.0. Times ≥ 24h: 2–3 %. arrival ≠ departure: ≤ 0.02 %.
- **E-B2:** plan 41 calendar lists Sat = 5 and Sun = 6; observed suffixes are 8 (3,127 pings) and 9 (2,687).
- **E-B3:** stops.txt has 23 of 30 columns empty or constant.
- **E-C1–C3:** velocidade×3.6 = kmh (100 %); geo = geowkt (99.4 %); cidade constant.
- **E-C4:** reversed intensity labels (table in §3.5).
- **E-C5:** 4–133 (median 44) minutes with data per zone-day.
- **E-D1:** 45.6 % of trip_ids appear on more than one day.
- **E-D2:** ping-level label is 89.4 % positive, and 98.9 % of those positives are the same bus.
- **E-D3:** 11,104 ping-level events = 957 bus pairs.
- **E-D4:** passage uncertainty median 8 s, p95 15 s; 2 % above 120 s.
