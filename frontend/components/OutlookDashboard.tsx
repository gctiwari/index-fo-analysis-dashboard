"use client";
import useSWR from "swr";
import clsx from "clsx";
import { fetcher, outlookPath } from "@/lib/api";
import type { MarketOutlook } from "@/lib/types";
import { SignalBadge, RiskBadge, SectionCard, StatTile, LoadingPanel, ErrorPanel } from "@/components/ui";
import ConfidenceGauge from "@/components/ConfidenceGauge";

export default function OutlookDashboard({ index }: { index: string }) {
  const { data, error, isLoading } = useSWR<MarketOutlook>(outlookPath(index), fetcher, {
    refreshInterval: 60_000,
  });

  if (isLoading) return <LoadingPanel label={`Running confluence analysis on ${index}…`} />;
  if (error) return <ErrorPanel message={error.message} />;
  if (!data) return null;

  const isUp = data.change >= 0;
  const biasColor = data.bias === "Bullish" ? "text-signal-bull" : data.bias === "Bearish" ? "text-signal-bear" : "text-ink-muted";

  return (
    <div className="space-y-5">
      {/* Header row: price + bias + gauge */}
      <div className="panel p-6 flex flex-col lg:flex-row lg:items-center justify-between gap-6">
        <div>
          <p className="text-[11px] uppercase tracking-widest text-gold/80 font-medium mb-1">{data.index} · as of {new Date(data.as_of).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })} IST</p>
          <h2 className="font-display text-4xl font-semibold tabular text-ink">{data.cmp.toLocaleString("en-IN")}</h2>
          <p className={clsx("font-mono text-sm mt-1 tabular", isUp ? "text-signal-bull" : "text-signal-bear")}>
            {isUp ? "▲" : "▼"} {Math.abs(data.change).toFixed(1)} ({data.change_pct.toFixed(2)}%)
          </p>
          <div className="flex items-center gap-2 mt-4">
            <span className={clsx("font-display text-2xl font-semibold", biasColor)}>{data.bias}</span>
            <RiskBadge level={data.risk_level} />
          </div>
          <p className="text-sm text-ink-muted mt-1">Momentum: {data.momentum_state} · Volatility: {data.volatility_state}</p>
        </div>
        <ConfidenceGauge value={data.confidence_score} bias={data.bias} />
      </div>

      {/* Executive summary */}
      <SectionCard title="Executive Summary" eyebrow="Plain-English read">
        <p className="text-sm leading-relaxed text-ink-muted">{data.executive_summary}</p>
      </SectionCard>

      {/* Levels + Range */}
      <div className="grid md:grid-cols-2 gap-5">
        <SectionCard title="Key Levels">
          <div className="grid grid-cols-2 gap-3">
            <StatTile label="Resistance" value={data.levels.resistance.map((n) => n.toLocaleString("en-IN")).join(" / ")} />
            <StatTile label="Support" value={data.levels.support.map((n) => n.toLocaleString("en-IN")).join(" / ")} />
            <StatTile
              label="Breakout above"
              value={data.levels.breakout != null ? data.levels.breakout.toLocaleString("en-IN") : "No valid level nearby"}
              sub={data.levels.breakout_round_number_confluence ? "Round-number confluence" : undefined}
            />
            <StatTile
              label="Breakdown below"
              value={data.levels.breakdown != null ? data.levels.breakdown.toLocaleString("en-IN") : "No valid level nearby"}
              sub={data.levels.breakdown_round_number_confluence ? "Round-number confluence" : undefined}
            />
          </div>
        </SectionCard>
        <SectionCard title="Expected Range & Opening">
          <div className="grid grid-cols-2 gap-3">
            <StatTile label="Range low" value={data.expected_range_low.toLocaleString("en-IN")} />
            <StatTile label="Range high" value={data.expected_range_high.toLocaleString("en-IN")} />
            <StatTile label="Gap-up prob." value={`${data.probability_gap_up}%`} />
            <StatTile label="Gap-down prob." value={`${data.probability_gap_down}%`} />
          </div>
          <p className="text-sm text-ink-muted mt-3">{data.expected_opening}</p>
        </SectionCard>
      </div>

      {/* Scenarios */}
      <div className="grid md:grid-cols-3 gap-5">
        <SectionCard title="Bullish Scenario">
          <p className="text-sm text-ink-muted leading-relaxed">{data.bullish_scenario}</p>
        </SectionCard>
        <SectionCard title="Bearish Scenario">
          <p className="text-sm text-ink-muted leading-relaxed">{data.bearish_scenario}</p>
        </SectionCard>
        <SectionCard title="Neutral / Range Scenario">
          <p className="text-sm text-ink-muted leading-relaxed">{data.neutral_scenario}</p>
        </SectionCard>
      </div>
      <p className="text-xs text-ink-faint -mt-3">Invalidation level for the current {data.bias.toLowerCase()} bias: <span className="font-mono text-ink-muted">{data.invalidation_level.toLocaleString("en-IN")}</span></p>

      {/* Multi-timeframe trend */}
      <SectionCard title="Multi-Timeframe Trend">
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
          {data.trends_mtf.map((t) => (
            <div key={t.timeframe} className="rounded-md border border-base-border bg-base-alt/60 p-3">
              <p className="text-[10px] uppercase tracking-wider text-ink-faint">{t.timeframe}</p>
              <p className={clsx(
                "font-display text-sm font-semibold mt-1",
                t.direction === "uptrend" ? "text-signal-bull" : t.direction === "downtrend" ? "text-signal-bear" : "text-ink-muted"
              )}>
                {t.direction}
              </p>
              <p className="text-[11px] text-ink-muted mt-1">{t.structure}</p>
              <div className="h-1 bg-base-border rounded-full mt-2 overflow-hidden">
                <div className="h-full bg-gold" style={{ width: `${t.strength}%` }} />
              </div>
            </div>
          ))}
        </div>
      </SectionCard>

      {/* Indicators */}
      <SectionCard title="Indicator Snapshot">
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3">
          <StatTile label="RSI (14)" value={data.key_indicators.rsi_14.toFixed(1)} />
          <StatTile label="MACD Hist" value={data.key_indicators.macd_hist.toFixed(1)} />
          <StatTile label="Stoch RSI K/D" value={`${data.key_indicators.stoch_rsi_k.toFixed(0)}/${data.key_indicators.stoch_rsi_d.toFixed(0)}`} />
          <StatTile label="ADX (14)" value={data.key_indicators.adx_14.toFixed(1)} />
          <StatTile label="ATR (14)" value={`${data.key_indicators.atr_14.toFixed(0)} (${data.key_indicators.atr_pct.toFixed(2)}%)`} />
          <StatTile label="ROC (10)" value={`${data.key_indicators.roc_10.toFixed(2)}%`} />
          <StatTile label="EMA 20/50" value={`${data.key_indicators.ema_20.toFixed(0)}/${data.key_indicators.ema_50.toFixed(0)}`} />
          <StatTile label="EMA 200" value={data.key_indicators.ema_200.toFixed(0)} />
          <StatTile label="VWAP" value={data.key_indicators.vwap.toFixed(0)} />
          <StatTile label="BB Width %ile" value={`${data.key_indicators.bb_width_pctile.toFixed(0)}`} />
          <StatTile label="OBV Slope" value={data.key_indicators.obv_slope} />
          <StatTile label="Volume Spike" value={data.key_indicators.volume_spike ? "Yes" : "No"} />
        </div>
      </SectionCard>

      {/* Patterns */}
      <SectionCard title="Detected Patterns" eyebrow={`${data.patterns.length} found`}>
        {data.patterns.length === 0 ? (
          <p className="text-sm text-ink-faint">No high-confidence candlestick or chart patterns on the current timeframe.</p>
        ) : (
          <div className="space-y-2">
            {data.patterns.map((p, i) => (
              <div key={i} className="flex items-start justify-between gap-3 rounded-md border border-base-border bg-base-alt/60 p-3">
                <div>
                  <p className="text-sm font-medium text-ink">{p.name} <span className="text-ink-faint font-normal">· {p.category}</span></p>
                  <p className="text-xs text-ink-muted mt-0.5">{p.note}</p>
                </div>
                <SignalBadge signal={p.direction} />
              </div>
            ))}
          </div>
        )}
      </SectionCard>

      {/* Confluence factors */}
      <SectionCard title="Confluence Factors" eyebrow="Full audit trail — nothing is a black box">
        <div className="space-y-2">
          {data.confluence_factors.map((f, i) => (
            <div key={i} className="flex items-start justify-between gap-3 rounded-md border border-base-border bg-base-alt/60 p-3">
              <div>
                <p className="text-sm font-medium text-ink">{f.factor} <span className="text-ink-faint font-normal font-mono text-xs">w={f.weight}</span></p>
                <p className="text-xs text-ink-muted mt-0.5">{f.detail}</p>
              </div>
              <SignalBadge signal={f.signal} />
            </div>
          ))}
        </div>
      </SectionCard>

      {/* Risk warnings */}
      <SectionCard title="Risk Warnings" className="border-gold/20">
        <ul className="space-y-1.5">
          {data.risk_warnings.map((w, i) => (
            <li key={i} className="text-sm text-ink-muted flex gap-2">
              <span className="text-gold">▲</span>
              <span>{w}</span>
            </li>
          ))}
        </ul>
      </SectionCard>
    </div>
  );
}
