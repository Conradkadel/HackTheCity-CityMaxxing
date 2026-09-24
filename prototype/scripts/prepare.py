"""Stream one local CSV into the replay contract. Python 3.9+, standard library only."""
import argparse
import csv
import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

OPERATORS = {'IA9T6': 'Carris', 'LA77N': 'Carris Metropolitana · Area 1', 'BNA17': 'Carris Metropolitana · Area 2', 'YA15B': 'Carris Metropolitana · Area 3', 'A2L1N': 'Carris Metropolitana · Area 4'}
ROOT = Path(__file__).resolve().parents[1]

def epoch(value):
    return int(datetime.fromisoformat(value).replace(tzinfo=ZoneInfo('Europe/Lisbon')).timestamp() * 1000)

def prepare(source, output, start, end):
    if end <= start:
        raise ValueError('End time must follow start time.')
    counts = Counter(rowsRead=0, skippedOperator=0, skippedInvalid=0, skippedOutsideWindow=0, duplicatesCollapsed=0)
    unique = {}
    required = {'agency_id','vehicle_id','created_at','received_at','latitude','longitude','trip_id','stop_id'}
    with Path(source).open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        if not required.issubset(reader.fieldnames or []):
            raise ValueError('CSV lacks required vehicle columns: ' + ', '.join(sorted(required-set(reader.fieldnames or []))))
        for row in reader:
            counts['rowsRead'] += 1
            agency = row['agency_id']
            if agency not in OPERATORS:
                counts['skippedOperator'] += 1
                continue
            try:
                ts, received = int(row['created_at']), int(row['received_at'])
                lat, lon = float(row['latitude']), float(row['longitude'])
                if not row['vehicle_id'] or not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
                    raise ValueError('Invalid position or vehicle')
            except (ValueError, TypeError):
                counts['skippedInvalid'] += 1
                continue
            if not start - 120000 <= ts <= end:
                counts['skippedOutsideWindow'] += 1
                continue
            key = (agency, row['vehicle_id'], ts, lat, lon, row['trip_id'], row['stop_id'])
            if key in unique:
                counts['duplicatesCollapsed'] += 1
                unique[key]['receivedTimestamp'] = min(received, unique[key]['receivedTimestamp'])
            else:
                unique[key] = dict(timestamp=ts,receivedTimestamp=received,operatorId=agency,vehicleId=row['vehicle_id'],tripId=row['trip_id'],stopId=row['stop_id'],latitude=lat,longitude=lon)
    observations = sorted(unique.values(), key=lambda x:(x['timestamp'],x['operatorId'],x['vehicleId'],x['receivedTimestamp'],x['latitude'],x['longitude'],x['tripId'],x['stopId']))
    counts['observations'] = len(observations)
    counts['windowObservations'] = sum(x['timestamp'] >= start for x in observations)
    counts['historyObservations'] = len(observations)-counts['windowObservations']
    if not counts['windowObservations']:
        raise ValueError('No retained events in the requested window. Output was not written; choose another window explicitly.')
    data = dict(schemaVersion=1,metadata=dict(title='Lisbon · eycs2 geographic extract',sourcePartition='eycs2',operationalDate='20260901',timezone='Europe/Lisbon',startTimestamp=start,endTimestamp=end,historySeconds=120,synthetic=False,operators=OPERATORS,counts=dict(counts)),observations=observations)
    output=Path(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    temp=output.with_suffix('.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    temp.replace(output)
    return dict(counts)

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=ROOT.parent/'raw-data/datasets/TML/vehicles/eycs2/20260901/1.csv')
    parser.add_argument('--output',type=Path,default=ROOT/'public/data/replay.json')
    args=parser.parse_args()
    try:
        print(json.dumps(prepare(args.source,args.output,epoch('2026-09-01T07:00:00'),epoch('2026-09-01T09:00:00')),indent=2))
    except (ValueError,OSError) as exc:
        parser.exit(1,str(exc)+'\n')
