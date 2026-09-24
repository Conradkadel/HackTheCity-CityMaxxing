"""Read-only access to committed data while an import is incomplete."""
from fastapi import HTTPException

def preview_version(conn,requested=None):
    if requested is None:
        row=conn.execute('SELECT id,status FROM dataset_versions ORDER BY id DESC LIMIT 1').fetchone()
    else:
        row=conn.execute('SELECT id,status FROM dataset_versions WHERE id=%s',(requested,)).fetchone()
    if not row:raise HTTPException(503,'No vehicle import has started yet.')
    return row['id']

def progress(conn,version):
    row=conn.execute("SELECT count(*) AS files,coalesce(sum((counts->>'insertedObservations')::bigint),0) AS observations FROM import_files WHERE version_id=%s",(version,)).fetchone()
    return {'completedFiles':row['files'],'committedObservations':int(row['observations'])}

def preview_coverage(conn,version):
    # MVCC hides all writes from an in-progress file transaction. No dirty reads,
    # no writes to final availability, and no source-date/calendar-date inference.
    return conn.execute("""SELECT geohash_5,(created_at AT TIME ZONE 'Europe/Lisbon')::date AS calendar_date,
      agency_id,count(*) AS observations FROM vehicle_events WHERE version_id=%s
      GROUP BY 1,2,3 ORDER BY 1,2,3""",(version,)).fetchall()
