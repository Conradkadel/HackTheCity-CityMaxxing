import hashlib
import json
import math
import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

LISBON=ZoneInfo('Europe/Lisbon')
OPERATORS={'IA9T6':'Carris (includes trams)','LA77N':'Carris Metropolitana · Area 1','BNA17':'Carris Metropolitana · Area 2','YA15B':'Carris Metropolitana · Area 3','A2L1N':'Carris Metropolitana · Area 4','N18KL':'Comboios de Portugal','7NTB1':'Fertagus','IA2N9':'Metropolitano de Lisboa','HF16N':'Mobicascais','LTP61':'Soflusa'}
AREAS={'eyckp':'Ponte 25 de Abril / Cais do Sodré / Alcântara','eyckr':'Campo Grande / Sete Rios / Monsanto / Campolide','eyckx':'Campo Grande / Alameda das Linhas de Torres','eyckq':'Benfica / Colégio Militar','eycs8':'Ponte Vasco da Gama','eycs9':'Ponte Vasco da Gama','eyckj':'Algés','eyckn':'Algés','eycks':'IC19 / Mira-Sintra / Agualva-Cacém','eyckt':'IC19','eyckm':'IC19','eyckk':'IC19','eyck1':'Cascais','eyck3':'Cascais','eyck4':'Cascais','eyck6':'Cascais','eycs2':'Rua Morais Soares / surrounding area','eyckw':'Caneças / Pontinha','eyc7w':'Charneca da Caparica','eyce8':'Estrada Nacional 10','eyceb':'Estrada Nacional 10','eyc7z':'Estrada Nacional 10','eycdb':'Sesimbra / Quinta do Conde','eycd8':'Sesimbra / Quinta do Conde'}
REQUIRED={'_id','agency_id','vehicle_id','driver_id','trip_id','stop_id','created_at','received_at','operational_date','latitude','longitude','geohash_5'}
EVENT_COLUMNS=['observation_key','event_id','agency_id','vehicle_id','driver_id','trip_id','stop_id','created_at','received_at','operational_date','latitude','longitude','geohash_5']

def parse_row(row):
    if None in row or any(row.get(k) is None for k in REQUIRED):
        raise ValueError('column_count')
    if not all(row[k].strip() for k in ('_id','agency_id','vehicle_id')):
        raise ValueError('identifier')
    try:
        lat,lon=float(row['latitude']),float(row['longitude'])
        if not math.isfinite(lat) or not math.isfinite(lon) or not -90<=lat<=90 or not -180<=lon<=180:
            raise ValueError()
    except (ValueError,TypeError):
        raise ValueError('coordinates')
    try:
        ts=int(row['created_at']); received=int(row['received_at'])
        dt=datetime.fromtimestamp(ts/1000,timezone.utc)
        receipt=datetime.fromtimestamp(received/1000,timezone.utc)
        if not 2000<=dt.year<=2100 or not 2000<=receipt.year<=2100: raise ValueError()
        day=datetime.strptime(row['operational_date'],'%Y%m%d').date()
    except (ValueError,OverflowError,OSError,TypeError):
        raise ValueError('timestamp_or_date')
    geo=row['geohash_5'].strip()
    if not re.fullmatch('[0123456789bcdefghjkmnpqrstuvwxyz]{5}',geo):
        raise ValueError('geohash')
    # Normalize negative zero before hashing equivalent numeric coordinates.
    lat=lat or 0.0;lon=lon or 0.0
    identity=[row['agency_id'],row['vehicle_id'],ts,lat,lon,row['trip_id'],row['stop_id']]
    key=hashlib.sha256(json.dumps(identity,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    return (key,row['_id'],row['agency_id'],row['vehicle_id'],row['driver_id'],row['trip_id'],row['stop_id'],dt,receipt,day,lat,lon,geo)

def selection_window(day,start,end):
    try:
        d=date.fromisoformat(day)
        if not re.fullmatch(r'\d{2}:\d{2}',start) or not re.fullmatch(r'\d{2}:\d{2}',end): raise ValueError()
        a=datetime.combine(d,time.fromisoformat(start))
        b=datetime.combine(d,time.fromisoformat(end))
        if b<a:b+=timedelta(days=1)
        def localize(value):
            first=value.replace(tzinfo=LISBON,fold=0)
            second=value.replace(tzinfo=LISBON,fold=1)
            if first.utcoffset()!=second.utcoffset() or first.astimezone(timezone.utc).astimezone(LISBON).replace(tzinfo=None)!=value:
                raise ValueError('Ambiguous/nonexistent Lisbon clock time. Choose a window away from the DST change.')
            return first.astimezone(timezone.utc)
        a,b=localize(a),localize(b)
    except ValueError as exc:
        raise ValueError(str(exc) if 'Lisbon' in str(exc) else 'Use an ISO date and HH:MM local times.')
    if not timedelta(0)<b-a<=timedelta(hours=4):
        raise ValueError('Select a nonempty window of at most four hours.')
    return a,b

def schedule_reference(created_at,clock):
    """Reference a GTFS service-clock value to the Lisbon service day starting at 04:00."""
    if not clock:return None
    try:
        h,m,s=(int(x) for x in clock.split(':'))
        if h<0 or m>59 or s>59:raise ValueError
        local=created_at.astimezone(LISBON)
        service_day=local.date()-timedelta(days=1 if local.hour<4 else 0)
        return datetime.combine(service_day,time.min,tzinfo=LISBON)+timedelta(hours=h,minutes=m,seconds=s)
    except (ValueError,TypeError):return None

def response_payload(rows,version,areas,ops,start,end):
    observations=[]
    for r in rows:
        item=dict(timestamp=int(r['created_at'].timestamp()*1000),receivedTimestamp=int(r['received_at'].timestamp()*1000),operatorId=r['agency_id'],vehicleId=r['vehicle_id'],tripId=r['trip_id'],stopId=r['stop_id'],latitude=r['latitude'],longitude=r['longitude'],geohash=r['geohash_5'])
        route_id=r.get('route_id') if hasattr(r,'get') else r['route_id'] if 'route_id' in r else None
        item['routeMatchStatus']='matched' if route_id else 'unmatched'
        item['isFocus']=bool(r.get('is_focus',False)) if hasattr(r,'get') else False
        if route_id:
            item['route']=dict(packageId=r['package_id'],routeId=route_id,line=r['line_short_name'],routeName=r['route_long_name'],directionId=r['direction_id'],mode=r.get('line_mode') or 'bus')
            clock=(r.get('departure_time') or r.get('arrival_time')) if hasattr(r,'get') else None
            reference=schedule_reference(r['created_at'],clock)
            if r.get('stop_sequence') is not None:
                item['schedule']=dict(**item['route'],stopSequence=r['stop_sequence'],scheduledTime=int(reference.timestamp()*1000) if reference else None,reportedStopDifferenceSeconds=round((r['created_at']-reference).total_seconds()) if reference else None)
        observations.append(item)
    matched=sum(o['routeMatchStatus']=='matched' for o in observations)
    focus=sum(o['isFocus'] for o in observations)
    return dict(schemaVersion=1,metadata=dict(title='Lisbon · selected areas',sourcePartition=','.join(areas),operationalDate='',calendarDate=start.astimezone(LISBON).date().isoformat(),areas=areas,datasetVersion=version,timezone='Europe/Lisbon',startTimestamp=int(start.timestamp()*1000),endTimestamp=int(end.timestamp()*1000),historySeconds=120,synthetic=False,operators={o:OPERATORS.get(o,o) for o in ops},counts={'observations':len(rows),'windowObservations':sum(r['created_at']>=start for r in rows),'matchedObservations':matched,'unmatchedObservations':len(rows)-matched,'focusObservations':focus,'contextObservations':len(rows)-focus}),observations=observations)
