"use client";

import React, { useState } from "react";
import { cn } from "@/lib/utils";

export interface SlaCounts {
  onTrack: number;
  atRisk: number;
  breached: number;
  escalated: number;
}

export interface HealthBarProps {
  counts: SlaCounts;
  total?: number;
  onFilterClick?: (status: "NORMAL" | "AT_RISK" | "BREACHED" | "ESCALATED" | "ALL") => void;
  selectedStatus?: string;
  className?: string;
  asPanel?: boolean;
}

/**
 * HealthBar: Visual SLA dispatch health breakdown.
 * - Large 24px rounded surface when asPanel=true (rounded-[24px])
 * - On track: #15803D (light) / #4ADE80 (dark)
 * - At risk: #A16207 (light) / #FACC15 (dark) - Yellow, distinct from brand orange!
 * - Breached: #B91C1C (light) / #F87171 (dark) - The ONLY red!
 * - Escalated: #6D28D9 (light) / #A78BFA (dark)
 */
export function HealthBar({
  counts,
  total,
  onFilterClick,
  selectedStatus,
  className,
  asPanel = false,
}: HealthBarProps) {
  const [hoveredKey, setHoveredKey] = useState<string | null>(null);

  const sum = total || (counts.onTrack + counts.atRisk + counts.breached + counts.escalated);
  const safeSum = sum === 0 ? 1 : sum;

  const segments = [
    {
      key: "NORMAL" as const,
      label: "On track",
      count: counts.onTrack,
      pct: (counts.onTrack / safeSum) * 100,
      color: "bg-[#15803D] dark:bg-[#4ADE80]",
      textColor: "text-[#15803D] dark:text-[#4ADE80]",
    },
    {
      key: "AT_RISK" as const,
      label: "At risk",
      count: counts.atRisk,
      pct: (counts.atRisk / safeSum) * 100,
      color: "bg-[#A16207] dark:bg-[#FACC15]",
      textColor: "text-[#A16207] dark:text-[#FACC15]",
    },
    {
      key: "BREACHED" as const,
      label: "Breached",
      count: counts.breached,
      pct: (counts.breached / safeSum) * 100,
      color: "bg-[#B91C1C] dark:bg-[#F87171]",
      textColor: "text-[#B91C1C] dark:text-[#F87171]",
    },
    {
      key: "ESCALATED" as const,
      label: "Escalated",
      count: counts.escalated,
      pct: (counts.escalated / safeSum) * 100,
      color: "bg-[#6D28D9] dark:bg-[#A78BFA]",
      textColor: "text-[#6D28D9] dark:text-[#A78BFA]",
    },
  ];

  const content = (
    <div className={cn("w-full flex flex-col gap-2 select-none", !asPanel && className)}>
      {/* Stacked SLA Split Bar */}
      <div
        className="w-full h-3 rounded-full bg-surface-subtle overflow-hidden flex items-center p-0.5 border border-border"
        role="presentation"
        aria-hidden="true"
      >
        {segments.map((seg) => {
          if (seg.pct <= 0) return null;
          const isHovered = hoveredKey === seg.key;
          const isDimmed = hoveredKey !== null && !isHovered;
          const isSelected = selectedStatus === seg.key;

          return (
            <span
              key={seg.key}
              style={{ width: `${seg.pct}%` }}
              className={cn(
                "h-full rounded-full transition-all duration-120",
                seg.color,
                isHovered && "scale-y-125 z-10 brightness-110",
                isDimmed && "opacity-40",
                isSelected && "ring-2 ring-content-primary"
              )}
            />
          );
        })}
      </div>

      {/* Legend Counts with Filter Trigger */}
      <div className="flex items-center justify-between flex-wrap gap-2 text-[12px] pt-1">
        {segments.map((seg) => {
          const isHovered = hoveredKey === seg.key;
          const isSelected = selectedStatus === seg.key;

          return (
            <button
              key={seg.key}
              type="button"
              onClick={() => onFilterClick?.(isSelected ? "ALL" : seg.key)}
              onMouseEnter={() => setHoveredKey(seg.key)}
              onMouseLeave={() => setHoveredKey(null)}
              className={cn(
                "inline-flex items-center gap-1.5 px-2.5 py-1 min-h-[24px] rounded-full transition-subtle cursor-pointer border border-transparent font-medium",
                isSelected ? "border-border-strong bg-surface shadow-xs" : "hover:bg-surface-subtle",
                isHovered && "bg-surface shadow-xs"
              )}
            >
              <span className={cn("w-2 h-2 rounded-full shrink-0", seg.color)} />
              <span className="text-content-secondary">{seg.label}:</span>
              <span className={cn("font-mono-numbers font-semibold", seg.textColor)}>
                {seg.count}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );

  if (asPanel) {
    return (
      <div className={cn("bg-surface border border-border rounded-[24px] p-4 shadow-sm", className)}>
        {content}
      </div>
    );
  }

  return content;
}
