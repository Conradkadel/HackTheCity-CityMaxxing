import csv
import json
import tempfile
import unittest
from pathlib import Path
from prepare import prepare,epoch

class PreparationTests(unittest.TestCase):
    def test_stream_validation_dedup_and_boundaries(self):
        start=epoch('2026-09-01T07:00:00')
        self.assertEqual(start,1788242400000)
        base=dict(agency_id='IA9T6',vehicle_id='001',created_at=str(start),received_at=str(start+100),latitude='38.7',longitude='-9.1',trip_id='0003',stop_id='0002')
        rows=[base,{**base,'received_at':str(start+10)}, {**base,'latitude':'nan'}, {**base,'agency_id':'LTP61'}, {**base,'created_at':str(start-120001)}, {**base,'created_at':str(start-120000)}, {**base,'created_at':str(start+1000)}, {**base,'created_at':str(start+1001)}]
        with tempfile.TemporaryDirectory() as tmp:
            src=Path(tmp)/'source.csv'; out=Path(tmp)/'out.json'
            with src.open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=list(base));w.writeheader();w.writerows(rows)
            counts=prepare(src,out,start,start+1000)
            data=json.loads(out.read_text());obs=data['observations']
            self.assertEqual(len(obs),3)
            self.assertEqual(obs[1]['receivedTimestamp'],start+10)
            self.assertEqual(obs[1]['vehicleId'],'001')
            self.assertEqual(obs[1]['stopId'],'0002')
            self.assertNotIn('driver_id',out.read_text())
            self.assertEqual(counts['duplicatesCollapsed'],1)
            self.assertEqual(counts['skippedInvalid'],1)
            self.assertEqual(counts['skippedOperator'],1)
            self.assertEqual(counts['skippedOutsideWindow'],2)
            original=out.read_bytes()
            with self.assertRaisesRegex(ValueError,'No retained events'):prepare(src,out,start+999999,start+1000999)
            self.assertEqual(out.read_bytes(),original)

if __name__=='__main__': unittest.main()
