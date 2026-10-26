"""Prepare research-only +1/+2/+3-minute TWAP targets at five-minute starts.

Uses a collector SQLite snapshot read-only. Never fits a model or places orders.
"""
import argparse
from collections import Counter
from decimal import Decimal
import json
from pathlib import Path
import time

import collector as c
import tools

HORIZONS = (60, 120, 180)


def point_index(store, windows):
    wanted = {t+h for t in windows for h in (0,)+HORIZONS}
    points, conflicts = {}, set()
    for row in store.c.execute("SELECT * FROM records WHERE kind='oracle' AND valid=1 AND stored_ns>0 ORDER BY id"):
        r = store.unpack(row)
        if r['stored_ns'] < r['received_ns']:
            raise ValueError('Oracle evidence has impossible availability timestamps')
        # Revalidate the archived raw provider message, rather than trusting only
        # a derived normalized point list. Snapshots are target evidence, not
        # evidence that historic observations were known before their receipt.
        for p in c.oracle_points(r['payload']['raw'], r['received_ns']):
            second = p['source_ns']//c.NS
            if second not in wanted or p['source_ns'] != second*c.NS:
                continue
            exact = p['full_accuracy_value']
            if exact is None:
                continue
            d = dict(source_ns=p['source_ns'], exact=exact, record_id=r['id'],
                received_ns=r['received_ns'], available_ns=r['stored_ns'])
            if second in points and Decimal(points[second]['exact']) != Decimal(exact):
                conflicts.add(second)
            if second not in points or d['available_ns'] < points[second]['available_ns']:
                points[second] = d
    return points, conflicts


def features(store, t):
    cutoff = t*c.NS-1
    current = store.asof(t, cutoff)
    x, evidence = {}, {}
    for side in ('Up', 'Down'):
        b = current['books'].get(side)
        for name in ('bid', 'ask', 'midpoint', 'spread', 'depth_imbalance_20', 'bid_depth_20', 'ask_depth_20'):
            x[side.lower()+'_'+name] = b[name] if b else None
        evidence[side] = b['record_id'] if b else None
    o = current['oracle']
    x['twap_price'] = o['price'] if o else None
    evidence['oracle'] = o['record_id'] if o else None
    for lag in (60, 120):
        past = store.asof(t, cutoff-lag*c.NS)['oracle']
        x['twap_return_'+str(lag)+'s'] = o['price']/past['price']-1 if o and past else None
        evidence['oracle_lag_'+str(lag)] = past['record_id'] if past else None
    complete = current['complete'] and all(v is not None for v in x.values())
    return dict(cutoff_ns=cutoff, features=x, feature_record_ids=evidence, features_complete=complete)


def prepare(store, out):
    windows = [r[0] for r in store.c.execute('SELECT window_ts FROM markets ORDER BY window_ts')]
    points, conflicts = point_index(store, windows)
    counts = Counter(windows=len(windows))
    watermark = store.c.execute('SELECT coalesce(max(id),0) FROM records').fetchone()[0]
    with Path(out).open('x', encoding='utf-8') as f:
        f.write(c.canonical(dict(type='manifest', schema='start-window-twap-horizons-v1', created_ns=time.time_ns(),
            max_record_id=watermark, horizons_s=list(HORIZONS), source=c.SOURCE,
            decision='window_start_minus_1ns', target='TWAP(window_start+h) versus TWAP(window_start)',
            note='Exact source seconds and full_accuracy_value only; no interpolation. Targets may arrive later and never enter features. Retrospective reconstruction, not frozen live forecasts.'))+'\n')
        for t in windows:
            row = dict(type='window', window=t, **features(store, t))
            targets = {}
            for h in HORIZONS:
                base, end = points.get(t), points.get(t+h)
                status = 'conflicting_source' if t in conflicts or t+h in conflicts else 'missing_exact_source' if not base or not end else 'ready'
                target = dict(status=status, direction=None, up=None, available_ns=None, evidence=None)
                if status == 'ready':
                    change = Decimal(end['exact'])-Decimal(base['exact'])
                    direction = 'up' if change > 0 else 'down' if change < 0 else 'flat'
                    target.update(direction=direction, up=int(change > 0) if change else None,
                        available_ns=max(base['available_ns'], end['available_ns']),
                        evidence=dict(reference=base, target=end))
                targets[str(h)] = target
                counts[str(h)+'s_'+status] += 1
                if row['features_complete'] and target['up'] is not None:
                    counts[str(h)+'s_trainable'] += 1
            row['targets'] = targets
            counts['complete_feature_windows'] += int(row['features_complete'])
            f.write(c.canonical(row)+'\n')
    return dict(export=str(out), counts=dict(counts), conflicting_source_seconds=len(conflicts),
        model_trained=False, note='Separate direction tasks; these are not five-minute contract settlement labels or buy signals.')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db', required=True)
    p.add_argument('--out', required=True, help='A new JSONL file; never overwritten')
    a = p.parse_args()
    with tools.reader(a.db) as store:
        result = prepare(store, a.out)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()