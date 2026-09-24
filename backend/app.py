from contextlib import asynccontextmanager
from typing import Optional
from datetime import timedelta
import logging
import psycopg
from fastapi import FastAPI,HTTPException,Query
from fastapi.responses import JSONResponse
from db import connect,migrate,active_version
from domain import AREAS,OPERATORS,selection_window,response_payload
from plans_api import router as plans_router
from schedule import router as schedule_router,ensure_operator_packages
from preview import preview_version,progress,preview_coverage

MAX_ROWS=200000
OBSERVATIONS_SQL='''SELECT created_at,received_at,agency_id,vehicle_id,trip_id,stop_id,latitude,longitude,geohash_5
 FROM vehicle_events WHERE version_id=%s AND geohash_5=ANY(%s) AND agency_id=ANY(%s)
 AND created_at >= %s AND created_at <= %s
 ORDER BY created_at,agency_id,vehicle_id,received_at,latitude,longitude,trip_id,stop_id,observation_key
 LIMIT %s'''
SCHEDULE_OBSERVATIONS_SQL='''SELECT e.created_at,e.received_at,e.agency_id,e.vehicle_id,e.trip_id,e.stop_id,e.latitude,e.longitude,e.geohash_5,
 t.package_id,t.route_id,t.direction_id,r.line_short_name,r.route_long_name,s.stop_sequence,s.arrival_time,s.departure_time
 FROM vehicle_events e JOIN schedule_operator_packages op ON op.agency_id=e.agency_id
 JOIN schedule_trips t ON t.package_id=op.package_id AND t.trip_id=e.trip_id
 JOIN schedule_routes r ON r.package_id=t.package_id AND r.route_id=t.route_id
 JOIN schedule_stop_visits s ON s.package_id=t.package_id AND s.trip_id=t.trip_id AND s.stop_id=e.stop_id
 WHERE e.version_id=%s AND e.geohash_5=ANY(%s) AND e.agency_id=ANY(%s) AND e.created_at >= %s AND e.created_at <= %s
 AND t.route_id=%s AND (%s::text IS NULL OR t.direction_id=%s)
 ORDER BY e.created_at,e.agency_id,e.vehicle_id,e.received_at,e.observation_key LIMIT %s'''

@asynccontextmanager
async def lifespan(app):
    with connect() as conn:
        migrate(conn)
        ensure_operator_packages(conn)
    yield

app=FastAPI(title='Headway local vehicle API',lifespan=lifespan)
app.include_router(plans_router)
app.include_router(schedule_router)

@app.exception_handler(psycopg.Error)
async def database_error(request,exc):
    logging.getLogger('headway').error('Database operation failed: %s',type(exc).__name__)
    return JSONResponse(status_code=503,content={'detail':'Database unavailable or query timed out. Check Compose services or narrow the selection.'})

def require_version(conn):
    version=active_version(conn)
    if version is None:raise HTTPException(503,'No completed dataset available. If an import is running, enable Preview incomplete import; otherwise run the import command in README.md.')
    return version

@app.get('/api/health')
def health():
    with connect() as conn:
        conn.execute('SELECT 1')
        return {'status':'ok','datasetVersion':active_version(conn)}

@app.get('/api/availability')
def availability(preview:bool=False):
    with connect() as conn:
        with conn.transaction():
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            conn.execute("SET LOCAL statement_timeout='30s'")
            version=preview_version(conn) if preview else require_version(conn)
            rows=preview_coverage(conn,version) if preview else conn.execute('SELECT geohash_5,calendar_date,agency_id,observations,first_event,last_event FROM availability WHERE version_id=%s ORDER BY geohash_5,calendar_date,agency_id',(version,)).fetchall()
            status=progress(conn,version) if preview else None
    areas=sorted({r['geohash_5'] for r in rows});ops=sorted({r['agency_id'] for r in rows})
    return {'datasetVersion':version,'partialPreview':preview,'importProgress':status,'timezone':'Europe/Lisbon','maxWindowHours':4,'maxObservations':MAX_ROWS,
            'areas':[{'id':a,'name':AREAS.get(a,a)} for a in areas],
            'operators':[{'id':o,'name':OPERATORS.get(o,o)} for o in ops],
            'dates':sorted({r['calendar_date'].isoformat() for r in rows}),
            'coverage':[{'area':r['geohash_5'],'date':r['calendar_date'].isoformat(),'operatorId':r['agency_id'],'observations':r['observations']} for r in rows]}

@app.get('/api/observations')
def observations(date:str,start:str,end:str,area:list[str]=Query(...),operator:list[str]=Query(...),preview:bool=False,dataset_version:int=Query(None,gt=0),schedule_mode:bool=False,route_id:Optional[str]=None,direction_id:Optional[str]=None):
    areas=sorted(set(area));ops=sorted(set(operator))
    if not areas or not ops or len(areas)>100 or len(ops)>100:raise HTTPException(422,'Select at least one area and operator (at most 100 each).')
    try:a,b=selection_window(date,start,end)
    except ValueError as exc:raise HTTPException(422,str(exc))
    if schedule_mode and (preview or not route_id):raise HTTPException(422,'Schedule replay requires a completed dataset and a route.')
    with connect() as conn:
        with conn.transaction():
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            conn.execute("SET LOCAL statement_timeout='30s'")
            version=preview_version(conn,dataset_version) if preview else require_version(conn)
            if not preview:
                valid_areas={r['geohash_5'] for r in conn.execute('SELECT DISTINCT geohash_5 FROM availability WHERE version_id=%s',(version,))}
                valid_ops={r['agency_id'] for r in conn.execute('SELECT DISTINCT agency_id FROM availability WHERE version_id=%s',(version,))}
                if not set(areas)<=valid_areas or not set(ops)<=valid_ops:raise HTTPException(422,'Unknown area or operator. Refresh available selections.')
            else:
                import re
                if any(not re.fullmatch('[0123456789bcdefghjkmnpqrstuvwxyz]{5}',x) for x in areas) or any(not x or len(x)>100 for x in ops):raise HTTPException(422,'Invalid area or operator.')
            status=progress(conn,version) if preview else None
            sql=SCHEDULE_OBSERVATIONS_SQL if schedule_mode else OBSERVATIONS_SQL
            params=(version,areas,ops,a-timedelta(seconds=120),b,route_id,direction_id,direction_id,MAX_ROWS+1) if schedule_mode else (version,areas,ops,a-timedelta(seconds=120),b,MAX_ROWS+1)
            rows=conn.execute(sql,params).fetchall()
            total=conn.execute('SELECT count(*) AS n FROM vehicle_events WHERE version_id=%s AND geohash_5=ANY(%s) AND agency_id=ANY(%s) AND created_at >= %s AND created_at <= %s',(version,areas,ops,a-timedelta(seconds=120),b)).fetchone()['n'] if schedule_mode else 0
    if len(rows)>MAX_ROWS:raise HTTPException(413,'More than 200,000 observations including prehistory. Narrow the areas, time window or operators; no data was truncated.')
    payload=response_payload(rows,version,areas,ops,a,b)
    if schedule_mode:
        payload['metadata']['scheduleReplay']=True
        payload['metadata']['coverage']={'matchedObservations':len(rows),'excludedObservations':max(0,total-len(rows)),'warning':'2025 operation-plan reference matched to 2026 vehicle reports; this is not confirmed schedule adherence.'}
    payload['metadata'].update(partialPreview=preview,importProgress=status)
    return payload
