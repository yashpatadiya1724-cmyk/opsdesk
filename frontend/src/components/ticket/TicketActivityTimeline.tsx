"use client";

import React, { useMemo } from "react";
import { TicketDetail } from "@/lib/types";
import { Tooltip, Chip } from "@/components/ui";
import { formatDate, formatRelativeTime, cn, parseUtc } from "@/lib/utils";
import { Clock } from "lucide-react";

export interface ActivityEvent {
  id: string;
  type:
    | "created"
    | "public_reply"
    | "internal_note"
    | "supplier_thread"
    | "assigned"
    | "escalated"
    | "status"
    | "bug_linked";
  typeName: string;
  actor: string;
  timestamp: string;
  summary: string;
  detail?: string;
  dotColor: string; // Tailwind bg class
}

export interface TicketActivityTimelineProps {
  ticket: TicketDetail;
}

export function TicketActivityTimeline({ ticket }: TicketActivityTimelineProps) {
  // Synthesize and sort chronologically (most recent first)
  const events = useMemo((): ActivityEvent[] => {
    const list: ActivityEvent[] = [];

    // 1. Ticket Creation
    list.push({
      id: "ev-create",
      type: "created",
      typeName: "Ticket Created",
      actor: ticket.agency_id || "Agency",
      timestamp: ticket.created_at,
      summary: `Ticket created for reservation ${ticket.tboh_id}`,
      detail: `Initial priority set to ${ticket.priority} with status ${ticket.status}. Check-in scheduled for ${formatDate(ticket.check_in_date)}.`,
      dotColor: "bg-blue-500",
    });

    // 2. Messages
    (ticket.messages || []).forEach((msg) => {
      const isInternal = msg.message_type === "InternalNote";
      const snippet = msg.content.length > 80 ? `${msg.content.slice(0, 80)}…` : msg.content;
      list.push({
        id: `ev-msg-${msg.id}`,
        type: isInternal ? "internal_note" : "public_reply",
        typeName: isInternal ? "Internal Note Logged" : "Public Reply Dispatched",
        actor: msg.sender_name || (isInternal ? "Staff Member" : "Agency Agent"),
        timestamp: msg.created_at,
        summary: isInternal
          ? `Recorded internal staff note: "${snippet}"`
          : `Dispatched public reply to agency: "${snippet}"`,
        detail: msg.content,
        dotColor: isInternal ? "bg-amber-500" : "bg-teal-600",
      });
    });

    // 3. Supplier Threads
    (ticket.side_conversations || []).forEach((sc) => {
      list.push({
        id: `ev-sc-${sc.id}`,
        type: "supplier_thread",
        typeName: "Supplier Thread Initiated",
        actor: sc.created_by || "Operations Agent",
        timestamp: sc.created_at,
        summary: `Initiated supplier thread with ${sc.supplier_name}`,
        detail: `Subject: "${sc.subject}" | Recipients: ${sc.recipients.join(", ")}`,
        dotColor: "bg-cyan-500",
      });
    });

    // 4. Assignment
    if (ticket.assigned_to) {
      list.push({
        id: "ev-assign",
        type: "assigned",
        typeName: "Ownership Assigned",
        actor: ticket.assigned_to,
        timestamp: ticket.updated_at || ticket.created_at,
        summary: `Case claimed and assigned to ${ticket.assigned_to}`,
        detail: "Ticket routing verified and assigned to specialist queue.",
        dotColor: "bg-emerald-500",
      });
    }

    // 5. Escalation
    if (ticket.status === "Escalated") {
      list.push({
        id: "ev-escalate",
        type: "escalated",
        typeName: "Escalated to Manager",
        actor: "Operations Escalation Lead",
        timestamp: ticket.updated_at || ticket.created_at,
        summary: "Case escalated to Global Escalation Manager queue (Vikram Joshi)",
        detail: "Urgent priority assigned; expedited resolution protocols activated.",
        dotColor: "bg-violet-600",
      });
    }

    // 6. Bug Link
    if (ticket.suggested_bug_link) {
      list.push({
        id: "ev-bug",
        type: "bug_linked",
        typeName: "Product Defect Associated",
        actor: "Product Engineering",
        timestamp: ticket.updated_at || ticket.created_at,
        summary: `Associated product defect link: ${ticket.suggested_bug_link}`,
        detail: `Referenced defect link: ${ticket.suggested_bug_link}`,
        dotColor: "bg-rose-500",
      });
    }

    // Sort descending by time
    return list.sort((a, b) => (parseUtc(b.timestamp)?.getTime() ?? 0) - (parseUtc(a.timestamp)?.getTime() ?? 0));
  }, [ticket]);

  // Group events by day label
  const groupedEvents = useMemo(() => {
    const groups: { [key: string]: ActivityEvent[] } = {};
    const now = new Date();

    events.forEach((ev) => {
      const d = parseUtc(ev.timestamp) ?? new Date(ev.timestamp);
      let dayLabel = "Earlier";

      if (!isNaN(d.getTime())) {
        const isToday =
          d.getDate() === now.getDate() &&
          d.getMonth() === now.getMonth() &&
          d.getFullYear() === now.getFullYear();

        const yesterday = new Date(now);
        yesterday.setDate(yesterday.getDate() - 1);
        const isYesterday =
          d.getDate() === yesterday.getDate() &&
          d.getMonth() === yesterday.getMonth() &&
          d.getFullYear() === yesterday.getFullYear();

        if (isToday) {
          dayLabel = "Today";
        } else if (isYesterday) {
          dayLabel = "Yesterday";
        } else {
          dayLabel = d.toLocaleDateString("en-US", {
            month: "short",
            day: "numeric",
            year: "numeric",
          });
        }
      }

      if (!groups[dayLabel]) groups[dayLabel] = [];
      groups[dayLabel].push(ev);
    });

    return groups;
  }, [events]);

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2 pb-2 border-b border-border text-caption font-semibold text-content-primary">
        <Clock className="w-4 h-4 text-brand-600" />
        <span>Chronological Case Audit Log</span>
      </div>

      <div className="space-y-6">
        {Object.entries(groupedEvents).map(([dayLabel, dayEvents]) => (
          <div key={dayLabel} className="space-y-3">
            {/* Day Header Badge */}
            <div className="sticky top-0 z-10">
              <span className="text-[11px] font-semibold text-content-tertiary uppercase tracking-wider bg-surface px-2 py-0.5 rounded border border-border">
                {dayLabel}
              </span>
            </div>

            {/* Vertical Line with 10px Coloured Dots */}
            <div className="relative pl-7 space-y-5 border-l-2 border-border ml-3">
              {dayEvents.map((ev) => (
                <div key={ev.id} className="relative group">
                  {/* 10px Coloured Dot (grows on hover) */}
                  <div
                    className={cn(
                      "absolute -left-[35px] top-1.5 w-2.5 h-2.5 rounded-full ring-4 ring-surface transition-transform duration-200 group-hover:scale-150 cursor-pointer shadow-xs",
                      ev.dotColor
                    )}
                  />

                  {/* Event Summary & Interactive Hover Detail Card */}
                  <div className="text-table">
                    <div className="flex flex-wrap items-center gap-2 text-caption">
                      <span className="font-semibold text-content-primary">
                        {ev.actor}
                      </span>
                      <Chip size="sm" variant="subtle" className="text-[10px] h-[18px] px-1.5">
                        {ev.typeName}
                      </Chip>
                      <Tooltip content={formatDate(ev.timestamp)}>
                        <span className="text-content-tertiary text-[11px] cursor-default ml-auto">
                          {formatRelativeTime(ev.timestamp)}
                        </span>
                      </Tooltip>
                    </div>

                    <p className="text-content-secondary mt-1 text-caption leading-relaxed">
                      {ev.summary}
                    </p>

                    {/* Detail Card revealed on hover */}
                    {ev.detail && ev.detail !== ev.summary && (
                      <div className="hidden group-hover:block mt-2 p-2.5 rounded-input bg-surface-subtle border border-border text-[12px] text-content-primary shadow-xs animate-in fade-in duration-150">
                        <p className="font-mono-numbers whitespace-pre-wrap leading-snug">
                          {ev.detail}
                        </p>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
