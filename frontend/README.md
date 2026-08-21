# Frontend — Index F&O Dashboard

Next.js 14 (App Router) + TypeScript + Tailwind. Dark institutional theme,
two dashboards (Market Outlook, Possible Trades), driven entirely by the
FastAPI backend.

## Run locally

```bash
cd frontend
cp .env.example .env.local   # points at http://localhost:8000/api by default
npm install
npm run dev
```

Open http://localhost:3000. The backend must be running on port 8000 (see `../backend/README.md`).

## Structure

- `app/page.tsx` — top-level layout: index tabs + Market Outlook / Trade Desk toggle
- `components/OutlookDashboard.tsx` — live market read (bias, confidence gauge, levels, scenarios, MTF trend, indicators, patterns, confluence audit trail, risk warnings) — this refreshes as prices move, since it's describing current conditions, not a trade you can take
- `components/TrackerDashboard.tsx` — the Trade Desk: **one locked recommendation per day** (Today), Yesterday (most recent completed session's final results), Paper Trades, Not Executed / Invalidated, and Performance (with equity curve + CSV/Excel export). The locked plan's numbers never change after generation — only a separate "live status" section (current price, distance to trigger, unrealized P&L) updates on refresh
- `components/TickerStrip.tsx` — scrolling macro ticker (VIX, USDINR, Crude, Gold, US10Y, Dow, Nasdaq)
- `lib/types.ts` / `lib/trackingTypes.ts` — mirror the backend Pydantic/dict schemas exactly
- `lib/api.ts` — typed fetch wrapper; change `NEXT_PUBLIC_API_URL` to point at a deployed backend

Data refreshes every 30-60s via SWR while a dashboard is open. On the Trade Desk this only ever updates *live status* against a fixed plan — it never regenerates a new recommendation on its own.
