"use client";

import React from "react";
import Link from "next/link";
import {
  ExternalLink,
  Clock,
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Sparkles,
} from "lucide-react";
import { Drawer } from "@/components/ui";
import { ThemeInsight } from "@/lib/types";
import { getThemeMeta } from "./themeData";

export interface ThemeDetailDrawerProps {
  theme: ThemeInsight | null;
  days: number;
  isOpen: boolean;
  onClose: () => void;
}

export function ThemeDetailDrawer({
  theme,
  days,
  isOpen,
  onClose,
}: ThemeDetailDrawerProps) {
  if (!theme) return null;

  const meta = getThemeMeta(theme.theme);
  const estimatedHours = Math.round(theme.count * meta.avgHoursPerIncident);

  return (
    <Drawer
      isOpen={isOpen}
      onClose={onClose}
      title={theme.theme}
      subtitle={`${theme.count.toLocaleString()} cases (${theme.percentage}% of ${days}-day volume)`}
      width="lg"
    >
      <div className="space-y-6 pt-2">
        {/* Incident Metrics Grid */}
        <div className="grid grid-cols-3 gap-3">
          <div className="p-3 bg-surface-subtle border border-border rounded-card">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-content-tertiary block mb-1">
              Incident count
            </span>
            <span className="text-xl font-semibold font-mono font-mono-numbers text-content-primary">
              {theme.count.toLocaleString()}
            </span>
          </div>

          <div className="p-3 bg-surface-subtle border border-border rounded-card">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-content-tertiary block mb-1">
              Volume share
            </span>
            <span className="text-xl font-semibold font-mono font-mono-numbers text-brand-orange dark:text-brand-orange-text">
              {theme.percentage}%
            </span>
          </div>

          <div className="p-3 bg-surface-subtle border border-border rounded-card">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-content-tertiary block mb-1">
              Estimated impact
            </span>
            <span className="text-xl font-semibold font-mono font-mono-numbers text-amber-700 dark:text-amber-400 flex items-center gap-1">
              <Clock className="w-4 h-4 text-amber-600 dark:text-amber-400 shrink-0" />
              <span>{estimatedHours.toLocaleString()}h</span>
            </span>
          </div>
        </div>

        {/* Operational Overview */}
        <div className="p-4 bg-surface rounded-card border border-border shadow-xs space-y-2">
          <div className="flex items-center gap-2 text-caption font-semibold text-content-primary">
            <Sparkles className="w-4 h-4 text-brand-orange dark:text-brand-orange-text shrink-0" />
            <span>Operational overview</span>
          </div>
          <p className="text-body text-content-secondary leading-relaxed">
            {meta.operationalSummary}
          </p>
        </div>

        {/* Root Cause Analysis */}
        <div className="p-4 bg-amber-50/70 dark:bg-amber-950/30 border border-amber-200/80 dark:border-amber-900/60 rounded-card space-y-2">
          <div className="flex items-center gap-2 text-caption font-semibold text-amber-900 dark:text-amber-200">
            <AlertTriangle className="w-4 h-4 text-amber-600 dark:text-amber-400 shrink-0" />
            <span>Root cause analysis</span>
          </div>
          <p className="text-body text-amber-950/90 dark:text-amber-300 leading-relaxed">
            {meta.rootCause}
          </p>
        </div>

        {/* SOP Recommendations */}
        <div className="p-4 bg-brand-50/60 dark:bg-brand-50/20 border border-brand-200/80 dark:border-brand-500/30 rounded-card space-y-2">
          <div className="flex items-center gap-2 text-caption font-semibold text-brand">
            <CheckCircle2 className="w-4 h-4 text-brand shrink-0" />
            <span>SOP recommendations</span>
          </div>
          <p className="text-body text-ink leading-relaxed">
            {meta.recommendedAction}
          </p>
        </div>

        {/* All Representative Tickets linking to /ticket/[id] */}
        <div>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-caption font-semibold text-content-primary uppercase tracking-wider">
              Representative tickets ({theme.sample_ticket_ids?.length || 0})
            </h3>
            <span className="text-[11px] text-content-tertiary font-mono-numbers">
              Click to open case timeline
            </span>
          </div>

          <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
            {theme.sample_ticket_ids && theme.sample_ticket_ids.length > 0 ? (
              theme.sample_ticket_ids.map((id) => (
                <Link
                  key={id}
                  href={`/ticket/${id}`}
                  className="min-h-[44px] flex items-center justify-between p-3 rounded-input bg-surface border border-border hover:border-brand-400 hover:bg-brand-50/20 dark:hover:bg-brand-50/10 transition-subtle group shadow-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2 focus-visible:ring-offset-canvas"
                >
                  <div className="flex items-center gap-3">
                    <span className="font-mono font-mono-numbers font-semibold text-brand-700 dark:text-brand-orange-text bg-brand-50 dark:bg-brand-50/20 px-2 py-0.5 rounded border border-brand-200 dark:border-brand-500/30 text-caption">
                      {id}
                    </span>
                    <span className="text-caption text-content-secondary group-hover:text-content-primary transition-subtle">
                      Inspect ticket details, GDS records, and communication thread
                    </span>
                  </div>
                  <ArrowRight className="w-4 h-4 text-content-tertiary group-hover:text-brand-orange dark:group-hover:text-brand-orange-text group-hover:translate-x-0.5 transition-subtle shrink-0" />
                </Link>
              ))
            ) : (
              <p className="text-caption text-content-tertiary italic p-3 bg-surface-subtle rounded-card border border-border">
                No sample ticket records linked to this theme in the selected time window.
              </p>
            )}
          </div>
        </div>

        {/* Action Button: Filter Queue by this Theme */}
        <div className="pt-4 border-t border-border">
          <Link
            href={`/?intent=${encodeURIComponent(theme.theme)}`}
            className="w-full min-h-[44px] inline-flex items-center justify-center gap-2 px-4 py-2.5 bg-brand-orange hover:bg-brand-600 text-white rounded-input text-table font-semibold transition-subtle shadow-xs active:scale-[0.99] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2 focus-visible:ring-offset-canvas"
          >
            <span>Filter queue by this theme</span>
            <ExternalLink className="w-4 h-4" />
          </Link>
        </div>
      </div>
    </Drawer>
  );
}
