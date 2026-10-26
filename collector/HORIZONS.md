# Research specification: one forecast per five-minute start

User-selected timing: at each window start `t`, produce three independent
probabilities for `+60`, `+120`, `+180` seconds. These forecast the matching
Polymarket 60-second BTC TWAP, NOT instantaneous Coinbase BTC or the five-minute
contract settlement. Outputs must be visibly labelled as forecasts, not actual
future paths. Their directions do not identify a guaranteed price turning point.

## Features versus targets

- Freeze inputs at `t-1ns`; only actually received and payload-committed data
  before that cutoff is eligible. Existing 10-second source/receipt freshness
  guards apply. Books must belong to this market and both sides must exist.
- Features: Up/Down bid/ask/midpoint/spread/top-20 depth/imbalance, recent TWAP
  and causal 60s/120s TWAP returns. Missing values stay missing; incomplete
  feature windows are not used by the first baseline.
- Target at horizon `h`: compare the exact `full_accuracy_value` at source
  timestamp `t+h` to the exact value at `t`. Up, Down and exact Flat are retained.
  Flat is not silently relabelled Up; the initial binary research baseline
  excludes Flat and reports its count. A later three-class model may include it.
- Exact provider observations only: no interpolation, fabricated start values,
  source substitution or float-based rounding of exact targets. Missing/conflicting
  source seconds are flagged, not filled. Earliest archived availability is
  retained. Later-arriving target observations are allowed as labels, never features.
- Sources: existing metadata-checked `crypto_prices_twap_sixty` BTC feed. These
  are NOT cryptographically authenticated direct Chainlink settlement labels.
- Dataset assembly is retrospective causal reconstruction, NOT evidence that
  the live browser emitted those predictions. Actual live forecasts need an
  immutable timestamped journal after a model is frozen.

## First bounded training experiment (not run yet)

Sandbox CPU; no paid GPUs. Three separate standard-scaled logistic regressions,
one per horizon, fixed C=0.1, max_iter=1000, seed=42. Preprocessing fitted on
training data only. No hyperparameter sweep. Primary score: per-horizon Brier;
also log log-loss, accuracy, calibration and coverage. Baselines: neutral 0.5,
training-only outcome frequency and training-frozen momentum direction.
Do not misuse five-minute contract midpoint as a three-minute direction baseline.

Chronological window groups: first60% train, next20% validation, final20% test;
all three horizon rows for a window stay in one split. Training target evidence
must have been available before validation starts; calibration/selection evidence
must have been available before test starts. Drop unavailable boundary labels
rather than leaking later knowledge. Retain a future live shadow period beyond
this retrospective test. No model promotion or confidence-threshold tuning on test.

Before fitting, inspect sample counts and coverage; a tiny dataset is a plumbing
check, not accuracy evidence. Report temporal uncertainty (UTC-day clusters when
enough days exist) and note when too few days make reliable intervals impossible.
Never treat 3 horizons from one window as 3 independent market observations.

An entry assessment is separate: it needs a properly tested five-minute
settlement probability, executable ask prices, fees/spread/slippage and uncertainty.
A predicted +3-minute rise is NOT automatically a Buy Up signal. No automatic
orders or wallet integration. Current display and model remain unchanged.

## Share collected data from Windows

Download these files next to the existing `collector.py` and `tools.py`:
`horizon_dataset.py`, `upload_horizon_data.py`, `HORIZONS.md`.
The upload requires the optional `wandb` package and your normal W&B login.
Never paste your API key into chat or commit it to GitHub.

For large databases, Ctrl+C the collector first to reduce disk contention;
it preserves data. This is stopping a process, not deleting the database.
In PowerShell, from your original collector folder:

```powershell
.\.venv\Scripts\python.exe tools.py backup --out horizon-backup-001.sqlite3
.\.venv\Scripts\python.exe -m pip install wandb
.\.venv\Scripts\python.exe -m wandb login
.\.venv\Scripts\python.exe upload_horizon_data.py --db horizon-backup-001.sqlite3 --out horizon-data-001.jsonl
```

Use NEW filenames on every export/backup; existing files are refused. Allow space
for the backup and JSONL. Inspect the printed coverage counts. Upload creates
a `data-upload` run and dataset artifact in
`pbernoos-university-of-michigan/wandb_agent_default_project`; the project team
can access the market records and timing metadata. Share its run link with ARIA.

If you stopped collection, resume it afterwards using the existing command:

```powershell
.\.venv\Scripts\python.exe collector.py collect
```

Windows commands are prepared, not executed or verified on your computer.
No model has been trained by these tools. They do not change the website,
install a background service, place trades or delete any existing data.