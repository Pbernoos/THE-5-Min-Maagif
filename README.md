# THE 5-Min Maagif

Public, read-only **GitHub Pages** dashboard for BTC and Polymarket five-minute markets.

## Trading dashboard UI

### Tehran time and forecast interpretation

All human-readable times and dates use **Asia/Tehran** (Iran local time;
UTC+03:30 under current rules), including the live clock, chart, forecast target,
market window, journal dates and export filename. IANA timezone conversion handles
local date rollover. Market identifiers, five-minute boundaries, API timestamps and
saved Unix seconds remain timezone-independent: no artificial offset is added to
the market itself. The clock still depends on your device's time being correct;
this change is timezone formatting, not external clock synchronization.

The direction estimate targets the **next full five-minute market window**, not
five minutes starting at the moment you read it. The exact Tehran target appears
underneath. It is not a guaranteed Up/Down result, and the model has not been
replaced or claimed to be more accurate by this UI update.

The journal now also compares model Brier with pre-start Up quote midpoint Brier
on the same officially resolved windows, only when stored quote timestamps are
fresh, precede issuance, and match the stored midpoint. Missing/stale/untimestamped
quotes are excluded. This is a descriptive evaluation, not proof of an edge.

The dark, responsive terminal includes a real Coinbase minute-close chart with
15m / 1h / 2h range controls, a five-minute countdown/progress indicator,
live BTC price, separate Up/Down public quote cards, experimental forecast panels,
and the ten most recent saved forecasts. Export retains all saved records.
The chart deliberately omits the newest minute and is **not tick-by-tick**;
chart-range change is not the current market window's return. Empty/stale data
stays empty rather than becoming demo prices or simulated results.
Quote midpoints and uncalibrated model probabilities are labeled separately.
The UI update does not alter the model, saved journal format, or trading permissions.

Expected website URL, once Pages is enabled and its build succeeds:
**https://pbernoos.github.io/THE-5-Min-Maagif/**

## What runs here

- A static HTML/CSS/JavaScript site. No Python, paid hosting, build service, credentials, wallet or orders.
- Direct public Coinbase BTC/USD ticker/candles and Polymarket Gamma/CLOB requests. API outages, stale timestamps, browser restrictions and rate limits can prevent display; failures do not become invented observations.
- A transparent, **untrained and uncalibrated** `browser-candle-baseline-v1`: 120 historical minute candles; standardized three-bar momentum (weight .5), EMA9/EMA21 trend (.3), simple 14-bar gain/loss RSI (.2), squashed to a deliberately narrow heuristic probability. This is a simplified independent baseline, NOT the Python model or either fitted research model.
- Draft for the upcoming full window; immutable browser-local forecast only if data collection and save complete within the last 20 seconds BEFORE its start. Candles must end at least 60 seconds before the window. No late backfill.
- Exact matching closed/resolved Polymarket outcomes, complementary binary labels and expected Chainlink 60-second TWAP source are required for scores. Coinbase price signs are never settlement labels.
- Local browser storage, up to 512 forecasts, and manual JSON export. Full/unavailable storage pauses capture rather than silently deleting old forecasts. Clearing browser data can lose history: export regularly.

**No demonstrated predictive edge. No financial advice or profitability claim.**
Historical studies did not establish dependable benefit. Neither research model is deployed here.
Coinbase is a price proxy; official strike/live Chainlink TWAP observations are not implemented.

## Important difference from the local Python app

GitHub Pages cannot run Python or an always-on collector. This site only collects while
the page is open and the browser schedules it; hidden/sleeping/closed tabs miss windows.
There is no shared database, authentication, centralized evaluation or cross-device sync.
Local data and device timestamps are editable, not tamper-proof evidence. Keep your clock
synchronized. Scores are provisional, conditional on collected/resolved windows, and do
not establish a reliable edge. The original Python shadow collector remains a separate app.

No analytics or data uploads are included. The browser contacts the listed public market
APIs, GitHub Pages, and any external links you choose to open; those services receive
normal web-request metadata. The site never asks for API keys or wallet secrets.

## Enable GitHub Pages (repository owner)

1. Open **Settings → Pages** in this repository:
   https://github.com/Pbernoos/THE-5-Min-Maagif/settings/pages
2. Under **Build and deployment**, choose **Deploy from a branch**.
3. Choose **main** and **/(root)**, then **Save**.
4. Wait for GitHub's Pages build to complete. The live URL appears on that page.

No Actions workflow or package install is required; `.nojekyll` bypasses Jekyll.
All asset paths are relative so the project URL works. No token belongs in these files.

## Local preview / tests

```sh
python -m http.server 8000
# open http://localhost:8000
```

Optional test dependencies (not required to serve the site):

```sh
python -m pip install pytest mini-racer
python -m pytest tests -q
```

Tests exercise JavaScript logic with an embedded engine and DOM stub, not real browser
rendering. Browser restrictions can differ from server-side CORS header checks.
See `verification.json` for delivery checks and limitations.