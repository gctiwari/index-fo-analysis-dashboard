"use client";
import { useState } from "react";
import useSWR from "swr";
import clsx from "clsx";
import { fetcher, indicesPath, exportTodayXlsxUrl } from "@/lib/api";
import type { IndexMeta } from "@/lib/types";
import IndexTabs from "@/components/IndexTabs";
import TickerStrip from "@/components/TickerStrip";
import OutlookDashboard from "@/components/OutlookDashboard";
import TrackerDashboard from "@/components/TrackerDashboard";
import { LoadingPanel, ErrorPanel } from "@/components/ui";

type View = "outlook" | "tracker";

export default function Home() {
  const { data: indices, error, isLoading } = useSWR<IndexMeta[]>(indicesPath, fetcher);
  const [activeIndex, setActiveIndex] = useState("NIFTY");
  const [view, setView] = useState<View>("outlook");

  return (
    <main className="min-h-screen">
      <TickerStrip />
      <header className="border-b border-base-border px-6 py-5">
        <div className="max-w-6xl mx-auto flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <p className="text-[11px] uppercase tracking-[0.2em] text-gold font-medium">Pre-Market · Post-Market Desk</p>
            <h1 className="font-display text-2xl font-semibold text-ink mt-0.5">Index F&amp;O Analysis</h1>
          </div>
          <div className="flex items-center gap-2">
            <nav className="flex gap-1 rounded-lg border border-base-border p-1 bg-base-panel w-fit">
              {(["outlook", "tracker"] as View[]).map((v) => (
                <button
                  key={v}
                  onClick={() => setView(v)}
                  className={clsx(
                    "px-4 py-1.5 rounded-md text-sm font-medium font-display transition-colors",
                    view === v ? "bg-gold text-base-deep" : "text-ink-muted hover:text-ink"
                  )}
                >
                  {v === "outlook" ? "Market Outlook" : "Trade Desk"}
                </button>
              ))}
            </nav>
            <a
              href={exportTodayXlsxUrl}
              title="Download an Excel sheet of every trade generated today, across all indices"
              className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg border border-base-border bg-base-panel text-sm font-medium font-display text-ink-muted hover:text-gold hover:border-gold/40 transition-colors whitespace-nowrap"
            >
              ⬇ Today&apos;s Trades
            </a>
          </div>
        </div>
      </header>

      <div className="max-w-6xl mx-auto px-6 py-6 space-y-6">
        {isLoading && <LoadingPanel label="Loading tracked indices…" />}
        {error && <ErrorPanel message={error.message} />}
        {indices && (
          <>
            <IndexTabs indices={indices} active={activeIndex} onChange={setActiveIndex} />
            <p className="text-xs text-ink-faint -mt-3">
              {view === "outlook"
                ? "Live read of current market conditions — refreshes as prices move. This is context, not a trade."
                : "Today's ONE locked trade plan for this index, tracked through the session — plus its full history and performance."}
            </p>
            {view === "outlook" && <OutlookDashboard index={activeIndex} />}
            {view === "tracker" && <TrackerDashboard index={activeIndex} />}
          </>
        )}
      </div>

      <footer className="max-w-6xl mx-auto px-6 pb-10 pt-2">
        <p className="text-xs text-ink-faint leading-relaxed border-t border-base-border pt-4">
          This is an analysis and research tool, not an automated trading system and not investment advice.
          Option premiums shown as estimates use a Black-Scholes model on ATR-derived volatility, not a live
          option-chain feed — verify actual quotes, OI and IV with your broker before acting. Trade at your own risk;
          past patterns do not guarantee future outcomes.
        </p>
      </footer>
    </main>
  );
}
