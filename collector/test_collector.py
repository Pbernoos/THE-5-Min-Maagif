import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import collector as c

T=1792766400
NOW=(T-10)*c.NS

def metadata():
    from datetime import datetime,timezone
    iso=lambda t:datetime.fromtimestamp(t,timezone.utc).isoformat()
    return dict(window=T,condition_id='0xabc',tokens={'Up':'123','Down':'456'},raw={
        'slug':c.slug(T),'outcomes':'["Up","Down"]','clobTokenIds':'["123","456"]',
        'conditionId':'0xabc','resolutionSource':c.SOURCE,'eventStartTime':iso(T),'endDate':iso(T+300),
        'cryptoMarketConfig':dict(asset='btc',duration='5m',twapEnabled=True,twapLookbackSeconds=60),
        'closed':True,'umaResolutionStatus':'resolved','outcomePrices':'["1","0"]'})

def book(side='Up'):
    return dict(asset_id='123' if side=='Up' else '456',market='0xabc',timestamp=str((T-11)*1000),
        bids=[{'price':'.48','size':'4'},{'price':'.45','size':'8'}],
        asks=[{'price':'.52','size':'6'},{'price':'.55','size':'9'}])

def oracle(t=T-11):
    return dict(topic=c.TOPIC,type='subscribe',payload=dict(symbol='btc/usd',window_s=60,
        data=[dict(timestamp=t*1000,value=80000.,full_accuracy_value='80000000000000000000000')]))

class ParseTests(unittest.TestCase):
    def test_market(self):
        m=metadata();result=c.market([{'slug':c.slug(T),'markets':[m['raw']]}],T)
        self.assertEqual(result['tokens'],m['tokens'])
    def test_market_rejects_wrong_source(self):
        m=metadata();m['raw']['resolutionSource']='coinbase'
        with self.assertRaises(ValueError):c.market([{'slug':c.slug(T),'markets':[m['raw']]}],T)
    def test_market_rejects_wrong_twap(self):
        m=metadata();m['raw']['cryptoMarketConfig']['twapLookbackSeconds']=1
        with self.assertRaises(ValueError):c.market([{'slug':c.slug(T),'markets':[m['raw']]}],T)
    def test_market_rejects_duplicate_tokens(self):
        m=metadata();m['raw']['clobTokenIds']='["123","123"]'
        with self.assertRaises(ValueError):c.market([{'slug':c.slug(T),'markets':[m['raw']]}],T)
    def test_sort_spread_depth(self):
        b=c.parse_book(book(),metadata(),'Up',NOW)
        self.assertAlmostEqual(b['midpoint'],.5);self.assertAlmostEqual(b['spread'],.04)
        self.assertEqual(b['bid_depth_20'],12);self.assertAlmostEqual(b['depth_imbalance_20'],-3/27)
    def test_rejects_cross(self):
        b=book();b['bids'][0]['price']='.6'
        with self.assertRaises(ValueError):c.parse_book(b,metadata(),'Up',NOW)
    def test_rejects_wrong_token(self):
        with self.assertRaises(ValueError):c.parse_book(book(),metadata(),'Down',NOW)
    def test_rejects_wrong_condition(self):
        b=book();b['market']='wrong'
        with self.assertRaises(ValueError):c.parse_book(b,metadata(),'Up',NOW)
    def test_rejects_nan(self):
        b=book();b['bids'][0]['size']='NaN'
        with self.assertRaises(ValueError):c.parse_book(b,metadata(),'Up',NOW)
    def test_rejects_empty(self):
        b=book();b['asks']=[]
        with self.assertRaises(ValueError):c.parse_book(b,metadata(),'Up',NOW)
    def test_future_book(self):
        b=book();b['timestamp']=str((T+10)*1000)
        with self.assertRaises(ValueError):c.parse_book(b,metadata(),'Up',NOW)
    def test_missing_source_time(self):
        b=book();b.pop('timestamp')
        with self.assertRaises(KeyError):c.parse_book(b,metadata(),'Up',NOW)
    def test_oracle(self):
        p=c.oracle_points(oracle(),NOW)[0]
        self.assertEqual(p['source_ns'],(T-11)*c.NS);self.assertEqual(p['price'],80000.)
    def test_wrong_oracle_symbol(self):
        raw=oracle();raw['payload']['symbol']='btc/usdt'
        with self.assertRaises(ValueError):c.oracle_points(raw,NOW)
    def test_wrong_oracle_topic(self):
        raw=oracle();raw['topic']='crypto_prices_chainlink'
        with self.assertRaises(ValueError):c.oracle_points(raw,NOW)
    def test_wrong_oracle_window(self):
        raw=oracle();raw['payload']['window_s']=1
        with self.assertRaises(ValueError):c.oracle_points(raw,NOW)
    def test_future_oracle(self):
        with self.assertRaises(ValueError):c.oracle_points(oracle(T+1),NOW)
    def test_oracle_snapshot_expired(self):
        with self.assertRaises(ValueError):c.oracle_points(oracle(T-1000),NOW)
    def test_unresolved_not_label(self):
        m=metadata();m['raw']['umaResolutionStatus']='proposed'
        self.assertIsNone(c.official_outcome(m,(T+400)*c.NS))
    def test_label_needs_exact_binary(self):
        m=metadata();m['raw']['outcomePrices']='[".99",".01"]'
        self.assertIsNone(c.official_outcome(m,(T+400)*c.NS))
    def test_premature_not_label(self):self.assertIsNone(c.official_outcome(metadata(),NOW))
    def test_official_label(self):self.assertEqual(c.official_outcome(metadata(),(T+400)*c.NS),1)

class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=c.Store(Path(self.tmp.name)/'sample.db')
    def tearDown(self):self.store.close();self.tmp.cleanup()
    def add(self,kind,t,payload,received=NOW-2*c.NS,stored=NOW-c.NS):
        with patch('collector.time.time_ns',return_value=stored):return self.store.add(kind,t,payload,received)
    def valid_data(self,received=NOW-2*c.NS,stored=NOW-c.NS):
        for side in ['Up','Down']:
            b=c.parse_book(book(side),metadata(),side,received)
            self.add('book',T,dict(normalized=b,raw=book(side)),received,stored)
        raw=oracle();self.add('oracle',None,dict(raw=raw,points=c.oracle_points(raw,received)),received,stored)
    def test_asof_complete(self):
        self.valid_data();f=self.store.asof(T,NOW)
        self.assertTrue(f['complete']);self.assertEqual(f['oracle']['price'],80000.)
    def test_receipt_after_cutoff_excluded(self):
        self.valid_data(NOW+1,NOW+2);self.assertFalse(self.store.asof(T,NOW)['complete'])
    def test_durable_storage_after_cutoff_excluded(self):
        self.valid_data(NOW-1,NOW+1);self.assertFalse(self.store.asof(T,NOW)['complete'])
    def test_snapshots_do_not_backdate_availability(self):
        self.valid_data(NOW+1,NOW+2)
        self.assertIsNone(self.store.asof(T,NOW)['oracle'])
    def test_poststart_rejected(self):
        with self.assertRaises(ValueError):self.store.asof(T,T*c.NS)
    def test_stale_excluded(self):
        self.valid_data();self.assertFalse(self.store.asof(T+300,(T+295)*c.NS)['complete'])
    def test_payload_integrity(self):
        i=self.add('test',T,{'x':1});row=self.store.c.execute('SELECT * FROM records WHERE id=?',(i,)).fetchone()
        self.assertEqual(self.store.unpack(row)['payload'],{'x':1})
        self.store.c.execute('UPDATE records SET sha256=? WHERE id=?',('bad',i))
        with self.assertRaises(RuntimeError):self.store.unpack(self.store.c.execute('SELECT * FROM records WHERE id=?',(i,)).fetchone())
    def test_restart_preserves(self):
        self.valid_data();path=self.store.path;self.store.close();self.store=c.Store(path)
        self.assertTrue(self.store.asof(T,NOW)['complete'])
    def test_full_storage_never_deletes(self):
        self.valid_data();n=self.store.stats()['records'];self.store.max_bytes=0
        with self.assertRaises(RuntimeError):self.add('test',T,{'x':1})
        self.assertEqual(self.store.stats()['records'],n)
    def test_backward_clock_stops(self):
        with patch('collector.time.time_ns',return_value=NOW):
            with self.assertRaises(RuntimeError):self.store.add('test',T,{},NOW+1)
    def test_label_conflict_preserves(self):
        self.store.outcome(metadata(),(T+400)*c.NS)
        m=metadata();m['raw']['outcomePrices']='["0","1"]'
        with self.assertRaises(RuntimeError):self.store.outcome(m,(T+400)*c.NS)
        self.assertEqual(self.store.c.execute('SELECT up FROM outcomes').fetchone()[0],1)
    def test_pending_survives_restart(self):
        self.store.remember(T);self.assertEqual(self.store.pending(T+500),[T])
        self.store.defer(T,T+500);self.assertEqual(self.store.pending(T+600),[])
    def test_uncommitted_marker_excluded(self):
        self.valid_data();self.store.c.execute('UPDATE records SET stored_ns=0');self.store.c.commit()
        self.assertFalse(self.store.asof(T,NOW)['complete'])
    def test_foreign_database_untouched(self):
        import sqlite3,hashlib
        path=Path(self.tmp.name)/'unrelated.db'
        with sqlite3.connect(path) as con:con.execute('CREATE TABLE important(x TEXT)')
        con.close()
        before=hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaises(ValueError):c.Store(path)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)
    def test_unknown_version_rejected(self):
        self.store.c.execute('PRAGMA user_version=2');self.store.c.commit()
        with self.assertRaises(ValueError):c.Store(self.store.path)
        self.assertEqual(self.store.c.execute('PRAGMA user_version').fetchone()[0],2)
    def test_invalid_window_rejected(self):
        with self.assertRaises(ValueError):self.store.asof(-300,-400*c.NS)

if __name__=='__main__':unittest.main()