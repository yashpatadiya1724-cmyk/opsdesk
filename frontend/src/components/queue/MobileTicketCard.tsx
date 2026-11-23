"use client";

import React from "react";
import { useRouter } from "next/navigation";
import {
  Link2,
  Calendar,
  Clock,
  AlertTriangle,
  MoreVertical,
  UserPlus,
  ArrowUpCircle,
  Copy,
  ExternalLink,
} from "lucide-react";
import { TicketSummary } from "@/lib/types";
import {
  SlaBadge,
  SlaRing,
  PriorityMark,
  StatusChip,
  Chip,
  Avatar,
  Popover,
} from "@/components/ui";
import { useUser } from "@/context/UserContext";
import { useToast } from "@/context/ToastContext";
import { assignTicket, escalateTicket } from "@/lib/api";
import { cn, parseUtc } from "@/lib/utils";

export interface MobileTicketCardProps {
  ticket: TicketSummary;
  rank: number;
  onRefresh?: () => void;
  onSelectTicket?: (ticketId: string) => void;
}

export function MobileTicketCard({
  ticket,
  rank,
  onRefresh,
  onSelectTicket,
}: MobileTicketCardProps) {
  const router = useRouter();
  const { currentUser, isStaff } = useUser();
  const { showToast } = useToast();

  const now = Date.now();
  const checkInTime = parseUtc(ticket.check_in_date)?.getTime() ?? 0;
  const checkInDiffMs = checkInTime - now;
  const checkInDiffHours = checkInDiffMs / (3600 * 1000);

  const isRank1Emergency = rank === 1 && checkInDiffHours >= 0 && checkInDiffHours < 4;

  const isClosedOrStopped =
    ticket.status === "Closed" ||
    ticket.status === "Resolved" ||
    ticket.sla.status === "STOPPED";

  const slaBorderColor = {
    NORMAL: "border-l-emerald-500",
    AT_RISK: "border-l-amber-500",
    BREACHED: "border-l-red-600",
    STOPPED: "border-l-slate-300",
  }[ticket.sla.status] || "border-l-slate-300";

  const checkInHoursInt = Math.floor(checkInDiffHours);
  const checkInDays = Math.floor(checkInHoursInt / 24);
  const checkInRemHours = Math.abs(checkInHoursInt % 24);

  let checkInText = "";
  if (checkInDiffMs < 0) {
    checkInText = "Checked in";
  } else if (checkInDays > 0) {
    checkInText = `In ${checkInDays}d ${checkInRemHours}h`;
  } else if (checkInHoursInt > 0) {
    checkInText = `In ${checkInHoursInt}h`;
  } else {
    checkInText = "In < 1h";
  }

  const linkedList: string[] =
    (ticket as unknown as { linked_ticket_ids?: string[] }).linked_ticket_ids || [];
  const linkedCount = linkedList.length;

  const handleAssignToMe = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await assignTicket(ticket.id, currentUser.id, currentUser.id);
      showToast(`Assigned ${ticket.id} to you`, "success");
      onRefresh?.();
    } catch {
      showToast("Failed to assign ticket", "error");
    }
  };

  const handleEscalate = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await escalateTicket(ticket.id, "Operational escalation from mobile card", currentUser.id);
      showToast(`Escalated ${ticket.id}`, "warning");
      onRefresh?.();
    } catch {
      showToast("Failed to escalate ticket", "error");
    }
  };

  const handleCopyTboh = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(ticket.tboh_id);
    showToast(`Copied ${ticket.tboh_id} to clipboard`, "info");
  };

  const handleCardClick = (e?: React.MouseEvent) => {
    if (e && (e.target as HTMLElement).closest('[data-no-card-click]')) {
      return;
    }
    if (onSelectTicket) {
      onSelectTicket(ticket.id);
    } else {
      router.push(`/ticket/${ticket.id}`);
    }
  };

  return (
    <div
      onClick={handleCardClick}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          handleCardClick();
        }
      }}
      tabIndex={0}
      role="link"
      aria-label={`View ticket ${ticket.id} - ${ticket.title}`}
      className={cn(
        "p-4 hover:bg-surface-subtle transition-subtle cursor-pointer flex flex-col gap-2.5 border-l-4 focus:outline-none focus:bg-surface-subtle select-none",
        slaBorderColor,
        isClosedOrStopped && "opacity-60 text-content-tertiary"
      )}
    >
      {/* Top row: ID + TBOH + SLA Badge + "..." Quick Actions Menu */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 min-w-0">
          <span className="font-mono-numbers text-caption font-bold text-content-primary">
            #{rank} {ticket.id}
          </span>
          <span className="font-mono-numbers text-[11px] text-content-tertiary truncate">
            {ticket.tboh_id}
          </span>
          {linkedCount > 0 && (
            <span className="inline-flex items-center gap-0.5 text-[10px] text-brand-700 dark:text-amber-200 bg-brand-50 dark:bg-amber-950/40 border border-brand-200 dark:border-amber-800 px-1 rounded shrink-0">
              <Link2 className="w-2.5 h-2.5 text-brand-600 dark:text-amber-400" aria-hidden="true" />
              <span>{linkedCount}</span>
            </span>
          )}
        </div>

        <div className="flex items-center gap-1.5 shrink-0">
          {isRank1Emergency && (
            <span className="inline-flex items-center gap-0.5 text-[10px] font-semibold text-rose-900 bg-rose-100 border border-rose-300 dark:text-rose-100 dark:bg-rose-950/80 px-1 py-0.2 rounded leading-none shrink-0">
              <AlertTriangle className="w-2.5 h-2.5 text-rose-800 dark:text-rose-200 shrink-0" aria-hidden="true" />
              &lt; 4h
            </span>
          )}
          <SlaRing status={ticket.sla.status} hoursRemaining={ticket.sla.hours_remaining} size={16} />
          <SlaBadge sla={ticket.sla} size="sm" isEscalated={ticket.status === "Escalated"} />

          {/* Mobile "..." Quick Actions Popover Menu */}
          <div data-no-card-click>
            <Popover
              position="bottom-right"
              trigger={
                <button
                  type="button"
                  className="p-1 rounded text-content-tertiary hover:text-content-primary hover:bg-surface-subtle"
                  aria-label="Ticket options"
                >
                  <MoreVertical className="w-4 h-4" />
                </button>
              }
            >
              <div className="flex flex-col gap-1 w-40 text-caption font-sans">
                {isStaff && !ticket.assigned_to && (
                  <button
                    type="button"
                    onClick={handleAssignToMe}
                    className="flex items-center gap-2 px-2.5 py-1.5 rounded hover:bg-surface-subtle text-left text-content-primary transition-colors cursor-pointer"
                  >
                    <UserPlus className="w-3.5 h-3.5 text-brand-600" />
                    <span>Assign to me</span>
                  </button>
                )}
                {isStaff && (
                  <button
                    type="button"
                    onClick={handleEscalate}
                    className="flex items-center gap-2 px-2.5 py-1.5 rounded hover:bg-surface-subtle text-left text-amber-700 transition-colors cursor-pointer"
                  >
                    <ArrowUpCircle className="w-3.5 h-3.5 text-amber-600" />
                    <span>Escalate</span>
                  </button>
                )}
                <button
                  type="button"
                  onClick={handleCopyTboh}
                  className="flex items-center gap-2 px-2.5 py-1.5 rounded hover:bg-surface-subtle text-left text-content-secondary transition-colors cursor-pointer"
                >
                  <Copy className="w-3.5 h-3.5" />
                  <span>Copy TBOH</span>
                </button>
                <button
                  type="button"
                  onClick={() => router.push(`/ticket/${ticket.id}`)}
                  className="flex items-center gap-2 px-2.5 py-1.5 rounded hover:bg-surface-subtle text-left text-brand-700 font-medium transition-colors cursor-pointer border-t border-border mt-0.5 pt-1.5"
                >
                  <ExternalLink className="w-3.5 h-3.5" />
                  <span>Open full page</span>
                </button>
              </div>
            </Popover>
          </div>
        </div>
      </div>

      {/* Middle: Title */}
      <p className="text-table text-content-primary font-medium line-clamp-2">
        {ticket.title}
      </p>

      {/* Chips row */}
      <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
        <PriorityMark priority={ticket.priority} />
        <StatusChip status={ticket.status} />
        {ticket.intent && (
          <Chip size="sm" variant="brand">
            {ticket.intent}
          </Chip>
        )}
      </div>

      {/* Bottom row: Deadlines and Assignee */}
      <div className="flex items-center justify-between text-caption text-content-secondary pt-2 border-t border-border/60">
        <div className="flex items-center gap-2 font-mono-numbers text-[11px]">
          <span className="inline-flex items-center gap-1 font-semibold text-content-primary">
            <Calendar className="w-3 h-3 text-content-tertiary" />
            {checkInText}
          </span>
          {ticket.lcd_date && (
            <span className="inline-flex items-center gap-1 text-content-tertiary">
              <Clock className="w-3 h-3" />
              LCD {parseUtc(ticket.lcd_date)?.toLocaleDateString("en-GB", { day: "numeric", month: "short" })}
            </span>
          )}
        </div>

        <div className="flex items-center gap-1 text-[11px]">
          {ticket.assigned_to ? (
            <div className="flex items-center gap-1">
              <Avatar name={ticket.assigned_to} id={ticket.assigned_to} size="sm" />
              <span className="truncate max-w-[90px]">{ticket.assigned_to}</span>
            </div>
          ) : (
            <span className="text-content-disabled italic">Unassigned</span>
          )}
        </div>
      </div>
    </div>
  );
}
