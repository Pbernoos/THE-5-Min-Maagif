"""Non-destructive health, backup, integrity and causal dataset tools (v1.1).

Works alongside collector v1.0; opens the source database read-only.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import time

import collector as c


@contextmanager
def reader(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError('Database not found; provide the existing collector database path')
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if db.execute('PRAGMA user_version').fetchone()[0] != 1 or tables != {'records', 'markets', 'outcomes'}:
            raise ValueError('Unsupported database: no migration or changes attempted')
        store = c.Store.__new__(c.Store)
        store.c, store.path = db, path
        # Consistent watermark/counts/features even while the collector writes.
        db.execute('BEGIN')
        yield store
    finally:
        db.close()


def iso(ns):
    return datetime.fromtimestamp(ns / c.NS, timezone.utc).isoformat() if ns else None


def health(store, now_ns=None):
    now_ns = time.time_ns() if now_ns is None else now_ns
    now = now_ns / c.NS
    alerts, feeds = [], {}
    for kind in ('book', 'oracle'):
        row = store.c.execute('SELECT * FROM records WHERE kind=? AND valid=1 AND stored_ns>0 ORDER BY id DESC LIMIT 1', (kind,)).fetchone()
        if row is None:
            feeds[kind] = {'status': 'missing'}
            alerts.append(kind + ': no usable records')
            continue
        d = store.unpack(row)
        receipt_age = (now_ns - d['received_ns']) / c.NS
        source_age = (now_ns - d['source_ns']) / c.NS if d['source_ns'] else None
        status = 'clock_error' if receipt_age < 0 or (source_age is not None and source_age < -2) else ('stale' if receipt_age > 30 or source_age is None or source_age > 30 else 'recent')
        feeds[kind] = dict(status=status, received_utc=iso(d['received_ns']), receipt_age_s=round(receipt_age, 2), source_age_s=round(source_age, 2) if source_age is not None else None)
        if status != 'recent':
            alerts.append(kind + ': ' + status)
    pending = store.c.execute('''SELECT count(*),min(m.window_ts) FROM markets m LEFT JOIN outcomes o USING(window_ts)
        WHERE o.window_ts IS NULL AND m.window_ts+300<=?''', (now,)).fetchone()
    oldest_wait = max(0, now - pending[1] - 300) if pending[1] is not None else None
    if oldest_wait is not None and oldest_wait > 1800:
        alerts.append('Official labels pending over 30 minutes: inspect recent errors; resolution may legitimately be delayed')
    reasons = {}
    for r in store.c.execute("SELECT * FROM records WHERE kind IN ('health','book_rejected','oracle_rejected') ORDER BY id DESC LIMIT 100"):
        p = store.unpack(r)['payload']
        if p.get('error'):
            reason = str(p.get('source', r['kind'])) + ': ' + p['error']
            reasons[reason] = reasons.get(reason, 0) + 1
    counts = store.stats()
    books = counts['records'].get('book', 0)
    rejected = counts['records'].get('book_rejected', 0)
    unmarked = store.c.execute('SELECT count(*) FROM records WHERE stored_ns=0').fetchone()[0]
    if unmarked:
        alerts.append('Unmarked post-commit records excluded from causal features: ' + str(unmarked))
    return dict(version='1.1.0', checked_utc=iso(now_ns), **counts, feeds=feeds,
        pending_closed_markets=pending[0], oldest_pending_age_s=round(oldest_wait, 1) if oldest_wait is not None else None,
        rejected_book_fraction=rejected/(books+rejected) if books+rejected else None,
        errors_in_last_100_health_or_rejected_records=reasons, unmarked_records=unmarked,
        alerts=alerts, note='Latest global feed records only; recent does not prove both sides or complete per-window coverage. No predictive accuracy measured.')


def audit(store):
    check = [r[0] for r in store.c.execute('PRAGMA quick_check')]
    if check != ['ok']:
        raise RuntimeError('SQLite quick_check failed: ' + repr(check))
    count = 0
    for row in store.c.execute('SELECT * FROM records ORDER BY id'):
        store.unpack(row)
        count += 1
    labels = 0
    for row in store.c.execute('SELECT o.window_ts AS label_window,o.up,r.* FROM outcomes o LEFT JOIN records r ON o.record_id=r.id'):
        if row['id'] is None:
            raise RuntimeError('Label has no evidence record')
        d = store.unpack(row)
        p = d['payload']
        if d['kind'] != 'official_outcome' or not d['valid'] or not d['stored_ns'] or d['window_ts'] != p['market']['window'] or d['window_ts'] != row['label_window']:
            raise RuntimeError('Label evidence mismatch')
        # Revalidate settlement metadata, not only the saved normalized label.
        meta = c.market([{'slug': c.slug(row['label_window']), 'markets': [p['market']['raw']]}], row['label_window'])
        if c.official_outcome(meta, d['received_ns']) != row['up'] or p['up'] != row['up']:
            raise RuntimeError('Official label failed revalidation')
        labels += 1
    return dict(quick_check='ok', record_hashes_verified=count, labels_revalidated=labels)


def backup(path, out):
    out = Path(out).resolve()
    # Exclusive creation: never overwrite source or an earlier backup.
    with reader(path) as store:
        with out.open('xb'):
            pass
        target = sqlite3.connect(out)
        try:
            store.c.backup(target, pages=256, sleep=0.05)
        finally:
            target.close()
    with reader(out) as saved:
        result = audit(saved)
    return dict(backup=str(out), **result)


def dataset(store, out, lead=15):
    if not 1 <= lead <= 299:
        raise ValueError('Lead must be between 1 and 299 seconds')
    total = complete = labeled = 0
    watermark = store.c.execute('SELECT coalesce(max(id),0) FROM records').fetchone()[0]
    with Path(out).open('x', encoding='utf-8') as f:
        f.write(c.canonical(dict(type='manifest', schema='causal-market-dataset-v1', max_record_id=watermark,
            lead_s=lead, created_ns=time.time_ns(), source=c.SOURCE,
            note='Retrospective assembly of received pre-start observations, NOT frozen live forecasts. Labels are targets only. Missing data retained.')) + '\n')
        for row in store.c.execute('SELECT m.window_ts,o.up FROM markets m LEFT JOIN outcomes o USING(window_ts) ORDER BY m.window_ts'):
            t = row['window_ts']
            cutoff = (t-lead)*c.NS
            a = store.asof(t, cutoff)
            features, evidence = {}, {}
            for side in ('Up', 'Down'):
                b = a['books'].get(side)
                for k in ('bid', 'ask', 'midpoint', 'spread', 'depth_imbalance_20', 'bid_depth_20', 'ask_depth_20'):
                    features[side.lower()+'_'+k] = b[k] if b else None
                evidence[side] = b['record_id'] if b else None
            o = a['oracle']
            features['oracle_price'] = o['price'] if o else None
            evidence['oracle'] = o['record_id'] if o else None
            # Labels never enter features, completeness, or the market midpoint baseline.
            f.write(c.canonical(dict(type='window', window=t, cutoff_ns=cutoff, complete=a['complete'],
                features=features, record_ids=evidence, target_up=row['up'],
                baseline_up_midpoint=features['up_midpoint'], baseline_neutral=0.5)) + '\n')
            total += 1
            complete += int(a['complete'])
            labeled += int(a['complete'] and row['up'] is not None)
    return dict(export=str(out), windows=total, complete_windows=complete, complete_labeled_windows=labeled,
        note='Chronological evaluation still required; no accuracy or trading edge claimed')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['health', 'audit', 'backup', 'dataset'])
    p.add_argument('--db', default='data/market.sqlite3')
    p.add_argument('--out')
    p.add_argument('--lead', type=int, default=15)
    a = p.parse_args()
    if a.command in ('backup', 'dataset') and not a.out:
        p.error('--out is required and must be a NEW file')
    try:
        if a.command == 'backup':
            result = backup(a.db, a.out)
        else:
            with reader(a.db) as store:
                result = health(store) if a.command == 'health' else audit(store) if a.command == 'audit' else dataset(store, a.out, a.lead)
        print(json.dumps(result, indent=2, allow_nan=False))
    except (ValueError, RuntimeError, OSError, sqlite3.Error) as e:
        p.exit(1, 'Not completed: ' + str(e) + '\nSource data was not intentionally modified; keep any partial output for inspection.\n')


if __name__ == '__main__':
    main()