import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import collector as c
import horizon_dataset as h
from test_collector import T, metadata, book, oracle


class HorizonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.tmp.name)
        self.s = c.Store(self.root/'test.sqlite3')
        self.s.remember(T)

    def tearDown(self):
        self.s.close()
        self.tmp.cleanup()

    def point(self, source, exact='80000000000000000000000', receipt=None):
        received = (source+2)*c.NS if receipt is None else receipt
        raw = oracle(source)
        raw['payload']['data'][0]['full_accuracy_value'] = exact
        with patch('collector.time.time_ns', return_value=received+1):
            self.s.add('oracle', None, {'raw':raw,'points':c.oracle_points(raw,received)}, received, source*c.NS)

    def export(self, name='rows.jsonl'):
        out = self.root/name
        report = h.prepare(self.s, out)
        return report, [json.loads(x) for x in out.read_text().splitlines()][1]

    def test_direction_and_flat_exact_precision(self):
        self.point(T)
        self.point(T+60, '80000000000000000000001')
        self.point(T+120, '79999999999999999999999')
        self.point(T+180)
        _, row = self.export()
        self.assertEqual([row['targets'][str(n)]['direction'] for n in h.HORIZONS], ['up','down','flat'])
        self.assertIsNone(row['targets']['180']['up'])

    def test_no_interpolation(self):
        self.point(T)
        self.point(T+59)
        self.point(T+61)
        _, row = self.export()
        self.assertEqual(row['targets']['60']['status'], 'missing_exact_source')

    def test_conflicts_exclude_target(self):
        self.point(T)
        self.point(T+60)
        self.point(T+60, '81000000000000000000000')
        report,row = self.export()
        self.assertEqual(report['conflicting_source_seconds'],1)
        self.assertEqual(row['targets']['60']['status'],'conflicting_source')
        self.assertIsNone(row['targets']['60']['up'])

    def test_missing_exact_not_float_filled(self):
        self.point(T, None)
        self.point(T+60)
        _,row = self.export()
        self.assertEqual(row['targets']['60']['status'],'missing_exact_source')

    def test_receipt_after_start_never_feature(self):
        self.point(T-1, receipt=(T+5)*c.NS)
        self.point(T)
        self.point(T+60)
        _,row = self.export()
        self.assertIsNone(row['features']['twap_price'])
        self.assertEqual(row['targets']['60']['direction'],'flat')
        self.assertGreater(row['targets']['60']['available_ns'],row['cutoff_ns'])

    def test_duplicate_retains_first_available(self):
        self.point(T)
        self.point(T, receipt=(T+20)*c.NS)
        self.point(T+60)
        _,row = self.export()
        self.assertEqual(row['targets']['60']['evidence']['reference']['received_ns'],(T+2)*c.NS)

    def test_needs_past_features_and_books(self):
        for source in (T-122,T-62,T-2):
            self.point(source, receipt=(source+1)*c.NS)
        received = (T-1)*c.NS
        with patch('collector.time.time_ns', return_value=received+1):
            for side in ('Up','Down'):
                raw = book(side)
                raw['timestamp'] = str((T-2)*1000)
                b = c.parse_book(raw, metadata(),side,received)
                self.s.add('book',T,{'raw':raw,'normalized':b},received,b['source_ns'])
        self.point(T)
        self.point(T+60,'81000000000000000000000')
        report,row = self.export()
        self.assertTrue(row['features_complete'])
        self.assertEqual(report['counts']['60s_trainable'],1)
        self.assertNotIn('target', row['features'])
        self.assertEqual(row['cutoff_ns'],T*c.NS-1)

    def test_corrupt_hash_fails(self):
        self.point(T)
        self.s.c.execute("UPDATE records SET sha256='bad'")
        self.s.c.commit()
        with self.assertRaises(RuntimeError):
            self.export()

    def test_existing_export_preserved(self):
        out = self.root/'existing.jsonl'
        out.write_text('preserve')
        with self.assertRaises(FileExistsError):
            h.prepare(self.s,out)
        self.assertEqual(out.read_text(),'preserve')

    def test_market_windows_remain_grouped(self):
        self.s.remember(T+300)
        out = self.root/'group.jsonl'
        h.prepare(self.s,out)
        rows = [json.loads(x) for x in out.read_text().splitlines()][1:]
        self.assertEqual([r['window'] for r in rows],[T,T+300])
        self.assertTrue(all(set(r['targets'])=={'60','120','180'} for r in rows))


if __name__ == '__main__':
    unittest.main()