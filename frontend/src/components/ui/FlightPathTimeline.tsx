"use client";

import React from "react";
import { Plane } from "lucide-react";
import { cn, parseUtc } from "@/lib/utils";

export interface FlightPathTimelineProps {
  nowDate?: string | Date;
  createdAt?: string | Date;
  lcd?: string | Date | null;
  checkIn?: string | Date | null;
  controllingDeadline?: "LCD" | "CHECK_IN" | "SLA" | string;
  variant?: "compact" | "full";
  className?: string;
}

/**
 * FlightPathTimeline:
 * Dotted arc/track: NOW -> LCD gate -> Check-in with small plane marker.
 * - LCD gate marker clearly indicated
 * - Plane is orange (#EA580C / #F97316)
 * - Plane turns yellow-amber (#A16207 / #FACC15) when approaching gate (< 2h)
 * - Plane turns red (#B91C1C / #F87171) after passing gate
 * - Controlling deadline highlighted and labelled
 * - Compact (table row, overflow-hidden, no layout shifts) and full (ticket) variants
 */
export function FlightPathTimeline({
  nowDate,
  lcd,
  checkIn,
  controllingDeadline,
  variant = "full",
  className,
}: FlightPathTimelineProps) {
  const now = nowDate ? (parseUtc(nowDate)?.getTime() ?? Date.now()) : Date.now();
  const lcdTime = lcd ? (parseUtc(lcd)?.getTime() ?? null) : null;
  const checkInTime = checkIn ? (parseUtc(checkIn)?.getTime() ?? null) : null;

  // Determine past states & deadlines
  const isLcdPast = lcdTime !== null && lcdTime < now;
  const isCheckInPast = checkInTime !== null && checkInTime < now;

  // Identify controlling deadline
  const effectiveControlling =
    controllingDeadline ||
    (lcdTime && !isLcdPast ? "LCD" : checkInTime && !isCheckInPast ? "CHECK_IN" : "LCD");

  // Plane color based on progress toward LCD gate:
  // Brand orange by default; turns yellow-amber approaching gate (< 2h); red after it.
  let planeColorClass = "text-brand-orange";
  let planeColorHex = "#EA580C";
  if (isLcdPast) {
    planeColorClass = "text-red-600 dark:text-red-400";
    planeColorHex = "#B91C1C";
  } else if (lcdTime !== null) {
    const hoursToLcd = (lcdTime - now) / (1000 * 60 * 60);
    if (hoursToLcd <= 2) {
      planeColorClass = "text-amber-600 dark:text-amber-400";
      planeColorHex = "#A16207";
    }
  }

  // Calculate plane progress position (0 to 100%)
  let planeProgressPct = 15;
  if (lcdTime && checkInTime) {
    const totalSpan = checkInTime - now;
    if (totalSpan <= 0) {
      planeProgressPct = 95;
    } else if (isLcdPast) {
      planeProgressPct = 65;
    } else {
      planeProgressPct = 25;
    }
  }

  // Format date helper: "Oct 14, 18:00 IST"
  const formatDate = (dateVal?: string | Date | number | null): string => {
    if (!dateVal) return "N/A";
    const d = parseUtc(dateVal);
    if (!d || isNaN(d.getTime())) return "N/A";
    return d.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
      timeZoneName: "short",
    });
  };

  // Compact Variant (~20px height for table rows, overflow-hidden)
  if (variant === "compact") {
    return (
      <div
        className={cn(
          "flex items-center gap-1.5 h-4 text-[10px] font-mono-numbers select-none w-full max-w-full overflow-hidden",
          className
        )}
        title={`Flight Path: NOW -> LCD Gate (${lcd ? formatDate(lcd) : "None"}) -> Check-in (${checkIn ? formatDate(checkIn) : "None"})`}
      >
        <span className="text-content-tertiary font-medium text-[10px] flex items-center gap-1 shrink-0">
          <Plane className={cn("w-3 h-3 rotate-45 shrink-0", planeColorClass)} />
          <span>NOW</span>
        </span>

        {/* Responsive Track spanning available width */}
        <div className="relative flex-1 min-w-[32px] h-1 bg-surface-subtle rounded-full flex items-center border border-border overflow-visible mx-0.5">
          <div className="absolute inset-0 border-b border-dashed border-border-strong top-0" />
          {/* LCD Gate Marker */}
          <div
            className={cn(
              "absolute left-1/2 -translate-x-1/2 w-2 h-2 rounded-full border",
              isLcdPast
                ? "bg-slate-400 border-slate-300"
                : effectiveControlling === "LCD"
                ? "bg-amber-500 border-white ring-2 ring-amber-400/40"
                : "bg-brand-orange border-white"
            )}
            title={lcd ? `LCD Gate: ${formatDate(lcd)}` : "No LCD deadline"}
          />
          {/* Check-in Marker */}
          <div
            className={cn(
              "absolute right-0 w-2 h-2 rounded-full border",
              isCheckInPast
                ? "bg-slate-400 border-slate-300"
                : effectiveControlling === "CHECK_IN"
                ? "bg-brand-orange border-white ring-2 ring-brand-orange/40"
                : "bg-slate-400 border-white"
            )}
            title={checkIn ? `Check-in: ${formatDate(checkIn)}` : "No check-in date"}
          />
        </div>

        {/* Concise Controlling milestone indicator */}
        <span
          className={cn(
            "text-[9px] font-medium uppercase tracking-wider shrink-0 px-1 py-0.2 rounded font-mono-numbers",
            effectiveControlling === "LCD"
              ? "text-amber-700 bg-amber-50 dark:bg-amber-950/40 dark:text-amber-300 border border-amber-200/60 dark:border-amber-800/60"
              : "text-brand bg-brand-soft border border-line"
          )}
          title={
            effectiveControlling === "LCD"
              ? `Controlled by LCD Gate (${lcd ? formatDate(lcd) : "N/A"})`
              : `Controlled by Check-in (${checkIn ? formatDate(checkIn) : "N/A"})`
          }
        >
          {effectiveControlling === "LCD" ? "Gate" : "In"}
        </span>
      </div>
    );
  }

  // Full Variant (Signature Mission Control Graphic)
  return (
    <div className={cn("w-full flex flex-col gap-2 select-none py-2", className)}>
      {/* SVG Arc Track with Plane Marker */}
      <div className="relative w-full h-12 flex items-center">
        <svg
          viewBox="0 0 400 48"
          preserveAspectRatio="none"
          className="w-full h-12 overflow-visible"
        >
          {/* Dotted arc track */}
          <path
            d="M 20 36 Q 200 6, 380 36"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeDasharray="4 4"
            className="text-border-strong"
          />
          {/* Active progress arc segment */}
          <path
            d={isLcdPast ? "M 20 36 Q 200 6, 380 36" : "M 20 36 Q 110 20, 200 21"}
            fill="none"
            stroke={isLcdPast ? "#94A3B8" : planeColorHex}
            strokeWidth="2.5"
          />
        </svg>

        {/* Milestone 1: NOW with moving Plane marker */}
        <div
          className="absolute -translate-x-1/2 -translate-y-1/2 flex flex-col items-center z-20 transition-all duration-300"
          style={{
            left: `${planeProgressPct}%`,
            top: planeProgressPct < 50 ? "24px" : "30px",
          }}
        >
          <div
            className="w-7 h-7 rounded-full bg-surface border-2 shadow-xs flex items-center justify-center transition-colors"
            style={{ borderColor: planeColorHex }}
            title={`Plane position: ${isLcdPast ? "Past LCD Gate" : "En route"}`}
          >
            <Plane className={cn("w-4 h-4 rotate-45", planeColorClass)} />
          </div>
        </div>

        {/* Milestone 2: LCD Gate (50% position) */}
        <div className="absolute left-1/2 -translate-x-1/2 top-4 flex flex-col items-center z-10">
          <div
            className={cn(
              "w-4 h-4 rounded-full border-2 shadow-xs transition-subtle flex items-center justify-center",
              isLcdPast
                ? "bg-slate-300 border-slate-400"
                : effectiveControlling === "LCD"
                ? "bg-amber-500 border-white ring-4 ring-amber-400/20"
                : "bg-surface border-border-strong"
            )}
          >
            <div className="w-1.5 h-1.5 rounded-full bg-white" />
          </div>
        </div>

        {/* Milestone 3: Check-in (100% position) */}
        <div className="absolute right-4 -translate-x-1/2 top-7 flex flex-col items-center z-10">
          <div
            className={cn(
              "w-4 h-4 rounded-full border-2 shadow-xs transition-subtle",
              isCheckInPast
                ? "bg-slate-300 border-slate-400"
                : effectiveControlling === "CHECK_IN"
                ? "bg-brand-orange border-white ring-4 ring-brand-orange/20"
                : "bg-surface border-border-strong"
            )}
          />
        </div>
      </div>

      {/* Milestone Labels Row */}
      <div className="relative flex justify-between items-start text-[12px] pt-1">
        {/* NOW */}
        <div className="flex flex-col items-start text-left">
          <span className="font-semibold text-content-primary flex items-center gap-1">
            <span>NOW</span>
          </span>
          <span className="text-[11px] text-content-tertiary font-mono-numbers">
            {formatDate(now)}
          </span>
        </div>

        {/* LCD Gate Marker Label */}
        <div className="flex flex-col items-center text-center">
          <div className="flex items-center gap-1">
            <span
              className={cn(
                "font-medium",
                isLcdPast
                  ? "text-content-disabled line-through"
                  : effectiveControlling === "LCD"
                  ? "text-amber-700 dark:text-amber-400 font-semibold"
                  : "text-content-secondary"
              )}
            >
              LCD Gate
            </span>
            {effectiveControlling === "LCD" && !isLcdPast && (
              <span className="text-[10px] font-semibold uppercase tracking-wider bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300 border border-amber-200 dark:border-amber-800 px-1.5 py-0.5 rounded-full">
                Controlling
              </span>
            )}
          </div>
          <span
            className={cn(
              "text-[11px] font-mono-numbers",
              isLcdPast
                ? "text-content-disabled line-through"
                : "text-content-tertiary"
            )}
          >
            {formatDate(lcd)}
          </span>
        </div>

        {/* Check-in Label */}
        <div className="flex flex-col items-end text-right">
          <div className="flex items-center gap-1">
            {effectiveControlling === "CHECK_IN" && !isCheckInPast && (
              <span className="text-[10px] font-semibold uppercase tracking-wider bg-brand-soft text-brand border border-line px-1.5 py-0.5 rounded-full">
                Controlling
              </span>
            )}
            <span
              className={cn(
                "font-medium",
                isCheckInPast
                  ? "text-content-disabled line-through"
                  : effectiveControlling === "CHECK_IN"
                  ? "text-brand-orange-text dark:text-brand-orange font-semibold"
                  : "text-content-secondary"
              )}
            >
              Check-in
            </span>
          </div>
          <span
            className={cn(
              "text-[11px] font-mono-numbers",
              isCheckInPast
                ? "text-content-disabled line-through"
                : "text-content-tertiary"
            )}
          >
            {formatDate(checkIn)}
          </span>
        </div>
      </div>
    </div>
  );
}

// Re-export alias for TravelTimeline backward compatibility
export const TravelTimeline = FlightPathTimeline;
