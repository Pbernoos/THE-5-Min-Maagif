# Collector toolkit v1.1 — keep your current data

This is an additive reliability/data-quality upgrade, not a better prediction
model. The original collector.py is unchanged. No website deployment, trading,
automatic restart task, paid compute, data deletion, or automatic uploads.

## Existing Windows installation (recommended)

1. Leave the running collector alone. Extract this archive into a NEW folder.
2. Copy ONLY `tools.py` into your existing collector folder, next to
   `collector.py`. Do not replace your `data` folder or its database.
3. Open a SECOND PowerShell window in your original collector folder and run:

```powershell
.\.venv\Scripts\python.exe tools.py health
```

Paste that report into chat. It shows source/receipt freshness, closed markets
awaiting labels, oldest label wait, recent rejection/error reasons, and storage.
A >30-minute label wait is a diagnostic warning, not proof of a bug: official
resolution may legitimately be delayed. Latest global feed freshness alone
does not prove both book sides or complete coverage at every decision cutoff.

If your database is elsewhere, pass `--db "D:\path\market.sqlite3"`.
Tools open the source using SQLite read-only mode. They do not migrate schemas
or change label schedules. Running them can affect disk/CPU load.

## Safe backup, including live SQLite WAL data

```powershell
.\.venv\Scripts\python.exe tools.py backup --out backup-001.sqlite3
```

Uses the SQLite backup API, not a raw copy of the main DB file. The new backup
is checked for SQLite integrity, every payload hash and official-label evidence.
Existing output paths are refused. Choose a new name each time. Allow enough
disk space for another full database; nothing is deleted automatically. If a
backup fails, preserve the partial output for inspection and retry to a NEW name.
For large databases, stop collection cleanly first or work from a backup to
reduce contention and avoid pinning the collector's WAL during long reads.

```powershell
.\.venv\Scripts\python.exe tools.py audit --db backup-001.sqlite3
.\.venv\Scripts\python.exe tools.py dataset --db backup-001.sqlite3 --lead 15 --out training-candidates-001.jsonl
```

## What the dataset is (and isn't)

- One row per observed market in chronological order, including missing rows.
- Fixed decision cutoff 15 seconds BEFORE market start by default; the existing
  collector's source, receipt, durable-payload-commit and freshness guards apply.
- Up/Down bid, ask, midpoint, spread, top-20 depth imbalance/depth and oracle price;
  source record IDs allow joining back to the raw evidence in the backup/export.
- Official label is a separate target, never part of features. Pending stays null.
- Neutral probability and Up midpoint baselines retained; midpoint is not a
  guaranteed executable fill, calibrated probability or profitable strategy.
- Counts complete/labeled windows so collection volume isn't mistaken for
  training-ready coverage. The manifest pins the snapshot's record watermark.
- This is RETROSPECTIVE causal assembly, NOT a journal of frozen live forecasts.
  Do not call it prospective model performance. No automatic training or scoring.

Before a model change: preserve a chronological future holdout, fit preprocessing
only on training data, compare against neutral AND market midpoint, report Brier,
calibration and time-block uncertainty, and do not promote on a tiny sample.
The last tested candidate did NOT beat the current browser heuristic on the
136-window comparison. Previously viewed holdouts are development data now.

## Fresh Windows install only

`start-windows.cmd` looks for `python`, then `py`, creates a local venv if needed,
installs the pinned requirements only on setup, and starts the collector. No
PowerShell execution-policy change, admin privileges, service, sleep-setting
change or secrets needed. Do NOT use it to start a second collector alongside
your current process. Its Windows execution has not been tested here.

## Verification

52 automated tests pass on Linux: the original 38 collector tests plus 14 toolkit
tests covering read-only access, stale/missing feeds, pending labels, rejection
reasons, backup/WAL recovery, hash corruption, label revalidation, snapshot
consistency, no output overwrite, pre-cutoff data and missing-value handling.
The toolkit was also checked against the earlier real-feed smoke database.
No access to your Windows database, Windows runtime test, long-running soak,
new model accuracy result or dashboard update is claimed.