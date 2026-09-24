# Project 7 data selection

This is the selection contract for Challenge 7. Configuration uses public line codes and event-facing agency IDs. Route IDs, trip IDs, and database package IDs are resolved dynamically and are not stable configuration values.

## Operators and configured lines

| Preset | Event agency ID | Public lines |
| --- | --- | --- |
| CARRIS Lisbon | `IA9T6` | `702`, `703`, `708`, `714`, `717`, `718`, `723`, `726`, `727`, `728`, `729`, `734`, `736`, `742`, `747`, `750`, `751`, `755`, `756`, `758`, `759`, `760`, `765`, `767`, `773`, `774`, `796`, `12E`, `15E`, `28E` |
| Mira-Sintra / Agualva-Cacém | `LA77N` | `1218`, `1219`, `1715` |
| Caneças / Pontinha | `BNA17` | `1709`, `1710`, `1711` |
| Estrada Nacional 10 | `YA15B`, `A2L1N` | `3103`, `3512`, `3116`, `3118`, `3505`, `3508`, `3527`, `3535`, `3536`, `3605` |
| Sesimbra / Quinta do Conde | `YA15B`, `A2L1N` | `3201`–`3213`, `3221`, `3223`, `3536`, `3544`, `3549`, `3625`, `3635`, `3642`, `3650`, `3721`, `4643` |
| MobiCascais | `HF16N` | `M02`, `M13`, `M14`, `M16`, `M22`, `M27`, `M30`, `M31`, `M32`, `M35` |

For Sesimbra, `3201`–`3213` means the explicit codes `3201` through `3213`; the JSON configuration is authoritative. CARRIS `12E`, `15E`, and `28E` are electric tram lines. The other configured CARRIS lines are buses.

Other event operators present in the supplied vehicle data are `7NTB1` (Fertagus), `IA2N9` (Metropolitano de Lisboa), `LTP61` (Soflusa), and `N18KL` (Comboios de Portugal). They are available to the general viewer when their observations exist, but are not default Challenge 7 focus groups.

## Operation-plan coverage

| Event agency | TML plan ID | Stable source directory | Valid from | Valid through |
| --- | --- | --- | --- | --- |
| CARRIS `IA9T6` | `82YP2` | `20260715_IA9T6_CARRIS_82YP2` | 2026-07-15 | 2026-12-31 |
| Area 1 `LA77N` | `XS3H8` | `20260803_LA77N_VIACAO_ALVORADA_XS3H8` | 2026-08-03 | 2026-09-13 |
| Area 2 `BNA17` | `0277F` | `20260803_BNA17_RODOVIARIA_LISBOA_0277F` | 2026-08-03 | 2026-08-31 |
| Area 2 `BNA17` | `JU98X` | `20260901_BNA17_RODOVIARIA_LISBOA_JU98X` | 2026-09-01 | 2026-09-13 |
| Area 3 `YA15B` | `2QDAD` | `20260803_YA15B_TST_2QDAD` | 2026-08-03 | 2026-09-13 |
| Area 4 `A2L1N` | `F1M13` | `20260801_A2L1N_ALSA_TODI_F1M13` | 2026-08-01 | 2026-09-13 |
| MobiCascais `HF16N` | `SBF83` | `20260608_HF16N_MOBICASCAIS_SBF83` | 2026-06-08 | 2026-09-13 |

Validity is inclusive. For example, Area 2 uses `0277F` on 31 August and `JU98X` from 1 September. If a package is not imported, the catalog returns the configured line as unavailable instead of guessing another package.

## Geographic selection

The active vehicle dataset stores five-character geohash areas. The workspace catalog returns every area with observations on the selected date, and the UI enables all of them by default.

The brief's Challenge 7 reference zones are:

| Preset | Geohashes |
| --- | --- |
| CARRIS Lisbon | `eyckpy`, `eyckpw`, `eycs26`, `eyckpq`, `eyckr6`, `eyckrx`, `eyckxb`, `eyckx9`, `eyckqy` |
| Mira-Sintra / Agualva-Cacém | `eycks` |
| Caneças / Pontinha | `eyckw` |
| Estrada Nacional 10 | `eyce8`, `eyceb`, `eyc7z` |
| Sesimbra / Quinta do Conde | `eycdb`, `eycd8` |
| MobiCascais | `eyck1`, `eyck3`, `eyck6`, `eyck4` |

Six-character CARRIS cells are reference overlays. Preset API queries prefilter by their five-character parent and then apply exact latitude/longitude bounds. The unified workspace does not use them as an invisible default restriction.

## API parameters

Start by asking the database what is actually available:

```http
GET /api/workspace-catalog?date=2026-09-01
```

The response contains date-available `areas`, `operators`, date-valid `routes`, validated `presets`, per-line `planAvailable` and `vehicleAvailable` flags, package-scoped `routeKeys`, warnings, and request limits.

Vehicle history uses `GET /api/observations` with these parameters:

| Parameter | Required | Meaning |
| --- | --- | --- |
| `date=YYYY-MM-DD` | yes | Lisbon operational/calendar date used for the query and plan selection |
| `start=HH:MM` | yes | Lisbon local start time |
| `end=HH:MM` | yes | Lisbon local end time; may cross midnight |
| `area=<geohash5>` | yes, repeated | One or more areas returned by the catalog |
| `operator=<agency_id>` | yes, repeated | One or more available event agencies |
| `line=<public_code>` | optional, repeated | Exact public-line restriction using the date-valid trip mapping |

The window must be nonempty and at most four hours. The API includes 120 seconds of prehistory for replay continuity and refuses responses above 200,000 rows rather than truncating them.

Supplying one or more `line` values returns only exact, date-valid matched trips for those public lines. Omitting every `line` means **All vehicles**: matched routes, other routes, and unresolved trip IDs are retained for the selected operators and areas.

Example for CARRIS lines 755 and 28E in two catalog areas:

```sh
curl --get 'http://127.0.0.1:8000/api/observations' \
  --data-urlencode 'date=2026-09-01' \
  --data-urlencode 'start=07:00' \
  --data-urlencode 'end=09:00' \
  --data-urlencode 'area=eyckp' \
  --data-urlencode 'area=eycs2' \
  --data-urlencode 'operator=IA9T6' \
  --data-urlencode 'line=755' \
  --data-urlencode 'line=28E'
```

Use area values returned for the requested date; the two values above are an example, not a universal CARRIS boundary.

## Route overlays are separate

Route selection never changes a vehicle query. The workspace uses package-scoped keys returned by the catalog and loads geometry in a batch:

```http
POST /api/plans/routes-geometry
Content-Type: application/json

{"route_keys":["<package_id>:<route_id>"]}
```

The numeric package component is returned by the current database and must not be stored in configuration.

## Matching examples

In the CARRIS plan currently used for 1 September 2026:

- public line `755` resolves to internal route `118_0`;
- `12E` resolves to `77_0`;
- `15E` resolves to `76_0`;
- `28E` resolves to `75_0`;
- trip `6656_20260606_118_0_2` resolves by exact trip ID to route `118_0`, hence public line `755`.

These examples are verification facts, not configuration. A later plan may use different internal route or trip IDs while keeping the same public line code.

## Backward-compatible parameters

The observations endpoint still accepts `preset_id`, repeated `focus_line`, and `include_context`, plus the older `schedule_mode`, `route_id`, and `direction_id` controls. New workspace code should prefer explicit repeated `area`, `operator`, and optional `line` parameters because they make the query boundary visible and keep presets independent from route overlays.
