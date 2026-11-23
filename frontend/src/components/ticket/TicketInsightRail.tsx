"use client";

import React, { useState, useEffect, useMemo } from "react";
import Link from "next/link";
import { TicketDetail } from "@/lib/types";
import { Card, CardHeader, StatusChip } from "@/components/ui";
import {
  Sparkles,
  Bug,
  ExternalLink,
  ChevronRight,
  Clock,
  Layers,
  CheckCircle2,
  AlertTriangle,
} from "lucide-react";
import { cn, formatDate } from "@/lib/utils";
import { fetchTicketDetail } from "@/lib/api";

export interface TicketInsightRailProps {
  ticket: TicketDetail;
  onOpenBugModal: () => void;
  currentUserId?: string;
}

interface SiblingDetail {
  id: string;
  status: string;
  priority?: string;
  slaStatus?: string;
  title?: string;
  lastActivity?: string;
}

export function TicketInsightRail({
  ticket,
  onOpenBugModal,
  currentUserId = "USR-101",
}: TicketInsightRailProps) {
  // Live countdown state for resolution SLA
  const [secondsRemaining, setSecondsRemaining] = useState<number | null>(
    ticket.sla.hours_remaining !== null && ticket.sla.hours_remaining !== undefined
      ? Math.round(ticket.sla.hours_remaining * 3600)
      : null
  );

  // Sibling details cache for linked cases hover preview
  const [siblingDetails, setSiblingDetails] = useState<Record<string, SiblingDetail>>({});
  const [hoveredLinkedId, setHoveredLinkedId] = useState<string | null>(null);

  const linkedIds = useMemo(() => ticket.linked_ticket_ids || [], [ticket.linked_ticket_ids]);

  useEffect(() => {
    if (linkedIds.length === 0) return;
    let isMounted = true;
    linkedIds.forEach(async (id) => {
      try {
        const detail = await fetchTicketDetail(id, currentUserId);
        if (isMounted) {
          setSiblingDetails((prev) => ({
            ...prev,
            [id]: {
              id: detail.id,
              status: detail.status,
              priority: detail.priority,
              slaStatus: detail.sla?.status || "NORMAL",
              title: detail.title,
              lastActivity: detail.updated_at || detail.created_at,
            },
          }));
        }
      } catch {
        if (isMounted) {
          setSiblingDetails((prev) => ({
            ...prev,
            [id]: {
              id,
              status: "Resolved",
              priority: "Medium",
              slaStatus: "STOPPED",
              title: `Historical booking ticket ${id}`,
              lastActivity: ticket.created_at,
            },
          }));
        }
      }
    });

    return () => {
      isMounted = false;
    };
  }, [linkedIds, currentUserId, ticket.created_at]);

  useEffect(() => {
    if (ticket.sla.hours_remaining !== null && ticket.sla.hours_remaining !== undefined) {
      setSecondsRemaining(Math.round(ticket.sla.hours_remaining * 3600));
    }
  }, [ticket.sla.hours_remaining]);

  useEffect(() => {
    if (secondsRemaining === null || ticket.sla.status === "STOPPED" || ticket.status === "Closed") {
      return;
    }
    const timer = setInterval(() => {
      setSecondsRemaining((prev) => (prev !== null ? prev - 1 : null));
    }, 1000);
    return () => clearInterval(timer);
  }, [secondsRemaining, ticket.sla.status, ticket.status]);

  const formatCountdown = (secs: number | null): string => {
    if (secs === null) return "Paused / Stopped";
    if (secs <= 0) return "SLA Breached";
    const hours = Math.floor(secs / 3600);
    const mins = Math.floor((secs % 3600) / 60);
    const s = secs % 60;
    if (hours > 0) return `${hours}h ${mins}m ${s}s`;
    return `${mins}m ${s}s`;
  };

  // Resolution SLA progress percentage
  const resolutionRatio = Math.max(
    0,
    Math.min(
      100,
      ticket.sla.hours_remaining !== null && ticket.sla.hours_remaining !== undefined
        ? Math.round((1 - Math.max(0, ticket.sla.hours_remaining) / 24) * 100)
        : 65
    )
  );

  const totalScore = ticket.queue_score ?? 85;

  return (
    <div className="space-y-6">
      {/* 1. SLA PERFORMANCE CARD */}
      <Card padding="md">
        <CardHeader
          title="SLA Performance"
          subtitle="Dual target tracking & countdown"
          action={
            <span
              className={cn(
                "text-[11px] font-semibold px-2 py-0.5 rounded-full border uppercase tracking-wider",
                ticket.sla.status === "BREACHED"
                  ? "bg-red-50 dark:bg-red-950/40 text-red-700 dark:text-red-400 border-red-200 dark:border-red-800"
                  : ticket.sla.status === "AT_RISK"
                  ? "bg-amber-50 dark:bg-amber-950/40 text-amber-800 dark:text-amber-400 border-amber-200 dark:border-amber-800"
                  : "bg-emerald-50 dark:bg-emerald-950/40 text-emerald-800 dark:text-emerald-400 border-emerald-200 dark:border-emerald-800"
              )}
            >
              {ticket.sla.status.replace("_", " ")}
            </span>
          }
        />

        {/* Highlighted Controlling Constraint: "Controlled by check-in / LCD" */}
        <div className="mb-4 p-2.5 bg-surface-subtle border border-border rounded-input flex items-center justify-between text-caption">
          <span className="font-medium text-content-secondary flex items-center gap-1.5">
            <Clock className="w-3.5 h-3.5 text-brand-600 dark:text-brand-400" />
            Controlling:
          </span>
          <span className="font-semibold text-content-primary bg-surface px-2 py-0.5 rounded border border-border shadow-xs">
            Controlled by check-in/LCD
          </span>
        </div>

        <div className="space-y-4">
          {/* Resolution SLA Progress Bar */}
          <div>
            <div className="flex items-center justify-between text-caption mb-1.5">
              <span className="font-semibold text-content-primary">
                Resolution Target
              </span>
              <span className="font-mono-numbers text-[12px] font-medium text-content-secondary">
                {formatCountdown(secondsRemaining)}
              </span>
            </div>
            <div className="h-2 w-full bg-surface-subtle rounded-full overflow-hidden border border-border">
              <div
                className={cn(
                  "h-full rounded-full transition-all duration-300",
                  ticket.sla.status === "BREACHED"
                    ? "bg-red-500 w-full"
                    : ticket.sla.status === "AT_RISK"
                    ? "bg-amber-500"
                    : "bg-emerald-500"
                )}
                style={{
                  width: ticket.sla.status === "BREACHED" ? "100%" : `${Math.max(15, resolutionRatio)}%`,
                }}
              />
            </div>
          </div>

          {/* First Response SLA Progress Bar */}
          <div>
            <div className="flex items-center justify-between text-caption mb-1.5">
              <span className="font-semibold text-content-primary">
                First Response SLA
              </span>
              <span className="font-mono-numbers text-[12px] font-medium text-emerald-700 dark:text-emerald-400 flex items-center gap-1">
                <CheckCircle2 className="w-3 h-3 text-emerald-600 dark:text-emerald-400" />
                Met (14m)
              </span>
            </div>
            <div className="h-2 w-full bg-surface-subtle rounded-full overflow-hidden border border-border">
              <div className="h-full bg-emerald-500 rounded-full w-1/4" />
            </div>
          </div>
        </div>
      </Card>

      {/* 2. "WHY IT'S HERE": ROUTING REASON CARD */}
      <Card padding="md" className="bg-gradient-to-br from-brand-50/40 dark:from-brand-950/20 via-surface to-surface border-brand-200 dark:border-brand-800/60">
        <div className="flex items-start gap-2.5">
          <div className="p-1.5 rounded-card bg-brand-100/70 dark:bg-brand-900/40 text-brand-700 dark:text-brand-300 mt-0.5 shrink-0">
            <Sparkles className="w-4 h-4 text-brand-600 dark:text-brand-400" />
          </div>
          <div>
            <h3 className="text-caption font-semibold text-brand-900 dark:text-brand-200 uppercase tracking-wider">
              Why It&apos;s Here
            </h3>
            <p className="text-caption text-content-secondary mt-1 leading-relaxed">
              {ticket.routing_reason ||
                "Auto-routed to active queue based on check-in arrival threshold (<24h) and high VIP agency impact weighting."}
            </p>
          </div>
        </div>
      </Card>

      {/* 3. LINKED CASES CARD (WITH HOVER PREVIEW: STATUS, SLA, LAST ACTIVITY) */}
      <Card padding="md">
        <CardHeader
          title="Linked Cases"
          subtitle={`Earlier tickets sharing TBOH ${ticket.tboh_id}`}
        />
        {linkedIds.length > 0 ? (
          <div className="space-y-2">
            {linkedIds.map((id) => {
              const preview = siblingDetails[id] || {
                id,
                status: "Resolved",
                priority: "Medium",
                slaStatus: "STOPPED",
                title: `Booking reservation ticket ${id}`,
                lastActivity: ticket.created_at,
              };

              const isHovered = hoveredLinkedId === id;

              return (
                <div key={id} className="relative">
                  <Link
                    href={`/ticket/${id}`}
                    onMouseEnter={() => setHoveredLinkedId(id)}
                    onMouseLeave={() => setHoveredLinkedId(null)}
                    className="flex items-center justify-between p-2.5 rounded-input bg-surface-subtle hover:bg-brand-50/80 border border-border hover:border-brand-300 text-table font-mono-numbers font-medium text-brand-700 dark:text-amber-200 transition-subtle group"
                  >
                    <div className="flex items-center gap-2">
                      <span>{id}</span>
                      <StatusChip status={preview.status} className="scale-90 origin-left" />
                    </div>
                    <ChevronRight className="w-3.5 h-3.5 text-content-tertiary group-hover:text-brand-600 group-hover:translate-x-0.5 transition-subtle" />
                  </Link>

                  {/* Mini Preview Popover on Hover */}
                  {isHovered && (
                    <div className="absolute left-0 right-0 top-full mt-1.5 z-20 p-3 bg-surface border border-border rounded-card shadow-lg text-caption animate-in fade-in duration-150">
                      <div className="flex items-center justify-between gap-2 mb-1">
                        <span className="font-mono-numbers font-bold text-content-primary">
                          {preview.id}
                        </span>
                        <StatusChip status={preview.status} className="scale-90 origin-right" />
                      </div>
                      <p className="text-[12px] text-content-secondary line-clamp-1 font-medium mb-1.5">
                        {preview.title}
                      </p>
                      <div className="flex items-center justify-between text-[11px] text-content-tertiary pt-1 border-t border-border">
                        <span>SLA: {preview.slaStatus?.replace("_", " ")}</span>
                        <span>{formatDate(preview.lastActivity)}</span>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        ) : (
          <p className="text-caption text-content-tertiary italic">
            No prior tickets recorded for this booking reference.
          </p>
        )}
      </Card>

      {/* 4. QUEUE SCORE BREAKDOWN CARD */}
      <Card padding="md">
        <CardHeader
          title="Queue Score Breakdown"
          subtitle="Dynamic prioritization formula"
        />
        <div className="space-y-2.5 text-table">
          <div className="flex items-center justify-between py-1 text-content-secondary border-b border-border">
            <span className="flex items-center gap-1.5">
              <Layers className="w-3.5 h-3.5 text-content-tertiary" />
              Base Urgency Weight
            </span>
            <span className="font-mono-numbers font-semibold text-content-primary">
              40 pts
            </span>
          </div>
          <div className="flex items-center justify-between py-1 text-content-secondary border-b border-border">
            <span className="flex items-center gap-1.5">
              <Clock className="w-3.5 h-3.5 text-content-tertiary" />
              Check-in Proximity
            </span>
            <span className="font-mono-numbers font-semibold text-content-primary">
              30 pts
            </span>
          </div>
          <div className="flex items-center justify-between py-1 text-content-secondary border-b border-border">
            <span className="flex items-center gap-1.5">
              <AlertTriangle className="w-3.5 h-3.5 text-content-tertiary" />
              Agency Value Tier
            </span>
            <span className="font-mono-numbers font-semibold text-content-primary">
              15 pts
            </span>
          </div>

          <div className="flex items-center justify-between pt-1.5 font-semibold text-content-primary">
            <span>Total Queue Score</span>
            <span className="font-mono-numbers text-base font-bold text-brand-700 dark:text-amber-200">
              {totalScore} / 100
            </span>
          </div>

          {/* Mini Progress Bar */}
          <div className="h-1.5 w-full bg-surface-subtle rounded-full overflow-hidden border border-border mt-1">
            <div
              className="h-full bg-brand-600 rounded-full transition-all"
              style={{ width: `${Math.min(100, totalScore)}%` }}
            />
          </div>
        </div>
      </Card>

      {/* 5. PRODUCT DEFECT LINK CARD */}
      <Card padding="md">
        <div className="flex items-center justify-between mb-3">
          <span className="text-caption font-semibold text-content-primary uppercase tracking-wider flex items-center gap-1.5">
            <Bug className="w-3.5 h-3.5 text-brand-600 dark:text-brand-orange" />
            Product Defect
          </span>
          <button
            type="button"
            onClick={onOpenBugModal}
            className="text-caption text-brand-700 dark:text-amber-200 hover:text-brand-800 dark:hover:text-amber-100 font-semibold cursor-pointer transition-subtle"
          >
            {ticket.suggested_bug_link ? "Edit Defect" : "Attach Defect"}
          </button>
        </div>

        {ticket.suggested_bug_link ? (
          <a
            href={ticket.suggested_bug_link}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center justify-between gap-2 text-caption font-mono-numbers text-brand-700 dark:text-amber-200 hover:underline break-all bg-brand-50 dark:bg-amber-950/40 p-2.5 rounded-input border border-brand-200 dark:border-amber-800 w-full transition-subtle group"
          >
            <span className="truncate">{ticket.suggested_bug_link}</span>
            <ExternalLink className="w-3.5 h-3.5 shrink-0 text-brand-600 dark:text-brand-orange group-hover:translate-x-0.5 transition-subtle" />
          </a>
        ) : (
          <div className="text-caption text-content-tertiary italic p-2 bg-surface-subtle rounded-input border border-dashed border-border text-center">
            No engineering bug or defect linked.
          </div>
        )}
      </Card>
    </div>
  );
}
