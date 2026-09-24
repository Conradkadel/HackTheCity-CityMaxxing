"""
API smoke tests on MOCK data (needs a LOCAL Postgres, see BACKEND.md "Run").

    pytest -q backend/test_api.py          (run from the code/ folder)

The fixture re-creates the mock tables with backend/mock_data.py (it refuses to touch
a DB with real data), then every route is called once. FastAPI validates each response
against its response_model (schemas.py), so a 200 also means "matches the contract".
"""
import pytest
from fastapi.testclient import TestClient

from backend import mock_data, services
from backend.main import app

C, D, T0 = "mira_sintra", mock_data.DATE, mock_data.T0_MS
MIN = 60_000


@pytest.fixture(scope="module")
def client():
    try:
        mock_data.main()
    except SystemExit as e:              # real data in the DB -> never overwrite
        pytest.skip(str(e))
    except Exception as e:               # no Postgres -> skip instead of many red tests
        pytest.skip(f"Postgres not reachable ({e})")
    services.get_meta.cache_clear()
    services.get_network.cache_clear()
    return TestClient(app)


def get(client, path, **params):
    r = client.get("/api/v1" + path, params=params)
    assert r.status_code == 200, r.text
    return r.json()


# ---------- system & network ----------
def test_health_and_meta(client):
    assert get(client, "/health")["status"] == "ok"
    m = get(client, "/meta")
    assert m["dates"] == [D] and m["thresholds"]["critical_s"] == 90


def test_corridors(client):
    assert C in [c["corridor_id"] for c in get(client, "/corridors")]
    assert get(client, f"/corridors/{C}")["summary"]["n_events"] > 0


def test_network_and_coverage(client):
    feats = get(client, f"/network/{C}")["features"]
    assert {f["properties"]["kind"] for f in feats} == {"line", "stop", "zone"}
    stop = next(f for f in feats if f["properties"]["kind"] == "stop")
    assert stop["properties"]["stop_id"].startswith("0")        # leading zero kept
    assert all(z["covered"] for z in get(client, f"/coverage/{C}", date=D))


# ---------- replay ----------
def test_replay(client):
    r = get(client, "/replay", corridor=C, date=D, from_ts=T0, to_ts=T0 + 30 * MIN)
    v = r["vehicles"][0]
    assert len(v["path"]) == len(v["timestamps"]) == len(v["status"])
    statuses = {s for v in r["vehicles"] for s in v["headway_status"]}
    assert "bunched" in statuses                                 # injected episode is visible
    f = get(client, "/replay", corridor=C, date=D, from_ts=T0, to_ts=T0 + 5 * MIN, format="frames")
    assert f["frames"] and isinstance(f["frames"][0]["vehicle_id"], str)


def test_replay_window_too_large_is_422(client):
    r = client.get("/api/v1/replay", params={"corridor": C, "date": D, "from_ts": T0, "to_ts": T0 + 31 * MIN})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_param"


def test_vehicle_track_and_alerts(client):
    ev = get(client, "/events", corridor=C, date=D, limit=1)["items"][0]
    track = get(client, f"/vehicles/{ev['follower_vehicle']}/track", date=D)
    assert track["frames"] and track["events"]
    alerts = get(client, "/alerts", corridor=C, date=D, ts=ev["ts"], window_s=60)
    assert alerts and alerts[0]["action"]["type"] == "hold"


# ---------- analysis ----------
def test_events_kpis_heatmap_hotspots(client):
    page = get(client, "/events", corridor=C, date=D, severity="critical", limit=5)
    assert page["total"] > len(page["items"]) == 5
    assert {r["group"] for r in get(client, "/kpis", corridor=C, group_by="line")} == {"1715", "1218"}
    h = get(client, "/heatmap", corridor=C)
    assert len(h["values"]) == len(h["stops"]) and len(h["values"][0]) == len(h["hours"]) == 24
    assert get(client, "/hotspots", corridor=C, top=3)[0]["rank"] == 1


# ---------- live model ----------
def test_live_buses(client):
    r = client.get("/api/v1/buses/live", params={"linha": "1715"})
    assert r.status_code in (200, 503)                           # 503 = modelo_bunching.pkl not found


# ---------- errors ----------
def test_errors(client):
    r = client.get("/api/v1/corridors/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    r = client.get("/api/v1/kpis", params={"corridor": C, "group_by": "banana"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_param"
    r = client.get("/api/v1/coverage/" + C, params={"date": "2020-01-01"})
    assert r.status_code == 422
