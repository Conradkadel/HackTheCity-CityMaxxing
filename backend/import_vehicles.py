"""Explicit, resumable vehicle import. Never run automatically with API startup."""
import argparse
import csv
import hashlib
import json
import time
from collections import Counter
from pathlib import Path
from psycopg.types.json import Jsonb
from db import connect,migrate,active_version
from domain import REQUIRED,EVENT_COLUMNS,parse_row
IMPORT_LOCK=717002

def checksum(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def inventory(root):
    files=sorted(root.rglob('*.csv'))
    if not files:raise ValueError('No CSV files found under the supplied source root.')
    entries=[dict(path=str(p.relative_to(root)),checksum=checksum(p),bytes=p.stat().st_size) for p in files]
    fingerprint=hashlib.sha256(json.dumps(entries,sort_keys=True).encode()).hexdigest()
    return entries,fingerprint

def load_file(conn,root,entry,version,batch_size=50000):
    path=root/entry['path'];t=time.monotonic()
    counts=Counter(rowsRead=0,validRows=0,insertedObservations=0,duplicatesCollapsed=0)
    rejected=Counter()
    with conn.transaction():
        conn.execute('CREATE TEMP TABLE stage (LIKE vehicle_events INCLUDING DEFAULTS) ON COMMIT DROP')
        def flush(batch):
            if not batch:return
            with conn.cursor().copy('COPY stage (version_id,'+','.join(EVENT_COLUMNS)+') FROM STDIN') as copy:
                for values in batch:copy.write_row((version,)+values)
            result=conn.execute('''WITH applied AS (
              INSERT INTO vehicle_events SELECT DISTINCT ON (observation_key) * FROM stage
              ORDER BY observation_key,received_at,event_id,geohash_5
              ON CONFLICT(version_id,observation_key) DO UPDATE SET
                received_at=LEAST(vehicle_events.received_at,excluded.received_at),
                event_id=CASE WHEN (excluded.received_at,excluded.event_id)<(vehicle_events.received_at,vehicle_events.event_id) THEN excluded.event_id ELSE vehicle_events.event_id END,
                driver_id=CASE WHEN (excluded.received_at,excluded.event_id)<(vehicle_events.received_at,vehicle_events.event_id) THEN excluded.driver_id ELSE vehicle_events.driver_id END,
                operational_date=CASE WHEN (excluded.received_at,excluded.event_id)<(vehicle_events.received_at,vehicle_events.event_id) THEN excluded.operational_date ELSE vehicle_events.operational_date END,
                geohash_5=CASE WHEN (excluded.received_at,excluded.event_id)<(vehicle_events.received_at,vehicle_events.event_id) THEN excluded.geohash_5 ELSE vehicle_events.geohash_5 END
              RETURNING (xmax=0) AS inserted
            ) SELECT count(*) FILTER (WHERE inserted) AS inserted FROM applied''').fetchone()
            counts['insertedObservations']+=result['inserted']
            conn.execute('''INSERT INTO event_sources
              SELECT DISTINCT ON (version_id,observation_key,event_id)
                version_id,observation_key,%s,event_id,driver_id,geohash_5,received_at
              FROM stage ORDER BY version_id,observation_key,event_id,received_at
              ON CONFLICT(version_id,observation_key,source_file,source_event_id)
              DO UPDATE SET source_received_at=LEAST(event_sources.source_received_at,excluded.source_received_at)''',(entry['path'],))
            conn.execute('TRUNCATE stage')
        with path.open(encoding='utf-8-sig',newline='') as f:
            reader=csv.DictReader(f)
            if not REQUIRED.issubset(reader.fieldnames or []) or len(reader.fieldnames or [])!=len(set(reader.fieldnames or [])):
                raise ValueError(f'{entry["path"]}: missing or duplicate CSV headers')
            batch=[]
            for row in reader:
                counts['rowsRead']+=1
                try:batch.append(parse_row(row));counts['validRows']+=1
                except ValueError as exc:rejected[str(exc)]+=1;continue
                if len(batch)>=batch_size:flush(batch);batch=[]
            flush(batch)
        # A file changed while importing must not be marked successfully loaded.
        if checksum(path)!=entry['checksum']:raise ValueError(f'{path.name} changed during import; retry with an explicit rebuild.')
        counts['duplicatesCollapsed']=counts['validRows']-counts['insertedObservations']
        report={**counts,'rejected':dict(rejected)}
        conn.execute('INSERT INTO import_files VALUES(%s,%s,%s,%s,%s,%s)',(version,entry['path'],entry['checksum'],entry['bytes'],Jsonb(report),time.monotonic()-t))
    return report

def run(root,rebuild=False,batch_size=50000):
    root=Path(root).resolve()
    if not root.is_dir():raise ValueError('Source root must be a directory containing vehicle CSVs.')
    started=time.monotonic()
    entries,fingerprint=inventory(root)
    with connect() as conn:
        migrate(conn)
        if not conn.execute('SELECT pg_try_advisory_lock(%s) AS locked',(IMPORT_LOCK,)).fetchone()['locked']:
            raise ValueError('Another vehicle import is running.')
        active=active_version(conn)
        active_row=conn.execute('SELECT * FROM dataset_versions WHERE id=%s',(active,)).fetchone() if active else None
        previous=conn.execute('SELECT * FROM dataset_versions ORDER BY id DESC LIMIT 1').fetchone()
        if active_row and active_row['inventory_hash']==fingerprint and not rebuild and previous['status']=='ready':
            return {'version':active,'unchanged':True,'files':len(entries),'elapsedSeconds':time.monotonic()-started}
        if previous and previous['inventory_hash']!=fingerprint and not rebuild:
            raise ValueError('Source inventory changed. Use --rebuild to create a new version without replacing the active version until successful.')
        if previous and previous['inventory_hash']==fingerprint and previous['status']=='loading' and not rebuild:
            version=previous['id']
        else:
            version=conn.execute('INSERT INTO dataset_versions(inventory_hash,source_root) VALUES(%s,%s) RETURNING id',(fingerprint,str(root))).fetchone()['id']
        done={r['path'] for r in conn.execute('SELECT path FROM import_files WHERE version_id=%s',(version,))}
        for i,entry in enumerate(entries,1):
            if entry['path'] in done:
                print(f'[{i}/{len(entries)}] unchanged/resumed {entry["path"]}',flush=True)
                continue
            print(f'[{i}/{len(entries)}] importing {entry["path"]}',flush=True)
            print(json.dumps(load_file(conn,root,entry,version,batch_size)),flush=True)
        conn.execute('ANALYZE vehicle_events')
        with conn.transaction():
            conn.execute('DELETE FROM availability WHERE version_id=%s',(version,))
            conn.execute('''INSERT INTO availability SELECT version_id,geohash_5,
              (created_at AT TIME ZONE 'Europe/Lisbon')::date,agency_id,count(*),min(created_at),max(created_at)
              FROM vehicle_events WHERE version_id=%s GROUP BY 1,2,3,4''',(version,))
            total=conn.execute('SELECT coalesce(sum(observations),0) AS n FROM availability WHERE version_id=%s',(version,)).fetchone()['n']
            if not total:raise ValueError('No valid observations; the previous active dataset is unchanged.')
            conn.execute('ANALYZE availability')
            conn.execute("UPDATE dataset_versions SET status='ready',completed_at=now() WHERE id=%s",(version,))
            conn.execute('INSERT INTO active_dataset VALUES(true,%s) ON CONFLICT(singleton) DO UPDATE SET version_id=excluded.version_id',(version,))
        return {'version':version,'files':len(entries),'observations':int(total),'elapsedSeconds':time.monotonic()-started}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,required=True)
    parser.add_argument('--rebuild',action='store_true')
    args=parser.parse_args()
    try:print(json.dumps(run(args.source_root,args.rebuild),indent=2))
    except Exception as exc:parser.exit(1,f'Import stopped: {exc}\nCompleted files can be resumed; the previous active dataset is unchanged.\n')
