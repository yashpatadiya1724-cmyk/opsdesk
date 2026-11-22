"use client";

import React, { useState, useEffect } from "react";
import { cn } from "@/lib/utils";
import { Tooltip } from "./Tooltip";

export interface SlaRingProps {
  status?: "NORMAL" | "AT_RISK" | "BREACHED" | "ESCALATED" | "STOPPED" | "CLOSED" | string;
  progress?: number; // 0 to 1
  hoursRemaining?: number | null;
  totalHours?: number; // default 24
  size?: number; // 16 to 20px, default 18
  showTooltip?: boolean;
  className?: string;
}

/**
 * SlaRing: 16-20px circular ring that fills as the SLA deadline nears.
 * On hover, shows elapsed percentage and ticking seconds remaining.
 */
export function SlaRing({
  status = "NORMAL",
  progress,
  hoursRemaining,
  totalHours = 24,
  size = 18,
  showTooltip = true,
  className,
}: SlaRingProps) {
  const normalizedStatus = status.toUpperCase();

  // Ticking seconds state for live hover detail
  const [secondsLeft, setSecondsLeft] = useState<number | null>(
    hoursRemaining !== null && hoursRemaining !== undefined
      ? Math.round(hoursRemaining * 3600)
      : null
  );

  useEffect(() => {
    if (hoursRemaining !== null && hoursRemaining !== undefined) {
      setSecondsLeft(Math.round(hoursRemaining * 3600));
    }
  }, [hoursRemaining]);

  useEffect(() => {
    if (secondsLeft === null || normalizedStatus === "STOPPED" || normalizedStatus === "CLOSED") return;
    const interval = setInterval(() => {
      setSecondsLeft((prev) => (prev !== null ? prev - 1 : null));
    }, 1000);
    return () => clearInterval(interval);
  }, [secondsLeft, normalizedStatus]);

  // Determine progress ratio (0 to 1, fills as deadline approaches)
  let ratio = 0;
  if (typeof progress === "number") {
    ratio = Math.max(0, Math.min(1, progress));
  } else if (hoursRemaining !== null && hoursRemaining !== undefined) {
    if (hoursRemaining <= 0 || normalizedStatus === "BREACHED") {
      ratio = 1;
    } else {
      ratio = Math.max(0, Math.min(1, 1 - hoursRemaining / totalHours));
    }
  } else if (normalizedStatus === "BREACHED") {
    ratio = 1;
  } else if (normalizedStatus === "AT_RISK") {
    ratio = 0.75;
  } else if (normalizedStatus === "NORMAL") {
    ratio = 0.25;
  }

  // Geometry
  const strokeWidth = 2.5;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference - ratio * circumference;

  // Semantic color mapping
  const colorClasses: Record<string, { track: string; stroke: string }> = {
    NORMAL: { track: "text-sla-normal-bg", stroke: "text-sla-normal-text" },
    AT_RISK: { track: "text-sla-at_risk-bg", stroke: "text-sla-at_risk-text" },
    BREACHED: { track: "text-sla-breached-bg", stroke: "text-sla-breached-text" },
    ESCALATED: { track: "text-sla-escalated-bg", stroke: "text-sla-escalated-text" },
    STOPPED: { track: "text-sla-stopped-bg", stroke: "text-sla-stopped-text" },
    CLOSED: { track: "text-sla-stopped-bg", stroke: "text-sla-stopped-text" },
  };

  const scheme = colorClasses[normalizedStatus] || colorClasses.NORMAL;
  const isBreached = normalizedStatus === "BREACHED";
  const pctDisplay = Math.round(ratio * 100);

  const ringElement = (
    <div
      role="img"
      className={cn(
        "inline-flex items-center justify-center shrink-0 cursor-pointer",
        isBreached && "animate-sla-breach hover:[animation-play-state:paused]",
        className
      )}
      style={{ width: size, height: size }}
      aria-label={`SLA Ring: ${pctDisplay}% elapsed`}
    >
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        className="rotate-[-90deg] overflow-visible"
      >
        {/* Track */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={strokeWidth}
          className={cn("stroke-current transition-colors duration-200", scheme.track)}
        />
        {/* Progress Fill */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={strokeWidth}
          strokeDasharray={circumference}
          strokeDashoffset={strokeDashoffset}
          strokeLinecap="round"
          className={cn("stroke-current transition-all duration-300 ease-out", scheme.stroke)}
        />
      </svg>
    </div>
  );

  if (!showTooltip) return ringElement;

  const tooltipText =
    secondsLeft !== null
      ? `${pctDisplay}% elapsed (${Math.abs(secondsLeft)}s remaining)`
      : `${pctDisplay}% SLA elapsed`;

  return (
    <Tooltip content={tooltipText} position="top">
      {ringElement}
    </Tooltip>
  );
}
