# Prospective market-data collector

Read-only data collection for the BTC five-minute Polymarket study. **No wallet,
orders, trained model, accuracy promise, or automatic website change.**

## What is collected

- Current and next five-minute markets, with exact Gamma token/condition IDs,
  start/end times and settlement configuration. A different feed/configuration
  is rejected, not silently substituted.
- Up and Down REST order-book snapshots every five seconds (configurable, minimum
  two seconds). Raw book payloads are preserved; sorted top-20 depth, bid/ask,
  spread, midpoint and depth imbalance are derived. Empty/one-sided/crossed or
  mismatched books are archived as rejected, never invented. A quote midpoint is
  a baseline, not a guaranteed fill or calibrated outcome probability.
- Polymarket RTDS `crypto_prices_twap_sixty`, `btc/usd`, `window_s=60` over
  `wss://ws-live-data.polymarket.com/`. This is the public 60-second TWAP topic
  matching the accepted market's Chainlink TWAP resolution metadata, **not**
  Coinbase spot, the ordinary instant-price topic, or a direct authenticated
  Chainlink Data Streams connection. Its identity is metadata-checked, not a
  cryptographic proof of settlement. Official labels come separately from Gamma.
- Exchange/source timestamps, local receipt timestamps, conservative post-commit
  availability timestamps (UTC nanoseconds), raw normalized-JSON SHA256, and health
  failures. The exact `full_accuracy_value` string is retained when supplied.
- Official binary outcomes after closed+resolved and matching settlement rules.
  Pending labels remain pending; conflicting labels stop capture, preserving the
  original. Previously observed unlabeled markets are retried after restart.

Snapshots are not a trade-by-trade or full order-event stream. Do not claim that
snapshot differences reconstruct complete order flow. Oracle snapshots can
contain older observations: **their availability is the current receipt time**, not
the old source time. No missed start price is fabricated from later data.

## Start on Windows

Extract this ZIP into a **new folder** (do not overwrite your existing app), open
PowerShell there, and run:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe collector.py collect
```

Requires Python 3.11 or later. Keep the computer awake, clock synchronized, and
terminal running. Ctrl+C stops safely. Re-running the last command resumes the same
database. These commands are prepared for Windows; execution was tested on Linux,
not Windows. No system service or startup task is installed automatically.

## Linux / always-on server

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python collector.py collect
```

A server still needs durable disk, a process supervisor, clock sync and monitoring.
This package does **not** provision hosting, create an always-on job, or run on
GitHub Pages. If a source returns HTTP401/403 it stops; it does not bypass access
restrictions. Public endpoints may fail or change. Restart/health status must be
monitored. The smoke test is not a long-running reliability guarantee.

## Storage / export

The default is a NEW `data/market.sqlite3` with SQLite WAL and full synchronous
commits. **Do not point this at the older app's shadow database.** Unknown schemas
are rejected. Payload rows are append-only; a second write marks post-commit
availability. A crash before marking leaves the record ineligible as a feature.
There is a conservative 1GiB cap including WAL/SHM: capture stops at capacity,
**nothing is automatically deleted**. Provision/monitor disk and back it up;
increase capacity explicitly with `--max-mb 4096` if appropriate. Do not copy only
the DB file while it is running; use the export, a SQLite-aware backup, or stop
the collector before backing up. Never upload a live WAL database directly.

```powershell
.\.venv\Scripts\python.exe collector.py status
.\.venv\Scripts\python.exe collector.py export --out market-export-001.jsonl
```

Exports verify each record hash and use a fixed maximum record ID so a running
collector can continue. An existing output file is never overwritten. Exported
rows include raw payloads, source mappings, labels, errors and timing evidence;
the manifest states the schema, source and watermark. JSON is canonicalized from
parsed provider payloads; this is not a byte-for-byte HTTP packet capture.

To send data back for analysis, log the stopped/exported JSONL file as a W&B
dataset artifact in `pbernoos-university-of-michigan/wandb_agent_default_project`
and share its artifact link with ARIA. No automatic upload or API key is included.
An optional separate W&B upload uses the normal SDK, e.g.:

```python
import wandb
with wandb.init(entity="pbernoos-university-of-michigan",
                project="wandb_agent_default_project", job_type="data-upload") as run:
    artifact = wandb.Artifact("btc-prospective-marketdata", type="dataset")
    artifact.add_file("market-export-001.jsonl")
    run.log_artifact(artifact)
```

Install/authenticate the `wandb` SDK separately for that optional upload. Only
market data is collected, but decide whether the timing/activity metadata should
be shared with your project team before uploading.

## No-lookahead feature assembly

`features` is a dataset diagnostic, **not a forecast**:

```bash
python collector.py features --window 1792810800 --lead 15
```

Substitute an actually collected market's Unix start. The cutoff is 15 seconds
before that start. Each selected payload must have source time at/before the
cutoff, receipt and post-commit availability at/before the cutoff, and source and
receipt age no more than 10 seconds. Both market sides and the oracle must be
present to mark the row complete. Missing input remains missing. Opening/closing
oracle values and final outcomes are not pre-start features. No random split,
shuffled evaluation or retrospective fake prediction is supplied.

## Verification and next research

```bash
python -m unittest -v test_collector
```

See `verification.json` for actual fixture/live checks and their limits. A short
live sample is included for inspection, not as enough training data. This release
does not train or promote a predictor. Collect several weeks with known coverage,
freeze a chronological training/validation/future-test plan, and benchmark new
market+oracle features against the same-window pre-start market midpoint and
candle heuristic. Better inputs may help; dependable accuracy is not established.