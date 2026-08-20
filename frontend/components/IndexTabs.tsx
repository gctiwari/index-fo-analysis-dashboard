"use client";
import clsx from "clsx";
import type { IndexMeta } from "@/lib/types";

export default function IndexTabs({
  indices,
  active,
  onChange,
}: {
  indices: IndexMeta[];
  active: string;
  onChange: (key: string) => void;
}) {
  return (
    <div className="flex gap-1 overflow-x-auto scrollbar-thin pb-1">
      {indices.map((idx) => {
        const isActive = idx.key === active;
        return (
          <button
            key={idx.key}
            disabled={!idx.live}
            onClick={() => onChange(idx.key)}
            className={clsx(
              "shrink-0 rounded-md px-3.5 py-2 text-sm font-medium font-display transition-colors border",
              isActive
                ? "bg-gold/10 border-gold/40 text-gold"
                : idx.live
                ? "border-base-border text-ink-muted hover:text-ink hover:border-ink-faint"
                : "border-base-border/50 text-ink-faint cursor-not-allowed"
            )}
            title={idx.live ? undefined : "Live data source not yet connected for this index"}
          >
            {idx.name}
            {!idx.live && <span className="ml-1.5 text-[10px] align-super">soon</span>}
          </button>
        );
      })}
    </div>
  );
}
