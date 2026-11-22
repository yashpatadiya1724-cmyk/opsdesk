"use client";

import React, { useMemo, useState } from "react";
import { TicketSummary } from "@/lib/types";
import { CountUp } from "@/components/ui";
import { cn } from "@/lib/utils";

export interface QueueKpiStripProps {
  tickets: TicketSummary[];
  activeFilter?: string;
  onFilterClick?: (filterType: "ALL" | "OPEN" | "AT_RISK" | "BREACHED" | "UNASSIGNED") => void;
  className?: string;
}

export function QueueKpiStrip({
  tickets,
  activeFilter,
  onFilterClick,
  className,
}: QueueKpiStripProps) {
  const [hoveredKey, setHoveredKey] = useState<string | null>(null);

  const stats = useMemo(() => {
    const total = tickets.length;
    const openCount = tickets.filter(
      (t) => t.status !== "Closed" && t.status !== "Resolved"
    ).length;
    const onTrackCount = tickets.filter(
      (t) => t.sla.status === "NORMAL" && t.status !== "Closed" && t.status !== "Resolved"
    ).length;
    const atRiskCount = tickets.filter((t) => t.sla.status === "AT_RISK").length;
    const breachedCount = tickets.filter((t) => t.sla.status === "BREACHED").length;
    const unassignedCount = tickets.filter((t) => !t.assigned_to).length;

    return {
      total,
      openCount,
      onTrackCount,
      atRiskCount,
      breachedCount,
      unassignedCount,
    };
  }, [tickets]);

  const safeSum = stats.total === 0 ? 1 : stats.total;

  const segments = [
    {
      key: "OPEN" as const,
      label: "Open",
      count: stats.openCount,
      barCount: stats.onTrackCount,
      pct: (stats.onTrackCount / safeSum) * 100,
      color: "bg-emerald-600 dark:bg-emerald-500",
      textColor: "text-emerald-700 dark:text-emerald-400",
    },
    {
      key: "AT_RISK" as const,
      label: "At risk",
      count: stats.atRiskCount,
      barCount: stats.atRiskCount,
      pct: (stats.atRiskCount / safeSum) * 100,
      color: "bg-amber-500 dark:bg-amber-400",
      textColor: "text-amber-700 dark:text-amber-400",
    },
    {
      key: "BREACHED" as const,
      label: "Breached",
      count: stats.breachedCount,
      barCount: stats.breachedCount,
      pct: (stats.breachedCount / safeSum) * 100,
      color: "bg-rose-600 dark:bg-rose-500",
      textColor: "text-rose-700 dark:text-rose-400",
    },
    {
      key: "UNASSIGNED" as const,
      label: "Unassigned",
      count: stats.unassignedCount,
      barCount: stats.unassignedCount,
      pct: Math.min((stats.unassignedCount / safeSum) * 100, 100),
      color: "bg-slate-400 dark:bg-slate-500",
      textColor: "text-slate-700 dark:text-slate-400",
    },
  ];

  const handleSegmentClick = (key: "OPEN" | "AT_RISK" | "BREACHED" | "UNASSIGNED") => {
    if (!onFilterClick) return;
    if (activeFilter === key) {
      onFilterClick("ALL");
    } else {
      onFilterClick(key);
    }
  };

  return (
    <div
      className={cn(
        "bg-surface border border-border rounded-card p-4 shadow-xs select-none flex flex-col gap-3",
        className
      )}
    >
      {/* Header with Title & Active Queue Summary */}
      <div className="flex items-center justify-between text-caption text-content-secondary">
        <span className="font-semibold text-content-primary flex items-center gap-2 text-table">
          <span className="w-2 h-2 rounded-full bg-brand-500" />
          Queue Health &amp; SLA Breakdown
        </span>
        <span className="text-[12px] font-mono-numbers">
          Loaded: <strong className="text-content-primary font-bold">{stats.total}</strong> tickets
        </span>
      </div>

      {/* Stacked SLA Split Bar */}
      <div
        className="w-full h-3.5 rounded-full bg-surface-subtle overflow-hidden flex items-center p-0.5 border border-border"
        role="presentation"
        aria-hidden="true"
      >
        {segments.map((seg) => {
          if (seg.barCount <= 0) return null;
          const isHovered = hoveredKey === seg.key;
          const isDimmed = hoveredKey !== null && !isHovered;
          const isSelected = activeFilter === seg.key;

          return (
            <span
              key={seg.key}
              style={{ width: `${Math.max(4, seg.pct)}%` }}
              className={cn(
                "h-full rounded-full transition-all duration-150",
                seg.color,
                isHovered && "scale-y-125 z-10 brightness-110",
                isDimmed && "opacity-40",
                isSelected && "ring-2 ring-content-primary scale-y-110"
              )}
            />
          );
        })}
      </div>

      {/* Legend Counts Beneath with CountUp */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-1 border-t border-border/50">
        {segments.map((seg) => {
          const isHovered = hoveredKey === seg.key;
          const isSelected = activeFilter === seg.key;

          return (
            <button
              key={seg.key}
              type="button"
              onClick={() => handleSegmentClick(seg.key)}
              onMouseEnter={() => setHoveredKey(seg.key)}
              onMouseLeave={() => setHoveredKey(null)}
              className={cn(
                "flex items-center justify-between px-3 py-1.5 rounded-input transition-subtle cursor-pointer border text-left",
                isSelected
                  ? "border-border-strong bg-surface-subtle shadow-xs ring-1 ring-border-strong"
                  : isHovered
                  ? "border-border bg-surface-subtle"
                  : "border-transparent hover:bg-surface-subtle/60"
              )}
              aria-label={`Filter by ${seg.label} cases`}
            >
              <div className="flex items-center gap-1.5 min-w-0">
                <span className={cn("w-2 h-2 rounded-full shrink-0", seg.color)} />
                <span className="text-caption font-medium text-content-secondary truncate">
                  {seg.label}
                </span>
              </div>
              <span className={cn("font-mono-numbers font-bold text-table ml-2", seg.textColor)}>
                <CountUp end={seg.count} durationMs={600} />
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
