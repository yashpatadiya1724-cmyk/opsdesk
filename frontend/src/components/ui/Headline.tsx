"use client";

import React from "react";
import { cn } from "@/lib/utils";

export interface PageHeadlineProps extends React.HTMLAttributes<HTMLDivElement> {
  eyebrow?: string;
  primaryTitle: string;
  emphasisWord?: string;
  badge?: React.ReactNode;
  subtitle?: string;
}

/**
 * Signature Headline Pattern (for page titles H1):
 * - Small orange eyebrow label above (e.g., "LIVE OPERATIONS")
 * - Two-tone title where emphasis word is orange italic (e.g. "Operations" in navy + "Queue" in orange italic)
 * - Optional badge and subtitle
 */
export function PageHeadline({
  eyebrow,
  primaryTitle,
  emphasisWord,
  badge,
  subtitle,
  className,
  ...props
}: PageHeadlineProps) {
  return (
    <div className={cn("min-w-0 flex flex-col gap-1", className)} {...props}>
      {eyebrow && (
        <span className="text-[11px] font-semibold uppercase tracking-wider text-brand-orange-text dark:text-brand-orange select-none">
          {eyebrow}
        </span>
      )}
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-page sm:text-2xl font-bold tracking-tight text-content-primary font-heading">
          {primaryTitle}{" "}
          {emphasisWord && (
            <span className="text-brand-orange-text dark:text-brand-orange italic font-heading">
              {emphasisWord}
            </span>
          )}
        </h1>
        {badge && <div className="shrink-0">{badge}</div>}
      </div>
      {subtitle && (
        <div className="text-caption text-content-tertiary max-w-2xl">
          {subtitle}
        </div>
      )}
    </div>
  );
}

export function Eyebrow({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <span
      className={cn(
        "text-[11px] font-semibold uppercase tracking-wider text-brand-orange-text dark:text-brand-orange select-none",
        className
      )}
    >
      {children}
    </span>
  );
}
