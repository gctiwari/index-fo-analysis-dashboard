"use client";
import useSWR from "swr";
import clsx from "clsx";
import { fetcher } from "@/lib/api";

interface MacroEntry {
  ticker: string;
  last: number | null;
  change: number | null;
  change_pct: number | null;
}

const LABELS: Record<string, string> = {
  INDIA_VIX: "INDIA VIX",
  USDINR: "USD/INR",
  CRUDE: "CRUDE OIL",
  GOLD: "GOLD",
  US10Y: "US 10Y YIELD",
  DOWJONES: "DOW JONES",
  NASDAQ: "NASDAQ",
  SGX_NIFTY_PROXY: "GIFT NIFTY*",
};

export default function TickerStrip() {
  const { data } = useSWR<Record<string, MacroEntry>>("/macro", fetcher, { refreshInterval: 90_000 });
  // Defensive filter: only render entries with a real, finite last price. The backend
  // is now expected to omit incomplete entries entirely, but a scrolling ticker crashing
  // the whole page over one bad upstream value is worse than just skipping it here too.
  const entries = data
    ? Object.entries(data).filter(([, v]) => typeof v?.last === "number" && Number.isFinite(v.last))
    : [];
  if (entries.length === 0) return null;

  const items = [...entries, ...entries]; // duplicate for seamless scroll

  return (
    <div className="border-b border-base-border bg-base-panel/60 overflow-hidden">
      <div className="flex w-max animate-ticker">
        {items.map(([key, v], i) => {
          const change = v.change ?? 0;
          const changePct = v.change_pct ?? 0;
          return (
            <div key={`${key}-${i}`} className="flex items-center gap-2 px-5 py-2 border-r border-base-border/60 whitespace-nowrap">
              <span className="text-[11px] uppercase tracking-wider text-ink-faint">{LABELS[key] ?? key}</span>
              <span className="font-mono text-sm text-ink tabular">{(v.last as number).toLocaleString("en-IN")}</span>
              <span className={clsx("font-mono text-xs tabular", change >= 0 ? "text-signal-bull" : "text-signal-bear")}>
                {change >= 0 ? "▲" : "▼"} {changePct.toFixed(2)}%
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
