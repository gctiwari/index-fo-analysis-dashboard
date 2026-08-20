# Backend — Index F&O Analysis API

FastAPI service that fetches index data, runs the technical/confluence
engine, and serves the two dashboards.

## Run locally

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Visit http://localhost:8000/docs for interactive API docs.

## Endpoints

- `GET /api/indices` — which indices are tracked and whether each has a live data source wired up
- `GET /api/macro` — India VIX, USDINR, Crude, Gold, US10Y, Dow, Nasdaq snapshot
- `GET /api/outlook/{index}` — live market-outlook payload (bias, confidence, levels, indicators, patterns, confluence factors, risk warnings). This recalculates on every request -- appropriate here since it's describing current conditions, not a fixed trade.

Note: there is deliberately no `/api/trades/{index}`-style endpoint that recomputes a trade idea on every request
anymore (it existed in an earlier version and was removed). A trade recommendation should be decided once and then
tracked against, not silently regenerated every time someone refreshes the page -- see the tracking endpoints below.

### Daily tracking / paper trading (the Trade Desk)

Each index gets up to **3 independent legs per trading day**, all locked at generation time (see
`app/models_db.py`'s `Recommendation.role` field):
- `PRIMARY` — confluence-gated, matches the original single-recommendation behavior
- `BREAKOUT_UP` — "if price closes above resistance, buy this call" (reactive, no confluence gate)
- `BREAKOUT_DOWN` — "if price closes below support, buy this put" (reactive, no confluence gate)

A leg is stored as `NO_SIGNAL` instead of skipped if it doesn't apply (e.g. Primary fails the confluence bar, or
a breakout level is too close to CMP to be meaningful) -- so history has no silent gaps.

- `GET /api/tracking/{index}/today` — **returns a list of up to 3 legs**, each with its own locked numbers plus
  a `"live"` block with read-only status: `current_price`, `distance_to_trigger` (while PENDING), or
  `current_premium`/`unrealized_pnl_pct`/`progress_to_target_1_pct` (once EXECUTED). The `live` block updates
  every call; everything else in each leg does not change until the next trading day.
- `GET /api/tracking/{index}/paper-trades` — all paper trades for the index, newest first (`?status=OPEN|CLOSED`)
- `GET /api/tracking/{index}/not-executed` — recommendations whose entry never triggered, with the reason
- `GET /api/tracking/{index}/history` — full daily history (NO_SIGNAL / PENDING / EXECUTED / NOT_EXECUTED)
- `GET /api/performance` and `GET /api/performance/{index}` — % executed, win rate, avg return, total P&L, best/worst trade
- `POST /api/tracking/{index}/generate-now` — **testing-only override**: wipes and regenerates ALL of today's locked legs at the current price. Normal use shouldn't need this -- `/today` already auto-generates once and then stays fixed.
- `POST /api/tracking/{index}/check-now` — manual: run one monitoring pass (trigger entries / manage open trades)
- `POST /api/tracking/{index}/finalize-now` — manual: settle the day (NOT_EXECUTED / EOD_EXIT) without waiting for close

**How the lifecycle actually runs**: `app/scheduler.py` starts an in-process APScheduler when `uvicorn` boots and,
Monday-Friday IST, generates a fresh recommendation at 09:16, polls every 3 minutes from 09:00-15:59 (acting only
during 09:15-15:30), and finalizes the day at 15:32. **This only runs while the backend process is running** —
there's no separate worker. For real use, keep `uvicorn` running through the session (or move the scheduler to a
proper worker/cron in production). The three manual `POST` endpoints above exist so you can exercise the whole
flow on demand instead of waiting for market hours.

Data model (`app/models_db.py`, SQLite by default — see `app/db.py` for the Postgres swap):
- `Recommendation` — one row per index, per trading day, **per role** (`PRIMARY` / `BREAKOUT_UP` /
  `BREAKOUT_DOWN`). `status` moves `PENDING → EXECUTED / NOT_EXECUTED`, or `NO_SIGNAL` if that role doesn't apply
  that day. Stores both index-level and premium-level targets/stop so monitoring and P&L can be recomputed
  consistently.
- `PaperTrade` — created the instant a leg's entry condition triggers; closes on `TARGET_1`, `STOP_LOSS`, or
  `EOD_EXIT`, with entry/exit price, time, targets touched (`targets_hit`), and P&L in ₹ (per 1 lot) and %.

**Upgrading from an older version of this app**: the `role` column is new. SQLite's schema doesn't auto-migrate,
so `app/db.py` checks for it on startup -- if your existing `tracking.db` predates this field, it's automatically
renamed to `tracking.db.pre-role-migration-<timestamp>.bak` (your old history is preserved in that file, just not
loaded) and a fresh database is created. This is a one-time, automatic, zero-config step; no action needed on
your part beyond noticing the message in the server logs.

Known simplification: exits are single-target (closes in full at Target 1) rather than scaled/partial exits —
matches the "hard stop, quality over quantity" discipline elsewhere in the app, but `targets_hit` still records
whether price action reached Target 2/3 intraday for your own review. NSE holiday calendar isn't modeled — the
scheduler only checks weekday, not exchange holidays.

### Equity curve & export

- `GET /api/performance/{index}/equity-curve` and `GET /api/performance-equity-curve` (all indices combined) —
  chronological, cumulative P&L (₹ per lot and %) across every closed paper trade, in the order trades closed.
  This is a simple additive curve (each trade's % is summed, not compounded) so it reads cleanly on a chart.
- `GET /api/export/{index}/csv`, `GET /api/export/{index}/xlsx` — full trade-log history for one index
  (every day: NO_SIGNAL, PENDING, EXECUTED, NOT_EXECUTED, with entry/exit/targets/P&L columns).
- `GET /api/export-all/csv`, `GET /api/export-all/xlsx` — same, across all tracked indices.
- Built with `app/services/export.py` (pandas + openpyxl); columns auto-fit width in the Excel version.

`{index}` is one of `NIFTY`, `BANKNIFTY`, `SENSEX` (live in this build), or `FINNIFTY` / `MIDCPNIFTY` (registered but not yet wired to a data source — see below).

## Audit: why trade levels used to sit far from CMP (and the fix)

A self-audit found two compounding bugs in `analysis/levels.py`'s `support_resistance()`, not a fundamental flaw in the 3-scenario framework itself:

1. **Undifferentiated, unfiltered candidate pool.** Swing highs/lows were pulled from up to 120 daily bars (~6 months) with no check that a candidate was even still on the correct side of current price. After a sustained trend, an old swing point from months ago can sit on the "wrong" side or far behind current price, but it was still dumped into the resistance/support pool alongside genuinely current levels.
2. **Backwards trigger selection.** The trade-trigger fields picked the *farthest* candidate by raw magnitude (`max(resistance)` / `min(support)`) instead of the nearest — the opposite of what a "next level to watch" should mean. Compounding this, other parts of the codebase (`confluence.py`'s proximity check, `routes.py`'s executive summary) assumed index `[0]`/`[-1]` meant "nearest," which was only true for one of the two lists by coincidence — an inconsistent convention that made the bug harder to spot.

**The fix**, entirely in `analysis/levels.py` plus small consistency updates in `confluence.py`/`routes.py`:
- Candidates now come from clearly-scoped near-term (last ~15 sessions) and medium-term (last ~60 sessions) swing windows, floor pivots (always inherently near CMP by construction), and round-number levels — not one long undifferentiated window.
- Every candidate is filtered by direction (resistance must be above CMP, support below) and ranked by **distance from CMP**, nearest first, consistently for both lists.
- A trigger level is only exposed (`breakout`/`breakdown`) if it clears a genuine-signal floor (not noise-close) and stays within this app's own realistic reach — roughly the same ATR multiple as its own 3rd profit target, so the level and the target ladder are internally consistent.
- **Round numbers are a confidence booster only, never a standalone trigger.** Round numbers are always close to any price, so treating them as sufficient grounds for a trade would let the system "always find something" even with no real structure — exactly what was flagged as the risk. A trigger now requires a genuine technical basis (pivot or actual historical swing); round-number coincidence only adds a documented confidence boost when it lines up with one.
- When nothing technical clears the bar, `breakout`/`breakdown` are `None` and the corresponding Trade Desk leg correctly shows **WAIT / NO TRADE** with a specific reason, instead of reaching for a distant level.
- The two breakout legs' `risk_level`/`probability_score` were also flat constants before; they're now derived from data the confluence engine already computes (daily trend alignment, volatility compression) rather than a fixed number — a breakout aligned with the prevailing trend, or emerging from a volatility squeeze, is scored differently from one fighting the trend in a choppy tape.

**Verified with (see `/tmp` test scripts used during development, not shipped in this package but reproducible from `analysis/levels.py` directly):**
- Unit tests across 4 distinct market regimes (strong uptrend, strong downtrend, choppy/range-bound, and a different price magnitude) confirming every exposed level is on the correct side of CMP, nearest-first ordered, and any trigger level falls within a realistic ATR-scaled band.
- A 60-trial randomized-market distribution test (varying drift, volatility, and index price magnitude) confirming the system finds a valid nearby level in the large majority of conditions (consistent with pivots being designed to always be near-term relevant) *and* correctly returns WAIT/no-level in genuinely structure-less conditions — proving it doesn't unconditionally force a level.
- A full 3-index, 10-endpoint API regression (outlook, today's 3 legs, paper trades, not-executed, performance, equity curve, CSV/XLSX export, check-now, finalize-now) confirming every actionable trigger across NIFTY/BANKNIFTY/SENSEX landed within ~1% of CMP in realistic synthetic conditions, with no errors.

**Honestly out of scope for this pass** (flagged rather than faked): real options/OI analysis and futures-basis analysis remain unimplemented since there's still no live option-chain or futures data source wired in (see the data-source limitations below) — adding those without real data would itself be the kind of fabrication this audit was asked to avoid.

## Audit #2: why most generated trades never showed as EXECUTED (and the fix)

**Root cause: monitoring only ran on a fixed background schedule (APScheduler cron, every 3 minutes, market hours) that requires the backend process to stay running continuously and unattended.** Opening or refreshing the app did **not** itself check triggers — traced precisely: `GET /api/tracking/{index}/today`, hit on every page load and polled every 30s by the frontend, called `generate_daily_recommendations()` only, never `monitor_tick()`. For a locally-run dev server (`uvicorn --reload`, started/stopped manually rather than left running 24/7), most of a session's price action was simply never observed, so a trade whose trigger genuinely *was* reached could still be marked `NOT_EXECUTED` purely because nobody was polling at that moment. This was an infrastructure/coverage gap, not a strategy flaw — confirmed by direct code trace, not assumption.

A second, independent bug was found and fixed at the same time: every generated trade's `entry_trigger` text explicitly says **"Enter on a 15-min close beyond X"**, but the actual check compared a single live tick against the level — no candle, let alone a *completed* one. This didn't explain the low execution rate (a raw tick is an *easier* bar to clear than a confirmed close, so if anything it inflated executions) but it meant `EXECUTED` trades weren't reliably meeting their own stated rule, which undermines the tracked win-rate.

**What changed:**
1. **Opportunistic monitoring on read** (`tracking_routes.py::_maybe_opportunistic_monitor`) — `GET /today` now also runs a throttled (~20s floor) monitoring pass during market hours as a side effect. Any real interaction with the app while the market is open now checks triggers, closing the coverage gap regardless of whether the dedicated scheduler process stayed alive.
2. **Completed-candle close confirmation** (`fetcher.py::get_last_completed_candle`, used in `tracker.py::monitor_tick`) — entries now require a genuinely completed 15-minute candle's close beyond the trigger, matching the entry text exactly instead of a raw tick.
3. **`INVALIDATED` status** — a `PENDING` trade that closes through its own stop level before ever triggering is now marked `INVALIDATED` with a specific reason, distinct from `NOT_EXECUTED` (Step 6 of the audit). This was actually already *promised* in the `invalidation_condition` text generated for every trade ("exit... if this level is breached on a closing basis") — the code just never implemented it until now.
4. **Consistent CMP source** — trade generation now uses `get_last_price()` (the same live-tick source monitoring uses) as the reference price for entry-trigger math, instead of the daily bar's close — removing a second, smaller data-path inconsistency.
5. **Per-trade monitoring diagnostics** — every recommendation now stores `monitor_tick_count`, `last_price_checked`/`_at`, `mfe_index_level` (best price seen toward the trigger), and `trigger_reached_at`. A `NOT_EXECUTED` reason now explicitly says how many times it was actually checked — a count of 0-1 is itself direct evidence of a coverage gap, not proof the market never got there.

Open-position stop-loss/target management deliberately still uses the live tick, not a completed candle — once in a position, a stop should react immediately rather than wait up to 15 minutes to confirm, which would add avoidable slippage risk. This is an intentional asymmetry between entry strictness and exit responsiveness, not an inconsistency.

**Re-audited per the request, not re-assumed:** searched every use of `levels["support"]`/`levels["resistance"]`/`resistance[0]`/`support[0]` across the codebase again — the nearest-first ordering fixed in the previous audit is still consistent everywhere. Not a contributor this time.

**Verified with** (shipped in `backend/tests/`, runnable directly):
- `tests/test_candle_completeness.py` — confirms a fully-elapsed candle is used as-is, and a still-forming candle correctly falls back to the previous completed one.
- `tests/test_entry_confirmation_scenarios.py` — implements all 5 required scenarios end-to-end against the real `monitor_tick()`: trigger never reached → `NOT_EXECUTED`; trigger touched intrabar but 15m close doesn't confirm → stays `PENDING`; valid CALL close confirmation → `EXECUTED`; valid PUT close confirmation → `EXECUTED`; setup breaks its own stop before ever triggering → `INVALIDATED`, and does **not** later flip to `EXECUTED` even if price subsequently crosses the original trigger.
- A full 3-index, 10-endpoint API regression confirming nothing else broke.

Run them with:
```bash
cd backend
python3 tests/test_candle_completeness.py
python3 tests/test_entry_confirmation_scenarios.py
```

**On before/after execution-rate numbers:** no historical `tracking.db` or trade logs were available to analyze real generated trades — only the code itself. I'm not fabricating plausible-looking percentages. If you export your `tracking.db`, the `/api/performance/{index}` endpoint (and `compute_performance()` in `tracker.py`) can compute real before/after execution rates directly from it.

**What this fix deliberately did NOT do** (per explicit instruction): did not shrink trigger distances, lower the confidence threshold, make more trades "Immediate," move S/R levels closer, or relabel `NOT_EXECUTED` as `EXECUTED` to improve the numbers. The fix targets the actual mechanism that was failing to observe price action, not the trade generation criteria.

## Architecture

```
app/
  config.py          index registry (add a new index here + a data source, nothing else changes)
  data/fetcher.py     ONLY place that talks to yfinance -- swap for a paid vendor here
  analysis/
    indicators.py     EMA/SMA/RSI/MACD/StochRSI/ADX/ROC/ATR/Bollinger/VWAP/OBV -- pure pandas, no TA-Lib
    patterns.py        candlestick + simplified chart-pattern detection
    levels.py           Dow-theory trend structure, pivot/swing/round-number S/R with distance-based, direction-filtered, confluence-aware selection (see audit above), gap detection
    confluence.py       deterministic rule engine merging every signal into bias/confidence, fully auditable
    trades.py            rule-based trade-idea generator (Primary + 2 breakout legs) + Black-Scholes premium estimate
  api/routes.py       orchestrates the above into the dashboard payloads
```

## Known limitations / extension points (be aware before trusting this for real trading prep)

1. **Yahoo Finance blocking / rate limits**: Yahoo periodically changes how it blocks non-browser traffic, and
   yfinance periodically ships fixes for it (this is an ongoing cat-and-mouse, not a one-time bug). This build
   sends every request through a `curl_cffi` browser-impersonation session (`app/data/fetcher.py`) with retry/backoff,
   which is the current recommended fix. If you see `"Expecting value: line 1 column 1"`, `"possibly delisted"`,
   or `ImpersonateError` again in the future:
   - `pip install -U yfinance curl_cffi` (this is almost always the fix — check the
     [yfinance GitHub issues](https://github.com/ranaroussi/yfinance/issues) for the current recommended combo)
   - If curl_cffi complains a Chrome version isn't supported, try `impersonate="chrome124"` or another explicit
     version in `app/data/fetcher.py`'s `_SESSION` instead of the generic `"chrome"`
   - If you still get `YFRateLimitError`, you're sending requests too fast — the `refreshInterval` values in the
     frontend (`components/*.tsx`, default 60s) and the scheduler's 3-minute poll are already conservative, but
     you can raise them further
   - As a fallback, a paid data vendor (see point 1 below) sidesteps this entirely since it doesn't depend on
     Yahoo's public, unofficial, and unsupported API
2. **Option chain / Greeks / OI**: NSE's real option-chain (strike-wise OI, IV, PCR, Max Pain, Greeks) requires a
   broker or data-vendor feed (Kite Connect, TrueData, Global Datafeeds, etc.) with auth. This build estimates
   premiums with Black-Scholes on an ATR-derived volatility proxy — clearly labeled in the UI as an estimate, not
   a live quote. Wire a real option-chain source into `data/fetcher.py` and replace `analysis/trades.py`'s
   `estimate_premium` with real strike-wise premiums/Greeks/OI when you have vendor access.
3. **FII/DII flows, RBI/corporate news, economic calendar**: not wired up — these need either a paid data vendor
   or an NLP news pipeline. `app/config.py` and the outlook payload have room to add these as new confluence
   factors once a source is chosen.
4. **FINNIFTY / MIDCAP NIFTY**: registered in `config.py` so the UI already understands them, but no yfinance
   ticker maps cleanly to them — add a `yf_ticker` (or other data source) once you have one.
5. **GIFT Nifty / SGX Nifty**: SGX Nifty was discontinued in favor of GIFT Nifty (NSE IX); no free real-time feed
   exists for it, so it's currently proxied by the regular NIFTY ticker with a `*` note in the UI ticker strip.
6. **Elliott Wave / Wyckoff / full Smart Money Concepts (order blocks, FVGs, BOS/CHOCH)**: not implemented in
   this pass. These are genuinely hard to make rule-based and reliable; the confluence engine is structured so
   they can be added as additional weighted factors in `analysis/confluence.py` without touching anything else.
7. Uses an in-process cache stub only — for production, add Redis and a pre/post-market APScheduler job so the
   dashboards don't recompute on every request.
