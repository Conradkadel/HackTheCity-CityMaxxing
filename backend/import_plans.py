"""Import all supplied GTFS TXT tables, preserving source strings and package namespaces."""
import argparse
import csv
import hashlib
import json
import math
import time
from pathlib import Path
from psycopg.types.json import Jsonb
from db import connect,migrate

REQUIRED={'agency':{'agency_id','agency_name'},'feed_info':{'feed_start_date','feed_end_date'},'routes':{'route_id'},'trips':{'trip_id','route_id','shape_id'},'stops':{'stop_id','stop_name','stop_lat','stop_lon'},'shapes':{'shape_id','shape_pt_lat','shape_pt_lon','shape_pt_sequence'},'stop_times':{'trip_id','stop_id','stop_sequence','arrival_time','departure_time'}}
def normalize_package(conn,pid):
    conn.execute("""INSERT INTO schedule_routes(package_id,route_id,line_short_name,route_long_name,route_color)
      SELECT package_id,data->>'route_id',COALESCE(NULLIF(data->>'route_short_name',''),data->>'line_id',data->>'route_id'),COALESCE(data->>'route_long_name',''),COALESCE(data->>'route_color','') FROM plan_records WHERE package_id=%s AND table_name='routes'
      ON CONFLICT(package_id,route_id) DO NOTHING""",(pid,))
    conn.execute("""INSERT INTO schedule_trips(package_id,trip_id,route_id,shape_id,direction_id,service_id)
      SELECT package_id,data->>'trip_id',data->>'route_id',COALESCE(data->>'shape_id',''),COALESCE(data->>'direction_id',''),COALESCE(data->>'service_id','') FROM plan_records WHERE package_id=%s AND table_name='trips'
      ON CONFLICT(package_id,trip_id) DO NOTHING""",(pid,))
    conn.execute("""INSERT INTO schedule_stop_visits(package_id,trip_id,stop_id,stop_sequence,arrival_time,departure_time)
      SELECT package_id,data->>'trip_id',data->>'stop_id',(data->>'stop_sequence')::integer,COALESCE(data->>'arrival_time',''),COALESCE(data->>'departure_time','') FROM plan_records WHERE package_id=%s AND table_name='stop_times'
      ON CONFLICT(package_id,trip_id,stop_id,stop_sequence) DO NOTHING""",(pid,))
def records(path):
    with path.open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f)
        if not reader.fieldnames or len(reader.fieldnames)!=len(set(reader.fieldnames)) or not REQUIRED.get(path.stem,set())<=set(reader.fieldnames):
            raise ValueError(f'{path}: invalid headers')
        for n,row in enumerate(reader,2):
            if None in row or any(v is None for v in row.values()):raise ValueError(f'{path}:{n}: malformed row')
            validate_row(path.stem,row)
            yield row

def validate_row(table,row):
    keys={'routes':['route_id'],'trips':['trip_id','route_id'],'stops':['stop_id'],'shapes':['shape_id'],'stop_times':['trip_id','stop_id']}.get(table,[])
    if any(not row[k].strip() for k in keys):raise ValueError(f'{table}: blank identifier')
    if table in ('stops','shapes'):
        a,b=('stop_lat','stop_lon') if table=='stops' else ('shape_pt_lat','shape_pt_lon')
        # GTFS locations can omit both coordinates; they remain in the stop list, not the map.
        if table=='stops' and not row[a] and not row[b]:return
        lat,lon=float(row[a]),float(row[b])
        if not math.isfinite(lat) or not math.isfinite(lon) or abs(lat)>90 or abs(lon)>180:raise ValueError(f'{table}: invalid coordinates')
    seq={'shapes':'shape_pt_sequence','stop_times':'stop_sequence'}.get(table)
    if seq and int(row[seq])<0:raise ValueError(f'{table}: invalid sequence')

def fingerprint(files):
    h=hashlib.sha256()
    for p in files:
        h.update(p.name.encode());h.update(b'\0')
        with p.open('rb') as f:
            for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def run(root,wait_for_vehicles=False):
    root=Path(root).resolve();packages=sorted(p.parent for p in root.glob('*/feed_info.txt'))
    if not packages:raise ValueError('No operation-plan packages found at source root')
    with connect() as conn:
        if wait_for_vehicles:
            print('Waiting for the vehicle importer to release its lock…',flush=True)
            conn.execute('SELECT pg_advisory_lock(717002)')
        migrate(conn)
        conn.execute('SELECT pg_advisory_lock(717003)')
        for package in packages:
            files=sorted(package.glob('*.txt'));digest=fingerprint(files)
            if conn.execute('SELECT id FROM plan_packages WHERE source_name=%s AND checksum=%s',(package.name,digest)).fetchone():
                print(f'Unchanged: {package.name}',flush=True);continue
            if not set(REQUIRED)<={p.stem for p in files}:raise ValueError(f'{package}: missing required tables')
            agency=list(records(package/'agency.txt'));feed=list(records(package/'feed_info.txt'))
            started=time.monotonic();counts={}
            with conn.transaction():
                pid=conn.execute('INSERT INTO plan_packages(source_name,checksum,agency,feed,counts) VALUES(%s,%s,%s,%s,%s) RETURNING id',(package.name,digest,Jsonb(agency),Jsonb(feed),Jsonb({}))).fetchone()['id']
                for path in files:
                    n=0
                    with conn.cursor().copy('COPY plan_records(package_id,table_name,row_number,data) FROM STDIN') as copy:
                        for n,row in enumerate(records(path),1):copy.write_row((pid,path.stem,n,Jsonb(row)))
                    counts[path.stem]=n
                    print(f'{package.name}/{path.name}: {n} rows',flush=True)
                if digest!=fingerprint(files):raise ValueError('Source changed during import; package rolled back')
                conn.execute('UPDATE plan_packages SET counts=%s WHERE id=%s',(Jsonb(counts),pid))
                normalize_package(conn,pid)
            print(json.dumps({'package':package.name,'id':pid,'counts':counts,'seconds':round(time.monotonic()-started,2)}),flush=True)
        conn.execute('ANALYZE plan_records')
        print('Operation-plan import complete.',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source-root',required=True);p.add_argument('--wait-for-vehicles',action='store_true');a=p.parse_args()
    run(a.source_root,a.wait_for_vehicles)
