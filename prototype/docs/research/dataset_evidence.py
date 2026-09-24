"""
Reproducible evidence for DATASET_DESIGN.md  (run from the challenge folder:
    python code/prototype/docs/research/dataset_evidence.py )
Every number quoted in the design doc comes from one of these checks.
Needs: duckdb, pandas, pyarrow. Runtime ~1-2 min on a laptop.
"""
import duckdb, pandas as pd, numpy as np, glob

con = duckdb.connect(); con.execute("PRAGMA threads=4")
V = "read_csv('vehicles/*/*/1.csv', header=true, all_varchar=true)"
PLANS = sorted(p for p in glob.glob('operation-plans/*') if not p.endswith('.docx'))
def R(p, t): return f"read_csv('{p}/{t}.txt', header=true, all_varchar=true)"
def say(k, v): print(f"{k:<70} {v}")

print("\n=== A. RAW VEHICLE EVENTS ===")
say("rows per agency / null stop_id / non-numeric stop_id",
    con.execute(f"""select agency_id, count(*) n,
        sum(case when stop_id is null then 1 else 0 end) stop_null,
        sum(case when stop_id is not null and not regexp_matches(stop_id,'^[0-9]+$') then 1 else 0 end) stop_non_numeric
        from {V} group by 1 order by 2 desc""").df().to_dict('records'))
say("placeholder tokens in stop_id (top)",
    con.execute(f"select stop_id, count(*) from {V} where stop_id='UNAVAILABLE_STOP_ID' group by 1").fetchall())
say("vehicle_id values used by >1 agency (=> key needs agency_id)",
    con.execute(f"select count(*) from (select vehicle_id from {V} group by 1 having count(distinct agency_id)>1)").fetchone()[0])

f = 'vehicles/eycks/20260902/1.csv'
d = pd.read_csv(f, dtype=str)
for c in ['created_at', 'received_at']: d[c] = d[c].astype('int64')
k = ['agency_id', 'vehicle_id', 'created_at']
say(f"[{f}] _id unique per row", d._id.is_unique)
say("rows that are re-sends of the same (agency,vehicle,created_at)", f"{d.duplicated(k).mean():.1%}")
grp = d[d.duplicated(k, keep=False)].groupby(k)
conf = grp[['stop_id', 'trip_id', 'latitude']].nunique()
say("dup groups whose copies DISAGREE on stop_id / trip_id / position",
    (round((conf.stop_id > 1).mean(), 3), round((conf.trip_id > 1).mean(), 4), round((conf.latitude > 1).mean(), 3)))
t = pd.to_datetime(d.created_at, unit='ms', utc=True).dt.tz_convert('Europe/Lisbon')
say("operational_date == date(created_at - 5h)", f"{((t - pd.Timedelta(hours=5)).dt.strftime('%Y%m%d') == d.operational_date).mean():.4f}")
say("latency received-created (s) median by agency",
    d.assign(l=(d.received_at - d.created_at) / 1000).groupby('agency_id').l.median().round(1).to_dict())

print("\n=== B. GTFS ===")
for p in PLANS:
    st = R(p, 'stop_times')
    say(f"[{p.split('/')[-1][:11]}] arrival!=departure | timepoint=1 share | times>=24h",
        con.execute(f"""select round(avg(case when arrival_time<>departure_time then 1 else 0 end),4),
            round(avg(case when timepoint='1' then 1 else 0 end),3),
            round(avg(case when try_cast(split_part(departure_time,':',1) as int)>=24 then 1 else 0 end),3) from {st}""").fetchone())
    say("   calendar_dates range", con.execute(f"select min(date), max(date) from {R(p,'calendar_dates')}").fetchone())
p41 = [p for p in PLANS if '_41_' in p][0]
say("plan 41 calendar says services for 31 Aug-6 Sep",
    con.execute(f"select date, list(service_id) from {R(p41,'calendar_dates')} where date between '20260831' and '20260906' group by 1 order by 1").fetchall())
say("...but LA77N trip_id suffix actually observed on Sat/Sun",
    con.execute(f"""select operational_date, split_part(trip_id,'_',7) suf, count(distinct trip_id) from {V}
        where agency_id='LA77N' and operational_date in ('20260905','20260906') group by 1,2 having count(*)>1000 order by 1""").fetchall())
stops = R(p41, 'stops')
cols = [c[0] for c in con.execute(f"describe select * from {stops}").fetchall()]
useless = [c for c in cols if con.execute(f"select count(distinct \"{c}\") from {stops}").fetchone()[0] <= 1]
say("stops.txt columns that are empty or constant (drop)", f"{len(useless)}/{len(cols)}: {useless}")

print("\n=== C. WAZE ===")
W = pd.read_csv('Waze/waze_jams_zonas_20260831_20260906.csv')
say("velocidade_kmh == velocidade*3.6", f"{np.isclose(W.velocidade*3.6, W.velocidade_kmh, atol=.01).mean():.3f}")
say("geowkt == geo (ignoring case)", f"{(W.geowkt.str.upper() == W.geo.str.upper()).mean():.3f}")
say("cidade distinct values", W.cidade.unique().tolist())
say("intensity label vs median speed km/h / median delay (labels look REVERSED)",
    W.groupby('nivel_de_intensidade').agg(v=('velocidade_kmh', 'median'), atraso=('atraso', 'median')).to_dict('index'))
say("distinct minutes with data per zone-day (of 1440)",
    W.groupby(['geohash6', 'data']).apply(lambda x: (x.Hora * 60 + x.Minuto).nunique()).describe()[['min', '50%', 'max']].to_dict())

print("\n=== D. PROCESSED DATA / CURRENT TEAM PIPELINE ===")
C = pd.read_parquet('_processed/corridor_pings.parquet')
say("trip_id seen on >1 operational_date (=> key needs date)", f"{(C.groupby('trip_id').operational_date.nunique() > 1).mean():.1%}")
P = C.sort_values(['stop_id', 'line', 'created_at']).copy(); g = P.groupby(['stop_id', 'line'])
P['prev_v'] = g.vehicle_id.shift(); P['hw'] = (P.created_at - g.created_at.shift()) / 1000
x = P[P.hw.notna() & (P.hw <= 3600)]
say("analysis/treinar_modelo_bunching.py label: share y=1 (hw<=120s, ping level)", f"{(x.hw <= 120).mean():.1%}")
say("   ...of which previous ping is the SAME bus", f"{(x[x.hw <= 120].prev_v == x[x.hw <= 120].vehicle_id).mean():.1%}")
ev = P[P.prev_v.notna() & (P.vehicle_id != P.prev_v) & (P.hw <= 90)]
say("processar_filtros_backend.py 'CRITICO' rows vs distinct (day, bus pair)",
    (len(ev), ev.drop_duplicates(['operational_date', 'vehicle_id', 'prev_v']).shape[0]))
