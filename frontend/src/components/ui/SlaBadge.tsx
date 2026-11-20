"use client";

import React, { useState, useEffect, useRef } from "react";
import { CheckCircle2, Clock, AlertTriangle, ArrowUpCircle, PauseCircle } from "lucide-react";
import { SLAStatus } from "@/lib/types";
import { cn } from "@/lib/utils";
import { SlaRing } from "./SlaRing";

export interface SlaBadgeProps {
  sla: SLAStatus | { status: string; hours_remaining?: number | null };
  size?: "sm" | "md" | "lg";
  className?: string;
  isEscalated?: boolean;
  showRing?: boolean;
}

/**
 * SlaBadge: Strict one-line SLA status badge.
 * - Always ONE line (whitespace-nowrap, min-width)
 * - Always icon + explicit label (never color alone)
 * - Breached pulses subtly (pulse stops on hover); ONLY red element
 * - At-risk uses distinct yellow-amber (#A16207 / #FACC15), never brand orange
 * - Closed / Stopped is muted slate with no countdown
 */
export function SlaBadge({
  sla,
  size = "sm",
  className,
  isEscalated = false,
  showRing = false,
}: SlaBadgeProps) {
  const [secondsRemaining, setSecondsRemaining] = useState<number | null>(
    sla.hours_remaining !== null && sla.hours_remaining !== undefined
      ? Math.round(sla.hours_remaining * 3600)
      : null
  );

  const prevStatusRef = useRef<string>(sla.status);
  const [announceText, setAnnounceText] = useState<string>("");

  // Announce only when SLA state changes (WCAG polite live region rule)
  useEffect(() => {
    if (prevStatusRef.current !== sla.status) {
      const normalized = sla.status.toLowerCase().replace("_", " ");
      setAnnounceText(`SLA status changed to ${normalized}`);
      prevStatusRef.current = sla.status;
    }
  }, [sla.status]);

  // Keep seconds remaining in sync with prop updates
  useEffect(() => {
    if (sla.hours_remaining !== null && sla.hours_remaining !== undefined) {
      setSecondsRemaining(Math.round(sla.hours_remaining * 3600));
    } else {
      setSecondsRemaining(null);
    }
  }, [sla.hours_remaining]);

  // Live countdown timer (30s interval normally; 1s interval when < 5 mins)
  useEffect(() => {
    if (secondsRemaining === null || sla.status === "STOPPED" || sla.status === "CLOSED") return;

    const isUrgent = Math.abs(secondsRemaining) < 300; // less than 5 minutes
    const intervalMs = isUrgent ? 1000 : 30000;

    const timer = setInterval(() => {
      setSecondsRemaining((prev) => (prev !== null ? prev - (isUrgent ? 1 : 30) : null));
    }, intervalMs);

    return () => clearInterval(timer);
  }, [secondsRemaining, sla.status]);

  // Format countdown string: "10h 3m", "2h 14m", "3d 4h"
  const formatCountdown = (secs: number | null): string => {
    if (secs === null) return "";
    const absSecs = Math.abs(secs);
    const hours = Math.floor(absSecs / 3600);
    const mins = Math.floor((absSecs % 3600) / 60);

    if (hours >= 24) {
      const days = Math.floor(hours / 24);
      const remainingHours = hours % 24;
      return `${days}d ${remainingHours}h`;
    }
    if (hours > 0) {
      return `${hours}h ${mins}m`;
    }
    const s = absSecs % 60;
    if (mins < 5) {
      return `${mins}m ${s}s`;
    }
    return `${mins}m`;
  };

  const sizeClasses = {
    sm: "h-[22px] px-2.5 text-[12px]",
    md: "h-7 px-3 text-caption",
    lg: "h-8 px-3.5 text-body font-semibold",
  };

  const iconSize = size === "sm" ? "w-3.5 h-3.5" : size === "lg" ? "w-4.5 h-4.5" : "w-4 h-4";
  const ringSize = size === "sm" ? 16 : size === "lg" ? 20 : 18;

  // Stopped / Closed: muted slate, no countdown
  if (sla.status === "STOPPED" || sla.status === "CLOSED") {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1.5 rounded-[6px] font-medium whitespace-nowrap min-w-[76px] bg-sla-stopped-bg text-sla-stopped-text border border-sla-stopped-line select-none shrink-0 leading-none",
          sizeClasses[size],
          className
        )}
      >
        {showRing && <SlaRing status="STOPPED" size={ringSize} />}
        <PauseCircle className={cn(iconSize, "shrink-0")} />
        <span>{sla.status === "CLOSED" ? "Closed" : "Stopped"}</span>
      </span>
    );
  }

  // Escalated: violet
  if (isEscalated || sla.status === "ESCALATED") {
    const cd = secondsRemaining !== null ? formatCountdown(secondsRemaining) : "";
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1.5 rounded-[6px] font-semibold whitespace-nowrap min-w-[96px] bg-sla-escalated-bg text-sla-escalated-text border border-[#DDD6FE] select-none shrink-0 leading-none",
          sizeClasses[size],
          className
        )}
      >
        {showRing && <SlaRing status="ESCALATED" hoursRemaining={sla.hours_remaining} size={ringSize} />}
        <ArrowUpCircle className={cn(iconSize, "shrink-0")} />
        <span>Escalated</span>
        {cd && <span className="font-mono-numbers font-medium">{cd}</span>}
        {announceText && <span className="sr-only" aria-live="polite">{announceText}</span>}
      </span>
    );
  }

  // Breached: the ONLY red (pulses subtly, pauses on hover)
  if (sla.status === "BREACHED" || (secondsRemaining !== null && secondsRemaining < 0)) {
    const cd = secondsRemaining !== null ? formatCountdown(secondsRemaining) : "";
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1.5 rounded-[6px] font-semibold whitespace-nowrap min-w-[104px] bg-sla-breached-bg text-sla-breached-text border border-sla-breached-line select-none shrink-0 leading-none animate-sla-breach hover:[animation-play-state:paused]",
          sizeClasses[size],
          className
        )}
      >
        {showRing && <SlaRing status="BREACHED" hoursRemaining={sla.hours_remaining} size={ringSize} showTooltip={false} />}
        <AlertTriangle className={cn(iconSize, "shrink-0")} />
        <span>Breached</span>
        {cd && <span className="font-mono-numbers font-medium">{cd}</span>}
        {announceText && <span className="sr-only" aria-live="polite">{announceText}</span>}
      </span>
    );
  }

  // At risk: yellow-amber (distinct from brand orange!)
  if (sla.status === "AT_RISK") {
    const cd = secondsRemaining !== null ? formatCountdown(secondsRemaining) : "";
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1.5 rounded-[6px] font-semibold whitespace-nowrap min-w-[96px] bg-sla-at_risk-bg text-sla-at_risk-text border border-sla-at_risk-line select-none shrink-0 leading-none",
          sizeClasses[size],
          className
        )}
      >
        {showRing && <SlaRing status="AT_RISK" hoursRemaining={sla.hours_remaining} size={ringSize} />}
        <Clock className={cn(iconSize, "shrink-0")} />
        <span>At risk</span>
        {cd && <span className="font-mono-numbers font-medium">{cd}</span>}
        {announceText && <span className="sr-only" aria-live="polite">{announceText}</span>}
      </span>
    );
  }

  // On track: green
  const cd = secondsRemaining !== null ? formatCountdown(secondsRemaining) : "";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-[6px] font-medium whitespace-nowrap min-w-[96px] bg-sla-normal-bg text-sla-normal-text border border-sla-normal-line select-none shrink-0 leading-none",
        sizeClasses[size],
        className
      )}
    >
      {showRing && <SlaRing status="NORMAL" hoursRemaining={sla.hours_remaining} size={ringSize} />}
      <CheckCircle2 className={cn(iconSize, "shrink-0")} />
      <span>On track</span>
      {cd && <span className="font-mono-numbers">{cd}</span>}
      {announceText && <span className="sr-only" aria-live="polite">{announceText}</span>}
    </span>
  );
}

// Re-export alias
export const SLABadge = SlaBadge;
