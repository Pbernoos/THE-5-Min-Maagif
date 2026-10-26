import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

import collector as c
import tools
from test_collector import T, metadata, book, oracle


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.tmp.name)
        self.db = self.root/'market.sqlite3'
        self.store = c.Store(self.db)
        self.store.remember(T)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def fill(self):
        received = (T-10)*c.NS
        with patch('collector.time.time_ns', return_value=received+1):
            for side in ('Up', 'Down'):
                raw = book(side)
                norm = c.parse_book(raw, metadata(), side, received)
                self.store.add('book', T, dict(raw=raw, normalized=norm), received, norm['source_ns'])
            raw = oracle()
            points = c.oracle_points(raw, received)
            self.store.add('oracle', None, dict(raw=raw, points=points), received, points[0]['source_ns'])

    def test_reader_rejects_unknown(self):
        db = self.root/'unknown.sqlite3'
        with sqlite3.connect(db) as conn:
            conn.execute('CREATE TABLE unrelated(x)')
        conn.close()
        before = db.read_bytes()
        with self.assertRaises(ValueError), tools.reader(db):
            pass
        self.assertEqual(before, db.read_bytes())

    def test_reader_does_not_create_missing(self):
        p = self.root/'missing.db'
        with self.assertRaises(ValueError), tools.reader(p):
            pass
        self.assertFalse(p.exists())

    def test_reader_cannot_write(self):
        with tools.reader(self.db) as r:
            with self.assertRaises(sqlite3.OperationalError):
                r.c.execute('INSERT INTO markets VALUES(1,2)')

    def test_health_missing(self):
        h = tools.health(self.store, (T+4000)*c.NS)
        self.assertEqual(h['feeds']['book']['status'], 'missing')
        self.assertEqual(h['pending_closed_markets'], 1)
        self.assertTrue(any('30 minutes' in a for a in h['alerts']))

    def test_health_recent_stale_clock(self):
        self.fill()
        self.assertEqual(tools.health(self.store, (T-8)*c.NS)['feeds']['oracle']['status'], 'recent')
        self.assertEqual(tools.health(self.store, (T+100)*c.NS)['feeds']['oracle']['status'], 'stale')
        self.assertEqual(tools.health(self.store, (T-20)*c.NS)['feeds']['book']['status'], 'clock_error')

    def test_health_rejection_reason(self):
        self.store.add('book_rejected', T, {'error':'One-sided book'}, valid=False)
        h = tools.health(self.store)
        self.assertEqual(h['rejected_book_fraction'], 1)
        self.assertIn('book_rejected: One-sided book', h['errors_in_last_100_health_or_rejected_records'])

    def test_audit_hash_failure(self):
        self.fill()
        self.store.c.execute("UPDATE records SET sha256='bad' WHERE id=1")
        self.store.c.commit()
        with self.assertRaises(RuntimeError):
            tools.audit(self.store)

    def test_audit_label_valid(self):
        self.store.outcome(metadata(), (T+600)*c.NS)
        self.assertEqual(tools.audit(self.store)['labels_revalidated'], 1)

    def test_audit_label_mismatch(self):
        self.store.outcome(metadata(), (T+600)*c.NS)
        self.store.c.execute('UPDATE outcomes SET up=0')
        self.store.c.commit()
        with self.assertRaises(RuntimeError):
            tools.audit(self.store)

    def test_backup_including_wal_and_reopen(self):
        self.fill()
        out = self.root/'backup.sqlite3'
        result = tools.backup(self.db, out)
        self.assertEqual(result['record_hashes_verified'], 3)
        with tools.reader(out) as s:
            self.assertEqual(s.stats()['records'], self.store.stats()['records'])
        with self.assertRaises(FileExistsError):
            tools.backup(self.db, out)
        with self.assertRaises(FileExistsError):
            tools.backup(self.db, self.db)

    def test_dataset_causal_and_missing(self):
        self.fill()
        self.store.outcome(metadata(), (T+600)*c.NS)
        self.store.remember(T+300)
        out = self.root/'dataset.jsonl'
        result = tools.dataset(self.store, out, lead=8)
        self.assertEqual(result['complete_labeled_windows'], 1)
        rows = [json.loads(x) for x in out.read_text().splitlines()]
        self.assertEqual(rows[1]['target_up'], 1)
        self.assertTrue(rows[1]['complete'])
        self.assertFalse(rows[2]['complete'])
        self.assertIsNone(rows[2]['features']['up_midpoint'])
        self.assertNotIn('target_up', rows[1]['features'])
        self.assertEqual(rows[1]['baseline_up_midpoint'], .5)
        with self.assertRaises(FileExistsError):
            tools.dataset(self.store, out)

    def test_dataset_before_receipt_incomplete(self):
        self.fill()
        out = self.root/'early.jsonl'
        self.assertEqual(tools.dataset(self.store, out, lead=15)['complete_windows'], 0)

    def test_dataset_invalid_lead(self):
        for lead in (0, 300):
            with self.assertRaises(ValueError):
                tools.dataset(self.store, self.root/'no.jsonl', lead)
        self.assertFalse((self.root/'no.jsonl').exists())

    def test_consistent_read_snapshot(self):
        with tools.reader(self.db) as r:
            self.assertEqual(r.c.execute('SELECT count(*) FROM records').fetchone()[0], 0)
            self.fill()
            self.assertEqual(r.c.execute('SELECT count(*) FROM records').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()