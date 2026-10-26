# DeepSeek explanation layer (optional local backend)

Model: `deepseek-ai/DeepSeek-V4.1-Flash`, verified in this account's Forge Inference
catalog on 2026-10-26. Integration code is prepared; no paid completion, model
training, forecasting-accuracy test or Windows runtime test was performed here.

## Its deliberately limited role

The numerical model owns the +1/+2/+3-minute probabilities. DeepSeek may only rank
up to three evidence-backed explanation notes. Notes are rendered locally from
approved text. It cannot change probabilities, invent a forecast, supply a new
price, add a free-form trading narrative or issue orders. Every explanation keeps
the research-only, direction-versus-settlement and entry-cost cautions visible.

This initial constrained approach prevents plausible-sounding but ungrounded
reasoning. It is not a new predictive feature or evidence of better accuracy.
It does not attempt to infer the numerical model's causal reasoning.

## What is ready versus missing

- Ready: standard-library Python local HTTP backend and panel, forecast-input
  validation, server-side Inference client, bounded calls, caching, approved-note
  validation and deterministic fallback. No new dependency installation required.
- Missing: trained/validated three-horizon numerical model, its actual immutable
  forecast journal and automatic connection of that journal to this panel.
- Your public GitHub Pages dashboard is unchanged. It cannot safely store an API
  key. This is a separate local panel, NOT a deployed cloud backend or a bridge
  allowing the public website to call localhost. No CORS access is granted.

## Safe local check — zero model calls

Download `deepseek_explainer.py` next to your collector. From PowerShell:

```powershell
.\.venv\Scripts\python.exe deepseek_explainer.py --forecast data/current-horizon-forecast.json
```

Open `http://127.0.0.1:8766`. If there is no actual current forecast, the panel
reports waiting; it never fabricates example forecasts. A training-target dataset
is NOT a forecast file. Do not make up probabilities to activate the panel.

## Enable paid explanations only when real forecasts are connected

```powershell
.\.venv\Scripts\python.exe deepseek_explainer.py --forecast data/current-horizon-forecast.json --allow-paid-inference --max-calls 3
```

The server uses `WANDB_API_KEY` when set, otherwise prompts for the W&B key with
hidden input. It keeps the key in process memory, never returns it to the browser,
never writes it into source/config, and sends it only to
`https://api.inference.wandb.ai/v1/chat/completions`. Do not put keys in GitHub,
HTML, forecast files or chat. A proxy endpoint/alternate host cannot be configured.
Redirects are refused. Usage is attributed to
`pbernoos-university-of-michigan/wandb_agent_default_project`.

Each click may consume Inference credits. Defaults: max3 outbound attempts per
server session, max512 output tokens/request, 10s request timeout, no automatic
retry. Both successful and failed responses are cached for the same forecast.
Restarting resets the session cap; this is not an account-wide monetary cap.
Failed requests/timeouts may still be billed. Pricing/credits/region/capacity
availability is not established merely by model-catalog availability.

No model call occurs on page load, when forecasts are missing/invalid/expired,
without paid opt-in, or without credentials. The bounded model request contains
only probabilities and eligible note text, not credentials or raw collector data.
Model identity, completion status and returned codes must pass validation;
otherwise the UI clearly labels deterministic local fallback. Token usage is
shown if supplied, not converted into an unsupported cost estimate.

## Forecast contract for future numerical-model integration

The server reads ONLY the explicit server-side `--forecast` path, not a filename
or prompt supplied by a browser. Maximum16KB JSON. Required keys only:

| Key | Meaning |
|---|---|
| `schema` | `frozen-horizon-forecast-v1` |
| `window` | Positive epoch seconds, multiple300, current five-minute window |
| `cutoff_ns` | Actual pre-start input cutoff, within30seconds before start |
| `generated_ns` | Actual completion time, cutoff <= generation <= window start |
| `model_version` | Short alphanumeric/dot/underscore/colon/hyphen identifier |
| `probabilities` | Numeric `60`, `120`, `180` Up probabilities in[0,1] |
| `data_complete` | Must be true |
| `research_only` | Must be true |

The numeric model must precompute with the real earlier cutoff and complete by
start; do not timestamp later predictions as earlier. A forecast generated after
start is rejected. Explanations may arrive later, but they never become new
predictions. Forecast freshness is checked on every click, including cache hits.
Schema/timestamp validation is NOT cryptographic proof that a file is genuine;
production wiring must use the numerical model's immutable journal, not manual
edits. The current training pipeline has not produced this journal yet.

## Local security and tests

Binds only127.0.0.1; checks exact Host and POST Origin; no arbitrary request data,
URL fetching, file serving, endpoint overrides, key persistence or CORS. UI uses
textContent and a restrictive CSP. No automatic background calls or jobs.

`python -m unittest test_deepseek_explainer` runs18 mocked/unit/local-HTTP tests.
The full collector/toolkit/horizon/explainer suite has80 passing tests on Linux.
No actual provider generation, Windows execution, funded trial, new forecast
model, buy signal or accuracy improvement is claimed by these tests.

Next dependency: follow `HORIZONS.md` to upload the actual collector backup. ARIA
can then check coverage and run the fixed, chronological CPU baseline before any
numerical-model/display integration or comparison with DeepSeek as a forecaster.