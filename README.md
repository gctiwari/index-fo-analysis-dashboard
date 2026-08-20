# Indian Index F&O Analysis Desk

A pre-market / post-market analysis and trade-idea prototype for Indian
index derivatives (NIFTY 50, BANK NIFTY, SENSEX live; FINNIFTY and MIDCAP
NIFTY registered but awaiting a data source). **Analysis and research
tooling only — not an automated trading system, not investment advice.**

## Risk — read this before acting on anything the app shows

**No feature in this app, including the "high-conviction" Primary pick, guarantees a profitable trade or protects
you from losing money.** Concretely:
- Options can lose their full value, including on setups with high displayed confidence.
- Confidence scores and win-rate stats reflect this app's own historical rule-based signals, not a promise about
  future market behavior — markets change regimes, and past confluence does not guarantee future results.
- Premiums, targets, and stop-losses are Black-Scholes **estimates** built on ATR-derived volatility, not live
  broker quotes — actual fills will differ, sometimes significantly during fast markets.
- Every trade idea includes a hard stop-loss specifically because breakouts and confluence setups fail often
  enough that skipping one would be reckless, not "more accurate."
- This tool is not a substitute for a licensed financial advisor, and the author/generator of this code is not
  one either. Use the paper-trading feature to build your own track record before risking real capital, size
  positions so a stop-out is a cost you can absorb, and never risk more than you can afford to lose.

## How the app is organized (and why)

Two tabs, each with a clear, single job:

1. **Market Outlook** — a live read of current conditions (bias, confidence, levels, indicators, patterns). This
   is deliberately reactive and refreshes as prices move, because it's describing *the market right now*, not a
   trade you can act on.
2. **Trade Desk** — the actual trade recommendation. **Exactly one PRIMARY plus two breakout/breakdown watches
   are generated per index per trading day, and each is then locked** — strike, premium, targets, and stop-loss
   never change again that day. Three legs total:
   - **Primary** — confluence-gated (only appears when multiple independent signals already agree)
   - **Breakout ↑** — "if price closes above resistance, buy this call" (reactive, no confluence gate)
   - **Breakdown ↓** — "if price closes below support, buy this put" (reactive, no confluence gate)

   What *does* update live is a separate "status" line per leg showing how close the market is to that leg's
   locked plan (distance to entry trigger, unrealized P&L once triggered). Sub-tabs: Today (all three locked
   legs + live status), Paper Trades, Not Executed, and Performance (win rate, equity curve, CSV/Excel export).

   **Important, and worth repeating plainly: none of this guarantees you won't lose money.** Every leg has a
   hard stop-loss because breakouts and even high-confluence setups fail often enough in real markets that
   skipping one would be irresponsible, not "more accurate." Premiums are still Black-Scholes estimates, not
   live option-chain quotes. This is a decision-support and paper-trading tool, not a guarantee generator.

Earlier drafts of this app also had a "Possible Trades" view that recalculated a fresh idea on every page load —
that was confusing (the recommended strike/premium/targets visibly shifted as price moved) and duplicated what
the Trade Desk already does properly, so it's been removed. The Trade Desk is now the single source of truth for
"what trade, at what price, with what targets."

## What's actually built vs. the full spec

The original brief asks for an institutional desk covering everything from
Elliott Wave to live FII/DII flows to NLP news sentiment — that's a
multi-team, multi-vendor product. This prototype builds the real,
end-to-end spine of that system so it's genuinely useful and extensible,
rather than a mockup:

**Fully working:**
- Live OHLCV for NIFTY, BANKNIFTY, SENSEX (yfinance)
- Trend structure (Dow theory / HH-HL / LH-LL), multi-timeframe (weekly → 15m)
- Moving averages: EMA 9/20/50/200, SMA 20/50, session VWAP
- Momentum: RSI, MACD, Stochastic RSI, ADX, ROC
- Volatility: ATR, Bollinger Bands + width percentile (compression/expansion)
- Volume: OBV slope, volume-spike detection
- Support/resistance via floor pivots + swing-point clustering, gap analysis
- Candlestick pattern detection (Doji, Hammer, Marubozu, Engulfing, Piercing/Dark Cloud, Harami, Morning/Evening Star, Three White Soldiers/Black Crows, and more)
- Simplified chart-pattern detection (Double Top/Bottom, range-compression/triangle context)
- A fully auditable confluence engine — every factor, its signal, and its weight is visible, not a black box
- Market bias + confidence score, scenarios (bullish/bearish/neutral), invalidation levels, expected range, gap-up/down probability
- Rule-based high-conviction trade-idea generator with Black-Scholes premium estimation, targets, stop-loss, risk:reward, position sizing guidance — or an explicit "no trade" verdict when confluence is weak
- **Daily trade tracking & paper trading**: one recommendation generated per index per trading day, **locked at generation time**, tracked for that session only. If the entry condition triggers, it moves to Paper Trades with entry price/time, exit price/time, targets hit, stop-loss, and P&L in ₹ and %. If it never triggers, it moves to Not Executed with the reason. Every prior day's record is preserved for history. An in-process scheduler drives this automatically during market hours (09:16 generate → every 3 min monitor → 15:32 settle); manual "Check now / Finalize day" buttons let you exercise the flow outside market hours too, and a guarded "Regenerate (force)" override exists for testing only.
- **Performance analytics**: % of recommendations that actually get executed, win rate, average return per trade, average win/loss, best/worst trade, and total P&L per lot — both per-index and combined.
- **Running equity curve**: a chart of cumulative P&L across every closed paper trade, per-index and combined across all indices.
- **CSV / Excel export**: download the full trade-log history (every day, every field) for one index or all indices, as CSV or Excel.
- Dark, institutional-style dashboard UI

**Deliberately stubbed / documented as extension points** (see `backend/README.md` for details):
option-chain Greeks/OI/PCR/Max Pain (needs a broker/vendor feed), FII/DII data, RBI/corporate news + NLP sentiment,
economic calendar, GIFT Nifty live feed, Elliott Wave, Wyckoff, and full Smart Money Concepts (order blocks, FVGs, BOS/CHOCH).

## Quick start

```bash
# Terminal 1
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Terminal 2
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

Then open http://localhost:3000.

## Adding a new index

Add one entry to `backend/app/config.py`'s `INDEX_REGISTRY` with a `yf_ticker`
(or point `data/fetcher.py` at a different source) — the API, confluence
engine, and frontend all pick it up automatically.
