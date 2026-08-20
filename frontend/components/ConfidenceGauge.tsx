"use client";

const SIZE = 148;
const STROKE = 10;
const R = (SIZE - STROKE) / 2;
const CIRC = 2 * Math.PI * R;
const ARC_FRACTION = 0.75; // 270-degree arc, terminal-gauge feel rather than a full circle

export default function ConfidenceGauge({
  value,
  bias,
}: {
  value: number;
  bias: "Bullish" | "Bearish" | "Neutral";
}) {
  const color = bias === "Bullish" ? "#33C77E" : bias === "Bearish" ? "#F1555C" : "#8A93A8";
  const arcLen = CIRC * ARC_FRACTION;
  const filled = (value / 100) * arcLen;
  const rotateOffset = 135; // start angle so the open gap sits at the bottom

  return (
    <div className="relative flex items-center justify-center" style={{ width: SIZE, height: SIZE }}>
      <svg width={SIZE} height={SIZE} className="-rotate-0">
        <circle
          cx={SIZE / 2}
          cy={SIZE / 2}
          r={R}
          fill="none"
          stroke="#1A2334"
          strokeWidth={STROKE}
          strokeDasharray={`${arcLen} ${CIRC}`}
          strokeDashoffset={0}
          strokeLinecap="round"
          transform={`rotate(${rotateOffset} ${SIZE / 2} ${SIZE / 2})`}
        />
        <circle
          cx={SIZE / 2}
          cy={SIZE / 2}
          r={R}
          fill="none"
          stroke={color}
          strokeWidth={STROKE}
          strokeDasharray={`${filled} ${CIRC}`}
          strokeDashoffset={0}
          strokeLinecap="round"
          transform={`rotate(${rotateOffset} ${SIZE / 2} ${SIZE / 2})`}
          style={{ transition: "stroke-dasharray 0.6s ease" }}
        />
      </svg>
      <div className="absolute flex flex-col items-center">
        <span className="font-display text-3xl font-semibold tabular" style={{ color }}>
          {value.toFixed(0)}
        </span>
        <span className="text-[10px] uppercase tracking-widest text-ink-faint mt-0.5">confidence</span>
      </div>
    </div>
  );
}
