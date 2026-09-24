from contextlib import asynccontextmanager
from typing import Optional
from datetime import timedelta
import logging
import psycopg
from fastapi import FastAPI,HTTPException,Query
from fastapi.responses import JSONResponse
from db import connect,migrate,active_version
from domain import AREAS,OPERATORS,selection_window,response_payload
from analysis_config import load_config,parent_cells,preset_by_id,preset_geohashes
from observation_query import OBSERVATIONS_SQL,build_observation_query
from plans_api import router as plans_router
from presets_api import router as presets_router
from workspace_api import router as workspace_router
from vehicle_day import router as vehicle_day_router
from line_day import router as line_day_router
from bunching_results_api import router as bunching_results_router
from bunching_api import router as bunching_router
from sim_api import router as sim_router
from findings_api import router as findings_router
from traffic_api import router as traffic_router
from traffic_diagram import router as traffic_diagram_router
from bunching_heatmap_api import router as bunching_heatmap_router
from schedule import router as schedule_router,ensure_operator_packages
from preview import preview_version,progress,preview_coverage

MAX_ROWS=200000

@asynccontextmanager
async def lifespan(app):
    with connect() as conn:
        migrate(conn)
        ensure_operator_packages(conn)
    yield

app=FastAPI(title='Headway local vehicle API',lifespan=lifespan)
app.include_router(plans_router)
app.include_router(schedule_router)
app.include_router(presets_router)
app.include_router(workspace_router)
app.include_router(vehicle_day_router)
app.include_router(line_day_router)
app.include_router(bunching_results_router)
app.include_router(bunching_router)
app.include_router(sim_router)
app.include_router(findings_router)
app.include_router(traffic_router)
app.include_router(traffic_diagram_router)
app.include_router(bunching_heatmap_router)

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
def observations(date:str,start:str,end:str,area:Optional[list[str]]=Query(None),operator:Optional[list[str]]=Query(None),preview:bool=False,dataset_version:int=Query(None,gt=0),schedule_mode:bool=False,route_id:Optional[str]=None,direction_id:Optional[str]=None,preset_id:Optional[str]=None,focus_line:Optional[list[str]]=Query(None),line:Optional[list[str]]=Query(None),include_context:bool=False):
    preset=preset_by_id(preset_id) if preset_id else None
    if preset_id and not preset:raise HTTPException(422,'Unknown analysis preset.')
    configured_geohashes=preset_geohashes(preset) if preset else []
    areas=sorted(set(area or (parent_cells(configured_geohashes) if preset else [])))
    ops=sorted(set(operator or (preset['operatorAgencyIds'] if preset else [])))
    public_lines=sorted(set(line or []))
    focus_lines=public_lines or sorted(set(focus_line or (preset['lines'] if preset else [])))
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
            allow_all=not public_lines and (not preset or include_context)
            sql,params=build_observation_query(version,areas,ops,a-timedelta(seconds=120),b,
                configured_geohashes if preset else [],route_id,direction_id,allow_all,focus_lines,MAX_ROWS+1)
            rows=conn.execute(sql,params).fetchall()
    if len(rows)>MAX_ROWS:raise HTTPException(413,'More than 200,000 observations including prehistory. Narrow the areas, time window or operators; no data was truncated.')
    payload=response_payload(rows,version,areas,ops,a,b)
    if preset:
        line_modes=preset.get('lineModes',{})
    else:
        line_modes={line:mode for configured in load_config()['presets']
                    if set(configured['operatorAgencyIds']) & set(ops)
                    for line,mode in configured.get('lineModes',{}).items()}
    for row,item in zip(rows,payload['observations']):
        item['isFocus']=bool(row.get('line_short_name') in focus_lines and row.get('route_id'))
        if item.get('route'):item['route']['mode']=line_modes.get(item['route']['line'],'bus')
        if item.get('schedule'):item['schedule']['mode']=line_modes.get(item['schedule']['line'],'bus')
    counts=payload['metadata']['counts'];counts['focusObservations']=sum(o['isFocus'] for o in payload['observations']);counts['contextObservations']=len(rows)-counts['focusObservations']
    payload['metadata'].update(presetId=preset_id,selectedLines=public_lines,includeContext=include_context,scheduleReplay=schedule_mode,
        routeCoverage={'matchedObservations':counts['matchedObservations'],'unmatchedObservations':counts['unmatchedObservations']})
    payload['metadata'].update(partialPreview=preview,importProgress=status)
    return payload
