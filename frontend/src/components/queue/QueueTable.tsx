"use client";

import React from "react";
import { useRouter } from "next/navigation";
import {
  Link2,
  HelpCircle,
  AlertTriangle,
  UserPlus,
  ArrowUpCircle,
  Copy,
  ExternalLink,
  Tag,
} from "lucide-react";
import { TicketSummary } from "@/lib/types";
import {
  SlaBadge,
  SlaRing,
  PriorityMark,
  StatusChip,
  Avatar,
  Tooltip,
  FlightPathTimeline,
  TableRowSkeleton,
} from "@/components/ui";
import { useUser } from "@/context/UserContext";
import { useToast } from "@/context/ToastContext";
import { assignTicket, escalateTicket } from "@/lib/api";
import { cn, parseUtc } from "@/lib/utils";

export interface QueueTableProps {
  tickets: TicketSummary[];
  loading: boolean;
  page: number;
  pageSize: number;
  isStaff: boolean;
  selectedTicketId?: string | null;
  onSelectTicket?: (ticketId: string) => void;
  onIntentFilter?: (intent: string) => void;
  onPriorityFilter?: (priority: string) => void;
  onRefresh?: () => void;
}

export function QueueTable({
  tickets,
  loading,
  page,
  pageSize,
  isStaff,
  selectedTicketId,
  onSelectTicket,
  onIntentFilter,
  onPriorityFilter,
  onRefresh,
}: QueueTableProps) {
  const router = useRouter();
  const { currentUser } = useUser();
  const { showToast } = useToast();

  // Quick Action Handlers
  const handleAssignToMe = async (ticketId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await assignTicket(ticketId, currentUser.id, currentUser.id);
      showToast(`Assigned ticket ${ticketId} to you`, "success");
      onRefresh?.();
    } catch {
      showToast("Failed to assign ticket", "error");
    }
  };

  const handleEscalate = async (ticketId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await escalateTicket(ticketId, "Operational priority escalation from queue", currentUser.id);
      showToast(`Escalated ticket ${ticketId}`, "warning");
      onRefresh?.();
    } catch {
      showToast("Failed to escalate ticket", "error");
    }
  };

  const handleCopyTboh = (tbohId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(tbohId);
    showToast(`Copied ${tbohId} to clipboard`, "info");
  };

  const handleOpenTicket = (ticketId: string, e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    router.push(`/ticket/${ticketId}`);
  };

  // Group tickets into 4 time buckets:
  // "Act now (< 4h)", "Today", "This week", "Later"
  const buckets = React.useMemo(() => {
    const now = Date.now();
    const actNow: { ticket: TicketSummary; rank: number }[] = [];
    const today: { ticket: TicketSummary; rank: number }[] = [];
    const thisWeek: { ticket: TicketSummary; rank: number }[] = [];
    const later: { ticket: TicketSummary; rank: number }[] = [];

    tickets.forEach((t, idx) => {
      const rank = page * pageSize + idx + 1;
      const checkInTime = parseUtc(t.check_in_date)?.getTime() ?? 0;
      const diffHours = (checkInTime - now) / (3600 * 1000);

      if (diffHours >= 0 && diffHours < 4) {
        actNow.push({ ticket: t, rank });
      } else if (diffHours >= 4 && diffHours < 24) {
        today.push({ ticket: t, rank });
      } else if (diffHours >= 24 && diffHours < 168) {
        thisWeek.push({ ticket: t, rank });
      } else {
        later.push({ ticket: t, rank });
      }
    });

    return [
      { name: "Act now (< 4h)", color: "text-rose-600 bg-rose-50 border-rose-200", items: actNow },
      { name: "Today", color: "text-amber-700 bg-amber-50 border-amber-200", items: today },
      { name: "This week", color: "text-brand-700 bg-brand-50 border-brand-200", items: thisWeek },
      { name: "Later", color: "text-content-secondary bg-surface-subtle border-border", items: later },
    ].filter((b) => b.items.length > 0);
  }, [tickets, page, pageSize]);

  // Loading skeleton state
  if (loading && tickets.length === 0) {
    return (
      <div className="w-full overflow-hidden">
        <table className="w-full text-left border-collapse table-fixed">
          <thead>
            <tr className="border-b border-border bg-surface-subtle text-micro-label uppercase text-content-tertiary h-10 select-none">
              <th className="px-3 w-9 text-center font-medium">#</th>
              <th className="px-3 w-[130px] font-medium">SLA Status</th>
              <th className="px-3 font-medium">Ticket</th>
              <th className="px-3 w-[90px] hidden lg:table-cell font-medium">Agency</th>
              <th className="px-3 w-[110px] hidden md:table-cell font-medium">Intent</th>
              <th className="px-3 w-[80px] font-medium">Priority</th>
              <th className="px-3 w-[76px] font-medium">Status</th>
              <th className="px-3 w-[175px] font-medium">Dates</th>
              <th className="px-3 w-[110px] hidden min-[1200px]:table-cell font-medium">Assignee</th>
              {isStaff && <th className="px-3 w-[54px] text-right hidden min-[1280px]:table-cell font-medium">Score</th>}
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: 8 }).map((_, i) => (
              <TableRowSkeleton key={i} columns={isStaff ? 10 : 9} />
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  const totalCols = isStaff ? 10 : 9;

  // Short intent formatter
  const formatShortIntent = (intent: string | null) => {
    if (!intent) return "General";
    if (intent.includes("Refund")) return "Refund";
    if (intent.includes("Cancellation")) return "Cancel";
    if (intent.includes("Amendment")) return "Amend";
    if (intent.includes("Bedding") || intent.includes("Room")) return "Room";
    if (intent.includes("Voucher")) return "Voucher";
    if (intent.includes("Emergency")) return "Emergency";
    return intent.slice(0, 10);
  };

  return (
    <div className="w-full overflow-x-auto">
      <table className="w-full text-left border-collapse table-fixed select-none">
        {/* Table Header */}
        <thead>
          <tr className="border-b border-border bg-surface-subtle text-micro-label uppercase text-content-tertiary h-10 select-none">
            <th className="px-3 w-10 text-center font-medium bg-surface-subtle">#</th>
            <th className="px-3 w-[145px] font-medium bg-surface-subtle">SLA Status</th>
            <th className="px-3 min-w-[240px] font-medium bg-surface-subtle">Ticket</th>
            <th className="px-3 w-[96px] hidden lg:table-cell font-medium bg-surface-subtle">Agency</th>
            <th className="px-3 w-[95px] hidden md:table-cell font-medium bg-surface-subtle">Intent</th>
            <th className="px-3 w-[75px] font-medium bg-surface-subtle">Priority</th>
            <th className="px-3 w-[75px] font-medium bg-surface-subtle">Status</th>
            <th className="px-3 w-[195px] max-w-[195px] font-medium bg-surface-subtle">Dates</th>
            <th className="px-3 w-[130px] hidden min-[1200px]:table-cell font-medium bg-surface-subtle">Assignee</th>
            {isStaff && (
              <th className="px-3 w-[60px] text-right hidden min-[1280px]:table-cell font-medium bg-surface-subtle">
                Score
              </th>
            )}
          </tr>
        </thead>

        {/* Grouped Table Body */}
        <tbody>
          {buckets.map((bucket) => (
            <React.Fragment key={bucket.name}>
              {/* Time-Bucket Group Header */}
              <tr className="border-y border-border bg-surface-subtle h-8 text-micro-label uppercase font-bold tracking-wider">
                <td colSpan={totalCols} className="px-3 py-1.5 bg-surface-subtle">
                  <div className="flex items-center gap-2">
                    <span
                      className={cn(
                        "px-1.5 py-0.5 rounded text-[10px] font-semibold border",
                        bucket.color
                      )}
                    >
                      {bucket.name}
                    </span>
                    <span className="text-content-tertiary font-mono-numbers text-[11px] font-normal">
                      ({bucket.items.length} {bucket.items.length === 1 ? "case" : "cases"})
                    </span>
                  </div>
                </td>
              </tr>

              {/* Bucket Rows */}
              {bucket.items.map(({ ticket: t, rank }) => {
                const now = Date.now();
                const checkInTime = parseUtc(t.check_in_date)?.getTime() ?? 0;
                const checkInDiffMs = checkInTime - now;
                const checkInDiffHours = checkInDiffMs / (3600 * 1000);

                // Rank #1 emergency row flag: check-in < 4h
                const isRank1Emergency =
                  rank === 1 &&
                  checkInDiffHours >= 0 &&
                  checkInDiffHours < 4;

                // Closed or Resolved row 60% emphasis
                const isClosedOrResolved =
                  t.status === "Closed" ||
                  t.status === "Resolved" ||
                  t.sla.status === "STOPPED";

                // SLA border color (4px normal, 6px on hover)
                const slaBorderColor = {
                  NORMAL: "border-l-emerald-500",
                  AT_RISK: "border-l-amber-500",
                  BREACHED: "border-l-red-600",
                  STOPPED: "border-l-slate-300",
                }[t.sla.status] || "border-l-slate-300";

                // Date calculations: "Check-in in 2d 4h / LCD 3 Dec"
                const checkInHoursInt = Math.floor(checkInDiffHours);
                const checkInDays = Math.floor(checkInHoursInt / 24);
                const checkInRemHours = Math.abs(checkInHoursInt % 24);

                let checkInText = "";
                if (checkInDiffMs < 0) {
                  checkInText = "Checked in";
                } else if (checkInDays > 0) {
                  checkInText = `Check-in in ${checkInDays}d ${checkInRemHours}h`;
                } else if (checkInHoursInt > 0) {
                  checkInText = `Check-in in ${checkInHoursInt}h`;
                } else {
                  checkInText = "Check-in in < 1h";
                }

                const lcdFormatted = t.lcd_date
                  ? `LCD ${parseUtc(t.lcd_date)?.toLocaleDateString("en-GB", {
                      day: "numeric",
                      month: "short",
                    })}`
                  : null;

                // Controlling deadline logic
                const isCheckinControlling =
                  t.intent === "Emergency Check-in Assist" ||
                  !t.lcd_date ||
                  (checkInDiffHours < 24 && checkInDiffHours >= 0);

                // Linked cases peek
                const linkedList: string[] =
                  (t as unknown as { linked_ticket_ids?: string[] }).linked_ticket_ids || [];
                const linkedCount = linkedList.length;

                const isSelected = selectedTicketId === t.id;

                return (
                  <tr
                    key={t.id}
                    onClick={() => {
                      if (onSelectTicket) {
                        onSelectTicket(t.id);
                      } else {
                        handleOpenTicket(t.id);
                      }
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        handleOpenTicket(t.id);
                      } else if (e.key === " " && onSelectTicket) {
                        e.preventDefault();
                        onSelectTicket(t.id);
                      } else if (e.key === "ArrowDown" || e.key === "j") {
                        e.preventDefault();
                        const nextRow = e.currentTarget.nextElementSibling as HTMLElement | null;
                        if (nextRow) nextRow.focus();
                      } else if (e.key === "ArrowUp" || e.key === "k") {
                        e.preventDefault();
                        const prevRow = e.currentTarget.previousElementSibling as HTMLElement | null;
                        if (prevRow) prevRow.focus();
                      }
                    }}
                    tabIndex={0}
                    role="link"
                    aria-label={`Case ${t.id} - ${t.title}`}
                    className={cn(
                      "h-[56px] transition-all duration-120 cursor-pointer border-l-4 group relative focus:outline-none focus:ring-2 focus:ring-[#115E59]",
                      isSelected
                        ? "bg-[#FBEFE6] border-l-[#D9733A]"
                        : "hover:bg-[#FBEFE6] hover:border-l-[#D9733A]",
                      !isSelected && slaBorderColor,
                      isClosedOrResolved && "opacity-60 text-content-tertiary"
                    )}
                  >
                    {/* 1. Gutter Rank # */}
                    <td className="px-3 text-center text-caption font-mono-numbers text-content-tertiary">
                      <div className="flex items-center justify-center gap-1">
                        <span>{rank}</span>
                        {/* 400ms hover shows "Why here?" popover with routing_reason (staff only) */}
                        {isStaff && t.routing_reason && (
                          <Tooltip
                            delayMs={400}
                            position="right"
                            content={
                              <div className="max-w-xs text-left p-1 whitespace-normal font-sans">
                                <span className="font-semibold text-departure-amber block text-[11px] mb-0.5">
                                  Why here?
                                </span>
                                <span className="text-[11px] text-white leading-tight">
                                  {t.routing_reason}
                                </span>
                              </div>
                            }
                          >
                            <span
                              className="opacity-0 group-hover:opacity-100 group-focus:opacity-100 transition-opacity text-brand-600 hover:text-brand-700 cursor-help"
                              onClick={(e) => e.stopPropagation()}
                              title="Routing reason"
                            >
                              <HelpCircle className="w-3 h-3" />
                            </span>
                          </Tooltip>
                        )}
                      </div>
                    </td>

                    {/* 2. SLA Status (SlaRing + SlaBadge) */}
                    <td className="px-3 w-[145px]">
                      <div className="flex items-center gap-1.5 whitespace-nowrap overflow-hidden">
                        <SlaRing
                          status={t.sla.status}
                          hoursRemaining={t.sla.hours_remaining}
                          size={16}
                          showTooltip={false}
                        />
                        <SlaBadge
                          sla={t.sla}
                          size="sm"
                          showRing={false}
                          isEscalated={t.status === "Escalated"}
                          className="shrink-0"
                        />
                        {isRank1Emergency && (
                          <span className="inline-flex items-center gap-0.5 text-[9px] font-semibold text-rose-700 bg-rose-50 border border-rose-200 px-1 py-0.2 rounded leading-none shrink-0 animate-pulse">
                            <AlertTriangle className="w-2.5 h-2.5 text-rose-600 shrink-0" />
                            &lt; 4h
                          </span>
                        )}
                      </div>
                    </td>

                    {/* 3. Ticket: Mono ID, title, TBOH */}
                    <td className="px-3 min-w-0">
                      <div className="flex flex-col justify-center min-w-0">
                        <div className="flex items-center gap-1.5 min-w-0">
                          <span className="font-mono-numbers text-[13px] font-bold text-content-primary group-hover:text-brand-600 transition-colors shrink-0">
                            {t.id}
                          </span>
                          <span className="font-mono-numbers text-[11px] text-content-tertiary truncate">
                            {t.tboh_id}
                          </span>
                          {/* Linked cases chain icon with hover peek */}
                          {linkedCount > 0 && (
                            <Tooltip
                              delayMs={200}
                              position="top"
                              content={
                                <div className="text-left text-[11px] p-1 flex flex-col gap-1 max-w-xs">
                                  <span className="font-semibold text-departure-amber block">
                                    {linkedCount} Sibling {linkedCount === 1 ? "Case" : "Cases"}:
                                  </span>
                                  <div className="flex flex-col gap-0.5 font-mono-numbers text-white">
                                    {linkedList.map((siblingId) => (
                                      <div key={siblingId} className="flex items-center gap-1.5">
                                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 shrink-0" />
                                        <span>{siblingId}</span>
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              }
                            >
                              <span
                                className="inline-flex items-center gap-0.5 text-[10px] text-brand-700 font-mono-numbers bg-brand-50 border border-brand-200 px-1 rounded shrink-0 cursor-pointer"
                                onClick={(e) => e.stopPropagation()}
                              >
                                <Link2 className="w-2.5 h-2.5 text-brand-600" />
                                <span>{linkedCount}</span>
                              </span>
                            </Tooltip>
                          )}
                        </div>
                        <span
                          className="text-table text-content-secondary truncate block font-normal"
                          title={t.title}
                        >
                          {t.title}
                        </span>
                      </div>
                    </td>

                    {/* 4. Agency (Avatar + Code) */}
                    <td className="px-3 hidden lg:table-cell">
                      <div className="flex items-center gap-1.5 min-w-0">
                        <Avatar name={t.agency_id} id={t.agency_id} size="sm" />
                        <span className="text-table font-medium text-content-secondary truncate">
                          {t.agency_id}
                        </span>
                      </div>
                    </td>

                    {/* 5. Intent (Icon + Short Label, Tooltip full name, Click = filter) */}
                    <td className="px-3 hidden md:table-cell">
                      <Tooltip delayMs={300} position="top" content={t.intent || "General Operations"}>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            if (t.intent && onIntentFilter) {
                              onIntentFilter(t.intent);
                            }
                          }}
                          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-chip text-[11px] font-medium bg-brand-50 text-brand-700 hover:bg-brand-100 hover:text-brand-800 transition-colors border border-brand-200/60 truncate max-w-[100px] cursor-pointer"
                          aria-label={`Filter by intent: ${t.intent || "General"}`}
                        >
                          <Tag className="w-2.5 h-2.5 shrink-0 text-brand-600" />
                          <span className="truncate">{formatShortIntent(t.intent)}</span>
                        </button>
                      </Tooltip>
                    </td>

                    {/* 6. Priority (PriorityMark, Click = filter) */}
                    <td className="px-3">
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          if (onPriorityFilter) {
                            onPriorityFilter(t.priority);
                          }
                        }}
                        className="cursor-pointer hover:opacity-80 transition-opacity"
                        aria-label={`Filter by priority: ${t.priority}`}
                      >
                        <PriorityMark priority={t.priority} />
                      </button>
                    </td>

                    {/* 7. Status */}
                    <td className="px-3">
                      <StatusChip status={t.status} />
                    </td>

                    {/* 8. Dates: compact FlightPathTimeline strip + "Check-in in 2d 4h / LCD 3 Dec" */}
                    <td className="px-3 w-[195px] max-w-[195px] overflow-hidden">
                      <div className="flex flex-col justify-center text-[11px] font-mono-numbers leading-tight min-w-0 w-full max-w-full overflow-hidden">
                        <div className="truncate">
                          <span
                            className={cn(
                              isCheckinControlling
                                ? "font-bold text-content-primary"
                                : "text-content-secondary"
                            )}
                          >
                            {checkInText}
                          </span>
                          {lcdFormatted && (
                            <>
                              <span className="text-content-disabled mx-1">/</span>
                              <span
                                className={cn(
                                  !isCheckinControlling
                                    ? "font-bold text-content-primary"
                                    : "text-content-tertiary"
                                )}
                              >
                                {lcdFormatted}
                              </span>
                            </>
                          )}
                        </div>

                        {/* Compact FlightPathTimeline strip */}
                        <div className="mt-0.5 w-full overflow-hidden">
                          <FlightPathTimeline
                            variant="compact"
                            checkIn={t.check_in_date}
                            lcd={t.lcd_date}
                            createdAt={t.created_at}
                            controllingDeadline={isCheckinControlling ? "CHECK_IN" : "LCD"}
                          />
                        </div>
                      </div>
                    </td>

                    {/* 9. Assignee & Quick Actions */}
                    <td className="px-3 hidden min-[1200px]:table-cell relative">
                      {/* Normal Assignee Display */}
                      <div
                        className={cn(
                          "flex items-center gap-1.5 min-w-0 transition-opacity duration-120",
                          isStaff && "group-hover:opacity-0"
                        )}
                      >
                        {t.assigned_to ? (
                          <>
                            <Avatar name={t.assigned_to} id={t.assigned_to} size="sm" />
                            <span className="text-table font-medium text-content-secondary truncate max-w-[85px]">
                              {t.assigned_to}
                            </span>
                          </>
                        ) : (
                          <span className="inline-flex items-center gap-1.5 text-[11px] text-content-secondary whitespace-nowrap">
                            <span className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" />
                            <span>Unassigned</span>
                          </span>
                        )}
                      </div>

                      {/* Quick Actions (Ghost icon buttons directly on row background: no border, no bubble, no shadow) */}
                      {isStaff && (
                        <div className="absolute inset-y-0 right-2 flex items-center justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity duration-120 pointer-events-none group-hover:pointer-events-auto">
                          {!t.assigned_to && (
                            <button
                              type="button"
                              onClick={(e) => handleAssignToMe(t.id, e)}
                              className="w-7 h-7 rounded-md flex items-center justify-center text-content-tertiary hover:text-brand hover:bg-brand-soft/50 transition-colors cursor-pointer"
                              title="Assign to me"
                              aria-label="Assign to me"
                            >
                              <UserPlus className="w-3.5 h-3.5" />
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={(e) => handleEscalate(t.id, e)}
                            className="w-7 h-7 rounded-md flex items-center justify-center text-content-tertiary hover:text-amber-600 hover:bg-amber-500/10 transition-colors cursor-pointer"
                            title="Escalate ticket"
                            aria-label="Escalate ticket"
                          >
                            <ArrowUpCircle className="w-3.5 h-3.5" />
                          </button>
                          <button
                            type="button"
                            onClick={(e) => handleCopyTboh(t.tboh_id, e)}
                            className="w-7 h-7 rounded-md flex items-center justify-center text-content-tertiary hover:text-content-primary hover:bg-surface-subtle transition-colors cursor-pointer"
                            title="Copy TBOH identifier"
                            aria-label="Copy TBOH identifier"
                          >
                            <Copy className="w-3.5 h-3.5" />
                          </button>
                          <button
                            type="button"
                            onClick={(e) => handleOpenTicket(t.id, e)}
                            className="w-7 h-7 rounded-md flex items-center justify-center text-content-tertiary hover:text-brand hover:bg-brand-soft/50 transition-colors cursor-pointer"
                            title="Open full page"
                            aria-label="Open full page"
                          >
                            <ExternalLink className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      )}
                    </td>

                    {/* 10. Score (Staff Only) */}
                    {isStaff && (
                      <td className="px-3 text-right hidden min-[1280px]:table-cell">
                        {t.queue_score !== null && t.queue_score !== undefined ? (
                          <div className="flex items-center justify-end gap-1.5 font-mono-numbers text-caption">
                            <span className="font-semibold text-content-primary">
                              {t.queue_score}
                            </span>
                            <div className="w-5 h-1 bg-surface-subtle rounded-full overflow-hidden shrink-0 border border-border/60">
                              <div
                                className="h-full bg-brand-500 rounded-full"
                                style={{
                                  width: `${Math.min(100, (t.queue_score / 150) * 100)}%`,
                                }}
                              />
                            </div>
                          </div>
                        ) : (
                          <span className="text-content-disabled text-caption font-mono-numbers">
                            —
                          </span>
                        )}
                      </td>
                    )}
                  </tr>
                );
              })}
            </React.Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}
