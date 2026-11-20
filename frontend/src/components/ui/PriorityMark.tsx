"use client";

import React from "react";
import { cn } from "@/lib/utils";

export interface PriorityMarkProps {
  priority: "Urgent" | "High" | "Medium" | "Low" | string;
  className?: string;
  showLabel?: boolean;
}

/**
 * PriorityMark: Renders ticket priority with neutral outline chip + dot + visible word.
 * - Border: 1px solid #E4DED5, background #FDFCFA, text #1C1B19
 * - Dot: Urgent #B42318, High #D9733A, Medium #6B7C93, Low #A8A196
 * - Word always visible in sentence case
 */
export function PriorityMark({ priority, className, showLabel = true }: PriorityMarkProps) {
  const normalized = priority.charAt(0).toUpperCase() + priority.slice(1).toLowerCase();

  const getDotColor = () => {
    switch (normalized) {
      case "Urgent":
        return "bg-[#B42318]";
      case "High":
        return "bg-[#D9733A]";
      case "Medium":
        return "bg-[#6B7C93]";
      case "Low":
      default:
        return "bg-[#A8A196]";
    }
  };

  const dotClass = getDotColor();

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 h-[22px] px-2 rounded-[6px] text-[12px] font-medium leading-none shrink-0 select-none border border-[#E4DED5] bg-[#FDFCFA] text-[#1C1B19]",
        className
      )}
      title={`Priority: ${normalized}`}
      aria-label={`Priority: ${normalized}`}
    >
      <span className={cn("w-1.5 h-1.5 rounded-full shrink-0", dotClass)} />
      {showLabel && <span>{normalized}</span>}
    </span>
  );
}

// Backward compatibility alias: PriorityChip points to PriorityMark
export const PriorityChip = PriorityMark;
export const PriorityBadge = PriorityMark;
