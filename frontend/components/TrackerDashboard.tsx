"use client";
import { useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import clsx from "clsx";
import {
  fetcher, poster,
  trackingTodayPath, trackingPaperTradesPath, trackingNotExecutedPath, trackingHistoryPath, invalidatedPath,
  performancePath, generateNowPath, checkNowPath, finalizeNowPath,
  equityCurvePath, equityCurveAllPath, exportCsvUrl, exportXlsxUrl, exportAllCsvUrl, exportAllXlsxUrl,
  yesterdayPath,
} from "@/lib/api";
import type { RecommendationRecord, PaperTradeRecord, PerformanceResponse } from "@/lib/trackingTypes";
import { SectionCard, StatTile, LoadingPanel, ErrorPanel, RiskBadge } from "@/components/ui";
import EquityCurveChart from "@/components/EquityCurveChart";

type SubView = "today" | "yesterday" | "paper" | "not_executed" | "performance";

const STATUS_STYLE: Record<string, string> = {
  PENDING: "text-gold bg-gold/10 border-gold/30",
  EXECUTED: "text-signal-bull bg-signal-bull/10 border-signal-bull/30",
  NOT_EXECUTED: "text-ink-muted bg-white/5 border-base-border",
  NO_SIGNAL: "text-ink-faint bg-white/5 border-base-border",
  INVALIDATED: "text-signal-bear bg-signal-bear/10 border-signal-bear/30",
};

export default function TrackerDashboard({ index }: { index: string }) {
  const [sub, setSub] = useState<SubView>("today");
  const { mutate } = useSWRConfig();
  const [busy, setBusy] = useState<string | null>(null);

  async function runAction(label: string, path: string) {
    setBusy(label);
    try {
      await poster(path);
      await Promise.all([
        mutate(trackingTodayPath(index)),
        mutate(trackingPaperTradesPath(index)),
        mutate(trackingNotExecutedPath(index)),
        mutate(invalidatedPath(index)),
        mutate(trackingHistoryPath(index)),
        mutate(performancePath),
      ]);
    } catch (e) {
      // surfaced via the panels' own error states on next fetch
      console.error(e);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-1 rounded-lg border border-base-border p-1 bg-base-panel w-fit">
          {([
            ["today", "Today"],
            ["yesterday", "Yesterday"],
            ["paper", "Paper Trades"],
            ["not_executed", "Not Executed"],
            ["performance", "Performance"],
          ] as [SubView, string][]).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setSub(key)}
              className={clsx(
                "px-3.5 py-1.5 rounded-md text-sm font-medium font-display transition-colors",
                sub === key ? "bg-gold text-base-deep" : "text-ink-muted hover:text-ink"
              )}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="flex gap-2">
          <ActionButton label="Check now" busy={busy === "check"} onClick={() => runAction("check", checkNowPath(index))} />
          <ActionButton label="Finalize day" busy={busy === "final"} onClick={() => runAction("final", finalizeNowPath(index))} />
          <ActionButton
            label="Regenerate (force)"
            busy={busy === "gen"}
            onClick={() => {
              if (confirm("This replaces ALL THREE of today's locked legs (Primary + both breakout watches) with brand-new ones at the current price. Only do this for testing — in normal use, today's plan should stay fixed once generated.")) {
                runAction("gen", generateNowPath(index));
              }
            }}
          />
        </div>
      </div>
      <p className="text-xs text-ink-faint -mt-2">
        A recommendation generates once automatically (~09:16 IST) and then stays fixed all day — that&apos;s the
        whole point: one plan, tracked, not a number that drifts with every price tick. &quot;Check now&quot; just
        refreshes the live status against that fixed plan (has it triggered? hit target/stop?) without changing it.
        &quot;Regenerate&quot; is a testing override that throws away today&apos;s plan and starts over — normal use
        shouldn&apos;t need it.
      </p>

      {sub === "today" && <TodayView index={index} />}
      {sub === "yesterday" && <YesterdayView index={index} />}
      {sub === "paper" && <PaperTradesView index={index} />}
      {sub === "not_executed" && <NotExecutedView index={index} />}
      {sub === "performance" && <PerformanceView index={index} />}
    </div>
  );
}

function ActionButton({ label, busy, onClick }: { label: string; busy: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      disabled={busy}
      className="text-xs font-medium px-3 py-1.5 rounded-md border border-base-border text-ink-muted hover:text-ink hover:border-ink-faint transition-colors disabled:opacity-50"
    >
      {busy ? "…" : label}
    </button>
  );
}

function TodayView({ index }: { index: string }) {
  const { data, error, isLoading } = useSWR<RecommendationRecord[]>(trackingTodayPath(index), fetcher, { refreshInterval: 30_000 });
  if (isLoading) return <LoadingPanel label="Loading today's plan…" />;
  if (error) return <ErrorPanel message={error.message} />;
  if (!data || data.length === 0) return null;

  const primary = data.find((r) => r.role === "PRIMARY");
  const breakoutUp = data.find((r) => r.role === "BREAKOUT_UP");
  const breakoutDown = data.find((r) => r.role === "BREAKOUT_DOWN");

  return (
    <div className="space-y-4">
      <div className="panel p-4 border-gold/20 bg-gold/5">
        <p className="text-xs text-ink-muted leading-relaxed">
          <span className="text-gold font-medium">Three independent legs, all locked once generated:</span> the
          Primary pick (only appears when multiple signals already agree), and two reactive breakout watches —
          buy if price breaks <span className="text-signal-bull">above resistance</span>, or buy if it breaks{" "}
          <span className="text-signal-bear">below support</span>. None of these guarantee a profitable outcome —
          every leg has a hard stop-loss because breakouts fail often enough that risking more than that stop is
          not something any analysis tool can responsibly promise against.
        </p>
      </div>

      {primary && <RecommendationCard rec={primary} title="Primary Pick" subtitle="Confluence-gated — only exists when several signals already agree" />}
      {breakoutUp && <RecommendationCard rec={breakoutUp} title="If market breaks ABOVE this level" subtitle="Reactive breakout watch — no confluence gate, sized and stopped accordingly" accent="bull" />}
      {breakoutDown && <RecommendationCard rec={breakoutDown} title="If market breaks BELOW this level" subtitle="Reactive breakdown watch — no confluence gate, sized and stopped accordingly" accent="bear" />}
    </div>
  );
}

function YesterdayView({ index }: { index: string }) {
  const { data, error, isLoading } = useSWR<{ trade_date: string | null; legs: RecommendationRecord[] }>(
    yesterdayPath(index), fetcher, { refreshInterval: 60_000 }
  );
  if (isLoading) return <LoadingPanel label="Loading yesterday's results…" />;
  if (error) return <ErrorPanel message={error.message} />;
  if (!data || !data.trade_date || data.legs.length === 0) {
    return <EmptyState text="No prior trading session found yet for this index — results will appear here after the first day it's tracked." />;
  }

  const primary = data.legs.find((r) => r.role === "PRIMARY");
  const breakoutUp = data.legs.find((r) => r.role === "BREAKOUT_UP");
  const breakoutDown = data.legs.find((r) => r.role === "BREAKOUT_DOWN");

  return (
    <div className="space-y-4">
      <div className="panel p-4 border-gold/20 bg-gold/5">
        <p className="text-xs text-ink-muted leading-relaxed">
          <span className="text-gold font-medium">Results for {data.trade_date}</span> — the most recent completed
          trading session. Each leg below shows its final outcome: executed with a realized P&amp;L, not executed
          because the entry trigger was never reached, invalidated because price broke the setup before it could
          trigger, or no signal that day.
        </p>
      </div>

      {primary && <RecommendationCard rec={primary} title="Primary Pick" subtitle="Confluence-gated — only exists when several signals already agreed" />}
      {breakoutUp && <RecommendationCard rec={breakoutUp} title="Breakout Watch (upside)" subtitle="Reactive breakout watch — no confluence gate" accent="bull" />}
      {breakoutDown && <RecommendationCard rec={breakoutDown} title="Breakdown Watch (downside)" subtitle="Reactive breakdown watch — no confluence gate" accent="bear" />}
    </div>
  );
}

function RecommendationCard({ rec, title, subtitle, accent }: { rec: RecommendationRecord; title: string; subtitle: string; accent?: "bull" | "bear" }) {
  const genTime = rec.generated_at ? new Date(rec.generated_at).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" }) : "—";
  const borderClass = accent === "bull" ? "border-signal-bull/20" : accent === "bear" ? "border-signal-bear/20" : "";
  const isPastDay = rec.trade_date !== new Date().toLocaleDateString("en-CA"); // en-CA gives YYYY-MM-DD, matching the API's date format
  const dayWord = isPastDay ? "that day" : "today";

  return (
    <div className={clsx("panel p-6 space-y-4", borderClass)}>
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <p className="text-[11px] uppercase tracking-widest text-gold/80 font-medium mb-1">{title}</p>
          <p className="text-xs text-ink-faint mb-1">{subtitle}</p>
          <h3 className="font-display text-xl font-semibold text-ink">
            {rec.status === "NO_SIGNAL" ? `No watch active ${dayWord}` : `${rec.option_type} ${rec.strike ?? ""}`}
          </h3>
        </div>
        <span className={clsx("text-xs font-medium px-2.5 py-1 rounded-full border uppercase tracking-wide", STATUS_STYLE[rec.status])}>
          {rec.status.replace("_", " ")}
        </span>
      </div>

      {rec.status === "NO_SIGNAL" && <p className="text-sm text-ink-muted">{rec.no_signal_reason}</p>}

      {rec.status !== "NO_SIGNAL" && (
        <>
          <p className="text-sm text-ink-muted leading-relaxed">
            Locked at {genTime} (index was at{" "}
            <span className="text-ink font-medium">{rec.cmp_at_generation?.toLocaleString("en-IN")}</span>):{" "}
            {rec.option_type === "CALL" ? "buy a call" : "buy a put"} at strike{" "}
            <span className="text-ink font-medium">{rec.strike}</span>, estimated cost{" "}
            <span className="text-ink font-medium">₹{rec.premium_at_generation}</span>.{" "}
            {isPastDay ? "This was fixed for the rest of that session." : "Fixed for the rest of today."}
          </p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <StatTile label="Strike / Premium" value={`${rec.strike} · ₹${rec.premium_at_generation}`} />
            <StatTile label="Entry type" value={rec.entry_type ?? "—"} />
            <StatTile label="Confidence at generation" value={`${rec.confidence_score?.toFixed(0)}%`} />
            <StatTile label="Targets 1/2/3" value={`₹${rec.target_premium_1} / ₹${rec.target_premium_2} / ₹${rec.target_premium_3}`} />
          </div>
          <p className="text-sm text-ink-muted"><span className="text-ink font-medium">Entry trigger: </span>{rec.entry_trigger_desc}</p>
          <p className="text-sm text-ink-muted"><span className="text-ink font-medium">Hard stop-loss: </span>₹{rec.stop_premium}</p>
          <p className="text-sm text-ink-muted"><span className="text-ink font-medium">Reasoning: </span>{rec.reasoning}</p>
          {rec.status === "NOT_EXECUTED" && (
            <p className="text-sm text-ink-muted"><span className="text-ink font-medium">Why it didn't execute: </span>{rec.not_executed_reason}</p>
          )}
          {rec.status === "INVALIDATED" && (
            <p className="text-sm text-signal-bear"><span className="font-medium">Invalidated before entry: </span>{rec.invalidated_reason}</p>
          )}
        </>
      )}

      {rec.status !== "NO_SIGNAL" && (
        <details className="text-xs text-ink-faint">
          <summary className="cursor-pointer hover:text-ink-muted select-none">Monitoring diagnostics — was this actually being watched?</summary>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 mt-2">
            <StatTile label="Times checked" value={`${rec.diagnostics.monitor_tick_count}`} sub="raw polls, including repeats" />
            <StatTile label="Unique candles seen" value={`${rec.diagnostics.unique_candles_checked}`} sub="distinct 15-min candles evaluated" />
            <StatTile label="Last checked" value={rec.diagnostics.last_price_checked_at ? new Date(rec.diagnostics.last_price_checked_at).toLocaleTimeString("en-IN") : "Not yet"} />
            <StatTile label="Best price seen" value={rec.diagnostics.mfe_index_level != null ? rec.diagnostics.mfe_index_level.toLocaleString("en-IN") : "—"} />
            <StatTile
              label="Decisive candle"
              value={rec.diagnostics.last_completed_candle_close != null ? rec.diagnostics.last_completed_candle_close.toLocaleString("en-IN") : "—"}
              sub={rec.diagnostics.last_completed_candle_timestamp ? new Date(rec.diagnostics.last_completed_candle_timestamp).toLocaleTimeString("en-IN") : undefined}
            />
          </div>
          {rec.diagnostics.monitor_tick_count === 0 && rec.status === "PENDING" && (
            <p className="mt-2 text-gold/80">Not checked yet today — this updates automatically the next time this tab is open during market hours, or via the background scheduler if the server has been running continuously.</p>
          )}
        </details>
      )}

      {rec.status !== "NO_SIGNAL" && rec.live?.available && (
        <SectionCard title="Live Status" eyebrow="Updates automatically — the plan above never does" className="bg-base-alt/40">
          {rec.status === "PENDING" && (
            <div className="space-y-2">
              <div className="grid grid-cols-2 gap-3">
                <StatTile label="Current index level" value={rec.live.current_price?.toLocaleString("en-IN") ?? "—"} />
                <StatTile
                  label={rec.live.trigger_reached ? "Trigger reached" : "Distance to trigger"}
                  value={rec.live.trigger_reached ? "Yes — should execute shortly" : `${Math.abs(rec.live.distance_to_trigger ?? 0).toFixed(1)} points away`}
                />
              </div>
              <p className="text-xs text-ink-faint">
                Waiting for the index to reach {rec.entry_trigger_desc?.toLowerCase()}. Nothing is executed until then.
              </p>
            </div>
          )}
          {rec.status === "EXECUTED" && rec.paper_trade?.status === "OPEN" && (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <StatTile label="Current index level" value={rec.live.current_price?.toLocaleString("en-IN") ?? "—"} />
              <StatTile label="Current premium (est.)" value={rec.live.current_premium != null ? `₹${rec.live.current_premium}` : "—"} />
              <StatTile
                label="Unrealized P&L"
                value={rec.live.unrealized_pnl_pct != null ? `${rec.live.unrealized_pnl_pct > 0 ? "+" : ""}${rec.live.unrealized_pnl_pct}%` : "—"}
              />
              <StatTile label="Progress to Target 1" value={rec.live.progress_to_target_1_pct != null ? `${rec.live.progress_to_target_1_pct}%` : "—"} />
            </div>
          )}
        </SectionCard>
      )}

      {rec.paper_trade && rec.paper_trade.status === "CLOSED" && (
        <SectionCard title="Result" eyebrow={isPastDay ? "This leg closed that session" : "This leg is closed for today"} className="bg-base-alt/40">
          <PaperTradeCard trade={rec.paper_trade} />
        </SectionCard>
      )}
    </div>
  );
}

function PaperTradesView({ index }: { index: string }) {
  const { data, error, isLoading } = useSWR<PaperTradeRecord[]>(trackingPaperTradesPath(index), fetcher, { refreshInterval: 60_000 });
  if (isLoading) return <LoadingPanel label="Loading paper trades…" />;
  if (error) return <ErrorPanel message={error.message} />;
  if (!data || data.length === 0) return <EmptyState text="No paper trades yet for this index — one appears here the moment an entry condition triggers." />;

  return (
    <div className="space-y-4">
      {data.map((t) => <PaperTradeCard key={t.id} trade={t} showDate />)}
    </div>
  );
}

function PaperTradeCard({ trade, showDate }: { trade: PaperTradeRecord; showDate?: boolean }) {
  const isProfit = (trade.pnl_pct ?? 0) > 0;
  const roleLabel = trade.role === "BREAKOUT_UP" ? "Breakout ↑" : trade.role === "BREAKOUT_DOWN" ? "Breakdown ↓" : "Primary";
  return (
    <SectionCard
      title={trade.status === "OPEN" ? `Open Position · ${roleLabel}` : `Closed · ${roleLabel} · ${trade.outcome?.replace("_", " ")}`}
      eyebrow={showDate ? trade.trade_date : undefined}
      className={trade.status === "CLOSED" ? (isProfit ? "border-signal-bull/20" : "border-signal-bear/20") : "border-gold/20"}
    >
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatTile label="Entry" value={`₹${trade.entry_premium} @ ${trade.entry_index_level.toLocaleString("en-IN")}`} sub={trade.entry_time ? new Date(trade.entry_time).toLocaleTimeString("en-IN") : undefined} />
        <StatTile
          label={trade.status === "OPEN" ? "Running" : "Exit"}
          value={trade.exit_premium ? `₹${trade.exit_premium} @ ${trade.exit_index_level?.toLocaleString("en-IN")}` : "—"}
          sub={trade.exit_time ? new Date(trade.exit_time).toLocaleTimeString("en-IN") : undefined}
        />
        <StatTile
          label="P&L"
          value={trade.pnl_pct != null ? `${trade.pnl_pct > 0 ? "+" : ""}${trade.pnl_pct}%` : "Open"}
          sub={trade.pnl_rupees != null ? `₹${trade.pnl_rupees.toLocaleString("en-IN")} / lot` : undefined}
        />
        <StatTile label="Targets hit" value={trade.targets_hit.length ? trade.targets_hit.join(", ") : "None yet"} />
      </div>
    </SectionCard>
  );
}

function NotExecutedView({ index }: { index: string }) {
  const { data, error, isLoading } = useSWR<RecommendationRecord[]>(trackingNotExecutedPath(index), fetcher, { refreshInterval: 60_000 });
  const { data: invalidated } = useSWR<RecommendationRecord[]>(invalidatedPath(index), fetcher, { refreshInterval: 60_000 });
  if (isLoading) return <LoadingPanel label="Loading not-executed log…" />;
  if (error) return <ErrorPanel message={error.message} />;

  const hasNotExecuted = data && data.length > 0;
  const hasInvalidated = invalidated && invalidated.length > 0;

  if (!hasNotExecuted && !hasInvalidated) {
    return <EmptyState text="Nothing here — every triggered-and-tracked idea either executed or is still pending today." />;
  }

  return (
    <div className="space-y-6">
      {hasInvalidated && (
        <div>
          <p className="text-xs uppercase tracking-wider text-signal-bear/80 mb-2 font-medium">
            Invalidated — broke down before ever triggering entry
          </p>
          <div className="space-y-3">
            {invalidated!.map((r) => (
              <div key={r.id} className="panel p-4 flex items-start justify-between gap-3 border-signal-bear/20">
                <div>
                  <p className="text-sm font-medium text-ink">{r.trade_date} · {r.option_type} {r.strike}</p>
                  <p className="text-xs text-signal-bear mt-1">{r.invalidated_reason}</p>
                  <p className="text-xs text-ink-faint mt-1">Entry trigger would have been: {r.entry_trigger_desc}</p>
                </div>
                <span className="text-[11px] font-medium px-2 py-0.5 rounded-full border border-signal-bear/30 text-signal-bear uppercase tracking-wide shrink-0">
                  Invalidated
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
      {hasNotExecuted && (
        <div>
          <p className="text-xs uppercase tracking-wider text-ink-faint mb-2 font-medium">
            Not executed — entry trigger never reached
          </p>
          <div className="space-y-3">
            {data!.map((r) => (
              <div key={r.id} className="panel p-4 flex items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-medium text-ink">{r.trade_date} · {r.option_type} {r.strike}</p>
                  <p className="text-xs text-ink-muted mt-1">{r.not_executed_reason}</p>
                  <p className="text-xs text-ink-faint mt-1">Trigger was: {r.entry_trigger_desc}</p>
                </div>
                <span className="text-[11px] font-medium px-2 py-0.5 rounded-full border border-base-border text-ink-muted uppercase tracking-wide shrink-0">
                  Not executed
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function PerformanceView({ index }: { index: string }) {
  const { data, error, isLoading } = useSWR<PerformanceResponse>(performancePath, fetcher, { refreshInterval: 60_000 });
  if (isLoading) return <LoadingPanel label="Crunching performance stats…" />;
  if (error) return <ErrorPanel message={error.message} />;
  if (!data) return null;

  const thisIndex = data.per_index.find((p) => p.index === index);

  return (
    <div className="space-y-5">
      <ExportBar index={index} />
      {thisIndex && <PerformanceBlock title={`${index} Performance`} stats={thisIndex} />}
      <EquityCurveChart path={equityCurvePath(index)} title={`${index} Equity Curve`} />
      <PerformanceBlock title="All Tracked Indices — Combined" stats={data.overall} />
      <EquityCurveChart path={equityCurveAllPath} title="Combined Equity Curve — All Indices" />
    </div>
  );
}

function ExportBar({ index }: { index: string }) {
  return (
    <SectionCard title="Export Trade Log" eyebrow="Full history, every day tracked">
      <div className="flex flex-wrap gap-2">
        <ExportLink href={exportCsvUrl(index)} label={`${index} · CSV`} />
        <ExportLink href={exportXlsxUrl(index)} label={`${index} · Excel`} />
        <ExportLink href={exportAllCsvUrl} label="All indices · CSV" />
        <ExportLink href={exportAllXlsxUrl} label="All indices · Excel" />
      </div>
    </SectionCard>
  );
}

function ExportLink({ href, label }: { href: string; label: string }) {
  return (
    <a
      href={href}
      className="text-xs font-medium px-3 py-1.5 rounded-md border border-base-border text-ink-muted hover:text-gold hover:border-gold/40 transition-colors"
    >
      ↓ {label}
    </a>
  );
}

function PerformanceBlock({ title, stats }: { title: string; stats: PerformanceResponse["overall"] }) {
  const pnlPositive = stats.total_pnl_rupees_per_lot >= 0;
  return (
    <SectionCard title={title}>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatTile label="Signal days tracked" value={`${stats.signal_days}`} sub={`${stats.no_signal_days} no-signal days`} />
        <StatTile label="% executed" value={`${stats.pct_executed}%`} sub={`${stats.executed_count} of ${stats.signal_days}`} />
        <StatTile label="Win rate" value={`${stats.win_rate_pct}%`} sub={`${stats.closed_trades_count} closed trades`} />
        <StatTile label="Avg return / trade" value={`${stats.avg_return_pct_per_trade > 0 ? "+" : ""}${stats.avg_return_pct_per_trade}%`} />
        <StatTile label="Avg win" value={`+${stats.avg_win_pct}%`} />
        <StatTile label="Avg loss" value={`${stats.avg_loss_pct}%`} />
        <StatTile label="Best / worst trade" value={`+${stats.best_trade_pct}% / ${stats.worst_trade_pct}%`} />
        <StatTile
          label="Total P&L (per 1 lot)"
          value={`${pnlPositive ? "+" : ""}₹${stats.total_pnl_rupees_per_lot.toLocaleString("en-IN")}`}
        />
      </div>
      {stats.open_trades_count > 0 && (
        <p className="text-xs text-gold/80 mt-3">{stats.open_trades_count} trade(s) still open — not yet included in win rate / avg return.</p>
      )}
    </SectionCard>
  );
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="panel p-8 text-center">
      <p className="text-sm text-ink-faint max-w-md mx-auto">{text}</p>
    </div>
  );
}
