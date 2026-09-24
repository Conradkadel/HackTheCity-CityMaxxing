"""Read-only totals, measured query plans and comparison with the original JSON extract."""
import argparse
import json
import time
from collections import Counter
from datetime import timedelta
from pathlib import Path
from app import OBSERVATIONS_SQL,MAX_ROWS
from db import connect,active_version
from domain import selection_window,response_payload

def identity(o):
    return tuple(o[k] for k in ('operatorId','vehicleId','timestamp','latitude','longitude','tripId','stopId'))

def verify(extract=None):
    with connect() as conn:
        version=active_version(conn)
        if version is None:raise ValueError('Import a dataset first.')
        files=conn.execute('SELECT path,counts,elapsed_seconds FROM import_files WHERE version_id=%s ORDER BY path',(version,)).fetchall()
        a,b=selection_window('2026-09-01','07:00','09:00')
        ops=['IA9T6','LA77N','BNA17','YA15B','A2L1N']
        report={'version':version,'fileCount':len(files),'files':files,'queries':[]}
        rows=[]
        for areas in (['eycs2'],['eycs2','eyckp','eyckr']):
            sql=OBSERVATIONS_SQL.format(geofence='TRUE')
            params=(version,areas,ops,a-timedelta(seconds=120),b,None,None,None,None,True,[],MAX_ROWS+1)
            t=time.perf_counter();result=conn.execute(sql,params).fetchall();seconds=time.perf_counter()-t
            plan=conn.execute('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) '+sql,params).fetchone()
            report['queries'].append({'areas':areas,'seconds':seconds,'returnedRows':len(result),'overLimit':len(result)>MAX_ROWS,'plan':plan})
            if areas==['eycs2']:rows=result
        report['observations']=conn.execute('SELECT sum(observations) AS n FROM availability WHERE version_id=%s',(version,)).fetchone()['n']
        if extract:
            old=json.loads(Path(extract).read_text())['observations']
            new=response_payload(rows,version,['eycs2'],ops,a,b)['observations']
            old_keys=Counter(map(identity,old));new_keys=Counter(map(identity,new))
            old_receipts={identity(o):o['receivedTimestamp'] for o in old}
            report['comparison']={'oldRows':len(old),'newRows':len(new),'onlyOld':sum((old_keys-new_keys).values()),'onlyNew':sum((new_keys-old_keys).values()),'differentReceipts':sum(identity(o) in old_receipts and old_receipts[identity(o)]!=o['receivedTimestamp'] for o in new),'interpretation':'Differences can arise from all-file coverage, stricter identifier/date/geohash validation, cross-file deduplication and earliest receipt across sources. Investigate nonzero differences; this report does not assume equivalence.'}
        return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--extract');args=p.parse_args()
    print(json.dumps(verify(args.extract),indent=2,default=str))
