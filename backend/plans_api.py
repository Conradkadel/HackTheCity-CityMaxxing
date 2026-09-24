from fastapi import APIRouter,HTTPException
from db import connect

router=APIRouter(prefix='/api/plans')
def package(conn,pid):
    p=conn.execute('SELECT id,source_name,agency,feed,counts FROM plan_packages WHERE id=%s',(pid,)).fetchone()
    if not p:raise HTTPException(404,'Plan package not found. Refresh packages.')
    return p

@router.get('/packages')
def packages():
    with connect() as c:return c.execute('SELECT id,source_name,agency,feed,counts FROM plan_packages ORDER BY source_name,id DESC').fetchall()

@router.get('/{pid}/routes')
def routes(pid:int):
    with connect() as c:
        package(c,pid)
        return [r['data'] for r in c.execute("SELECT data FROM plan_records WHERE package_id=%s AND table_name='routes' ORDER BY data->>'line_id',data->>'route_id'",(pid,))]

@router.get('/{pid}/trips')
def trips(pid:int,route_id:str):
    with connect() as c:
        package(c,pid)
        return [r['data'] for r in c.execute("SELECT data FROM plan_records WHERE package_id=%s AND table_name='trips' AND data->>'route_id'=%s ORDER BY data->>'direction_id',data->>'trip_id'",(pid,route_id))]

@router.get('/{pid}/trip')
def trip(pid:int,trip_id:str):
    with connect() as c:
        p=package(c,pid)
        matches=c.execute("SELECT data FROM plan_records WHERE package_id=%s AND table_name='trips' AND data->>'trip_id'=%s",(pid,trip_id)).fetchall()
        if not matches:raise HTTPException(404,'Planned trip not found.')
        if len(matches)!=1:raise HTTPException(409,'Ambiguous trip ID in source package.')
        t=matches[0]['data']
        shape=[r['data'] for r in c.execute("SELECT data FROM plan_records WHERE package_id=%s AND table_name='shapes' AND data->>'shape_id'=%s ORDER BY (data->>'shape_pt_sequence')::int,row_number",(pid,t.get('shape_id','')))]
        stops=c.execute("""SELECT st.data AS visit,s.data AS stop FROM plan_records st
         LEFT JOIN plan_records s ON s.package_id=st.package_id AND s.table_name='stops' AND s.data->>'stop_id'=st.data->>'stop_id'
         WHERE st.package_id=%s AND st.table_name='stop_times' AND st.data->>'trip_id'=%s
         ORDER BY (st.data->>'stop_sequence')::int,st.row_number,s.row_number""",(pid,trip_id)).fetchall()
    return {'package':p,'trip':t,'shape':[[float(r['shape_pt_lat']),float(r['shape_pt_lon'])] for r in shape],'stops':stops,'warning':'Planned service, not observed movement. These plan dates are not verified for the 2026 vehicle observations.'}
