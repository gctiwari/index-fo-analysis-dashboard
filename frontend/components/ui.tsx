"use client";
import clsx from "clsx";

export function SignalBadge({ signal }: { signal: "bullish" | "bearish" | "neutral" }) {
  const map = {
    bullish: "text-signal-bull bg-signal-bull/10 border-signal-bull/30",
    bearish: "text-signal-bear bg-signal-bear/10 border-signal-bear/30",
    neutral: "text-ink-muted bg-white/5 border-base-border",
  };
  return (
    <span className={clsx("text-[11px] font-medium px-2 py-0.5 rounded-full border uppercase tracking-wide", map[signal])}>
      {signal}
    </span>
  );
}

export function RiskBadge({ level }: { level: "Low" | "Medium" | "High" }) {
  const map = {
    Low: "text-signal-bull bg-signal-bull/10 border-signal-bull/30",
    Medium: "text-gold bg-gold/10 border-gold/30",
    High: "text-signal-bear bg-signal-bear/10 border-signal-bear/30",
  };
  return (
    <span className={clsx("text-[11px] font-medium px-2 py-0.5 rounded-full border uppercase tracking-wide", map[level])}>
      {level} risk
    </span>
  );
}

export function SectionCard({
  title,
  eyebrow,
  children,
  className,
}: {
  title: string;
  eyebrow?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={clsx("panel p-5", className)}>
      {eyebrow && <p className="text-[11px] uppercase tracking-widest text-gold/80 mb-1 font-medium">{eyebrow}</p>}
      <h3 className="font-display text-lg font-semibold text-ink mb-3">{title}</h3>
      {children}
    </div>
  );
}

export function StatTile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-md border border-base-border bg-base-alt/60 px-3 py-2.5">
      <p className="text-[10px] uppercase tracking-wider text-ink-faint">{label}</p>
      <p className="font-mono text-base font-medium text-ink tabular mt-0.5">{value}</p>
      {sub && <p className="text-[11px] text-ink-muted mt-0.5">{sub}</p>}
    </div>
  );
}

export function LoadingPanel({ label }: { label: string }) {
  return (
    <div className="panel p-8 flex flex-col items-center justify-center gap-3 text-ink-muted">
      <div className="h-8 w-8 rounded-full border-2 border-gold/30 border-t-gold animate-spin" />
      <p className="text-sm">{label}</p>
    </div>
  );
}

export function ErrorPanel({ message }: { message: string }) {
  return (
    <div className="panel p-6 border-signal-bear/30 bg-signal-bear/5">
      <p className="text-sm text-signal-bear font-medium mb-1">Couldn&apos;t load this view</p>
      <p className="text-sm text-ink-muted">{message}</p>
    </div>
  );
}
