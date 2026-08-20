"use client";
import useSWR from "swr";
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine,
} from "recharts";
import { fetcher } from "@/lib/api";
import type { EquityCurvePoint } from "@/lib/trackingTypes";
import { SectionCard, LoadingPanel, ErrorPanel } from "@/components/ui";

export default function EquityCurveChart({ path, title }: { path: string; title: string }) {
  const { data, error, isLoading } = useSWR<EquityCurvePoint[]>(path, fetcher, { refreshInterval: 60_000 });

  if (isLoading) return <LoadingPanel label="Loading equity curve…" />;
  if (error) return <ErrorPanel message={error.message} />;
  if (!data) return null;

  const closedTrades = data.filter((d) => d.outcome !== "START");
  const finalPnl = data[data.length - 1]?.cumulative_pnl_rupees ?? 0;
  const lineColor = finalPnl >= 0 ? "#33C77E" : "#F1555C";

  return (
    <SectionCard title={title} eyebrow={`${closedTrades.length} closed trade${closedTrades.length === 1 ? "" : "s"}`}>
      {closedTrades.length === 0 ? (
        <p className="text-sm text-ink-faint">No closed trades yet — the equity curve fills in as paper trades settle.</p>
      ) : (
        <div className="h-64 -ml-2">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#232D40" vertical={false} />
              <XAxis
                dataKey="seq"
                tick={{ fill: "#5B6478", fontSize: 11 }}
                axisLine={{ stroke: "#232D40" }}
                tickLine={false}
                tickFormatter={(v) => (v === 0 ? "start" : `#${v}`)}
              />
              <YAxis
                tick={{ fill: "#5B6478", fontSize: 11 }}
                axisLine={{ stroke: "#232D40" }}
                tickLine={false}
                tickFormatter={(v) => `₹${v.toLocaleString("en-IN")}`}
                width={70}
              />
              <ReferenceLine y={0} stroke="#5B6478" strokeDasharray="2 2" />
              <Tooltip
                contentStyle={{ background: "#111826", border: "1px solid #232D40", borderRadius: 8, fontSize: 12 }}
                labelStyle={{ color: "#8A93A8" }}
                formatter={(value: number, name: string) => [`₹${value.toLocaleString("en-IN")}`, "Cumulative P&L"]}
                labelFormatter={(_, payload) => {
                  const p = payload?.[0]?.payload as EquityCurvePoint | undefined;
                  if (!p || p.outcome === "START") return "Start";
                  return `${p.trade_date} · ${p.index} · ${p.outcome?.replace("_", " ")}`;
                }}
              />
              <Line
                type="monotone"
                dataKey="cumulative_pnl_rupees"
                stroke={lineColor}
                strokeWidth={2}
                dot={{ r: 3, fill: lineColor, strokeWidth: 0 }}
                activeDot={{ r: 5 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      <p className="text-xs text-ink-faint mt-2">Running total of closed paper-trade P&amp;L (₹ per 1 lot), in the order trades were closed.</p>
    </SectionCard>
  );
}
