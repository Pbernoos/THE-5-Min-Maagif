"""Validate a stopped/SQLite-aware backup and share it for three-horizon research.

Creates a W&B dataset artifact/run in the established project. No model training,
website changes, deletion or trading. Run only on a completed backup, not live DB.
"""
import argparse
import hashlib
import json
from pathlib import Path

import horizon_dataset
import tools


def digest(path):
    sha = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024), b''):
            sha.update(block)
    return sha.hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db', required=True, help='Completed SQLite backup, NOT live collector DB')
    p.add_argument('--out', required=True, help='New derived JSONL filename')
    a = p.parse_args()
    try:
        import wandb
    except ImportError:
        p.error('Install the optional upload SDK: python -m pip install wandb')
    db = Path(a.db).resolve()
    if not db.is_file():
        p.error('Backup not found; use tools.py backup first')
    if Path(str(db)+'-wal').exists() and Path(str(db)+'-wal').stat().st_size:
        p.error('Database has a WAL: use a completed SQLite-aware backup, not a live database')
    initial = digest(db)
    with tools.reader(db) as store:
        audit = tools.audit(store)
        prepared = horizon_dataset.prepare(store, a.out)
    if digest(db) != initial:
        p.error('Backup changed during preparation; no upload started. Create a stable backup.')
    print(json.dumps(dict(audit=audit, dataset=prepared), indent=2), flush=True)
    print('Uploading market data and timing metadata to your W&B project team. No model is being trained.', flush=True)
    with wandb.init(entity='pbernoos-university-of-michigan', project='wandb_agent_default_project',
        name='btc-three-horizon-data-upload', job_type='data-upload',
        config=dict(database_sha256=initial, schema='start-window-twap-horizons-v1',
            horizons_seconds=[60,120,180], model_trained=False)) as run:
        artifact = wandb.Artifact('btc-prospective-marketdata', type='dataset',
            description='Collector SQLite backup plus pre-start features and exact +1/+2/+3-minute TWAP targets; not live forecasts.',
            metadata=dict(database_sha256=initial, audit=audit, preparation=prepared))
        artifact.add_file(str(db), name='collector-backup.sqlite3')
        artifact.add_file(a.out, name='horizon-dataset.jsonl')
        for name in ('horizon_dataset.py','tools.py','collector.py','HORIZONS.md'):
            artifact.add_file(str(Path(__file__).parent/name), name='source/'+name)
        logged = run.log_artifact(artifact)
        logged.wait()
        run.summary.update(prepared['counts'])
        print('Artifact: pbernoos-university-of-michigan/wandb_agent_default_project/'+logged.name, flush=True)
        print('Run: '+run.url, flush=True)
    print('Upload completed. Share the run link with ARIA to verify it and start training.', flush=True)


if __name__ == '__main__':
    main()