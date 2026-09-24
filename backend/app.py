from contextlib import asynccontextmanager
from datetime import timedelta
import logging
import psycopg
from fastapi import FastAPI,HTTPException,Query
from fastapi.responses import JSONResponse
from db import connect,migrate,active_version
from domain import AREAS,OPERATORS,selection_window,response_payload
from plans_api import router as plans_router
from preview import preview_version,progress,preview_coverage

MAX_ROWS=200000
OBSERVATIONS_SQL='''SELECT created_at,received_at,agency_id,vehicle_id,trip_id,stop_id,latitude,longitude,geohash_5
 FROM vehicle_events WHERE version_id=%s AND geohash_5=ANY(%s) AND agency_id=ANY(%s)
 AND created_at >= %s AND created_at <= %s
 ORDER BY created_at,agency_id,vehicle_id,received_at,latitude,longitude,trip_id,stop_id,observation_key
 LIMIT %s'''

@asynccontextmanager
async def lifespan(app):
    with connect() as conn:migrate(conn)
    yield

app=FastAPI(title='Headway local vehicle API',lifespan=lifespan)
app.include_router(plans_router)

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
def observations(date:str,start:str,end:str,area:list[str]=Query(...),operator:list[str]=Query(...),preview:bool=False,dataset_version:int=Query(None,gt=0)):
    areas=sorted(set(area));ops=sorted(set(operator))
    if not areas or not ops or len(areas)>100 or len(ops)>100:raise HTTPException(422,'Select at least one area and operator (at most 100 each).')
    try:a,b=selection_window(date,start,end)
    except ValueError as exc:raise HTTPException(422,str(exc))
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
            rows=conn.execute(OBSERVATIONS_SQL,(version,areas,ops,a-timedelta(seconds=120),b,MAX_ROWS+1)).fetchall()
    if len(rows)>MAX_ROWS:raise HTTPException(413,'More than 200,000 observations including prehistory. Narrow the areas, time window or operators; no data was truncated.')
    payload=response_payload(rows,version,areas,ops,a,b)
    payload['metadata'].update(partialPreview=preview,importProgress=status)
    return payload
