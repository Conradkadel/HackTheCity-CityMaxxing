from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from fastapi import APIRouter,HTTPException,Query
from db import connect

LISBON=ZoneInfo('Europe/Lisbon')
PACKAGE_SOURCES={'20250924_43_YEAR_04_05_01':'YA15B','20250930_44_YEAR_04_20_01':'A2L1N','20251002_41_YEAR_03_47_02':'LA77N','2025922_42_YEAR_03.03.55':'BNA17'}
TARGETS={
 '1218':('Mira-Sintra / Agualva-Cacém',['eycks']),'1219':('Mira-Sintra / Agualva-Cacém',['eycks']),'1715':('Mira-Sintra / Agualva-Cacém',['eycks']),
 '1709':('Caneças / Pontinha',['eyckw']),'1710':('Caneças / Pontinha',['eyckw']),'1711':('Caneças / Pontinha',['eyckw']),
 **{x:('Estrada Nacional 10',['eyce8','eyceb','eyc7z']) for x in ['3103','3512','3116','3118','3505','3508','3527','3535','3536','3605']},
 **{x:('Sesimbra / Quinta do Conde',['eycdb','eycd8']) for x in ['3201','3202','3203','3204','3205','3206','3207','3208','3209','3210','3211','3212','3213','3221','3223','3536','3544','3549','3625','3635','3642','3650','3721','4643']},
}
router=APIRouter(prefix='/api/schedule')

def ensure_operator_packages(conn):
    for source,agency in PACKAGE_SOURCES.items():
        row=conn.execute('SELECT id FROM plan_packages WHERE source_name=%s ORDER BY id DESC LIMIT 1',(source,)).fetchone()
        if row:conn.execute('INSERT INTO schedule_operator_packages(agency_id,package_id) VALUES(%s,%s) ON CONFLICT(agency_id) DO UPDATE SET package_id=EXCLUDED.package_id',(agency,row['id']))

def service_timestamp(service_day,clock):
    if not clock:return None
    try:
        h,m,s=(int(x) for x in clock.split(':'))
        if m>59 or s>59 or h<0:raise ValueError
        return datetime(service_day.year,service_day.month,service_day.day,tzinfo=LISBON)+timedelta(hours=h,minutes=m,seconds=s)
    except (ValueError,TypeError):return None

@router.get('/routes')
def routes(include_other:bool=False):
    with connect() as conn:
        rows=conn.execute('''SELECT op.agency_id,r.package_id,r.route_id,r.line_short_name,r.route_long_name,r.route_color,
          array_agg(DISTINCT t.direction_id ORDER BY t.direction_id) AS directions
          FROM schedule_operator_packages op JOIN schedule_routes r ON r.package_id=op.package_id
          JOIN schedule_trips t ON t.package_id=r.package_id AND t.route_id=r.route_id
          GROUP BY op.agency_id,r.package_id,r.route_id,r.line_short_name,r.route_long_name,r.route_color ORDER BY r.line_short_name,r.route_id''').fetchall()
    out=[]
    for r in rows:
        target=TARGETS.get(r['line_short_name'])
        if not include_other and not target:continue
        out.append({**r,'target':bool(target),'corridor':target[0] if target else 'Other matched CM route','areas':target[1] if target else []})
    return out

@router.get('/directions')
def directions(operator:str,route_id:str):
    with connect() as conn:
        rows=conn.execute('''SELECT DISTINCT t.direction_id,t.shape_id FROM schedule_operator_packages op JOIN schedule_trips t ON t.package_id=op.package_id
          WHERE op.agency_id=%s AND t.route_id=%s ORDER BY t.direction_id,t.shape_id''',(operator,route_id)).fetchall()
    if not rows:raise HTTPException(404,'No matched schedule route for this operator.')
    return rows
