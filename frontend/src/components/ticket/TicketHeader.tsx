"use client";

import React, { useMemo } from "react";
import Link from "next/link";
import { TicketDetail } from "@/lib/types";
import {
  StatusChip,
  PriorityMark,
  SlaBadge,
  SlaRing,
  Button,
  Tooltip,
} from "@/components/ui";
import {
  ArrowLeft,
  UserCheck,
  UserX,
  Shuffle,
  ShieldAlert,
  ChevronDown,
} from "lucide-react";
import { cn } from "@/lib/utils";

export interface TicketHeaderProps {
  ticket: TicketDetail;
  isStaff: boolean;
  isLead: boolean;
  currentUserId: string;
  onClaim: () => Promise<void>;
  onUnassign: () => Promise<void>;
  onStatusChange: (status: string) => Promise<void>;
  onOpenEscalate: () => void;
  onOpenTransfer: () => void;
  escalatedSuccess?: boolean;
}

export function TicketHeader({
  ticket,
  isStaff,
  isLead,
  currentUserId,
  onClaim,
  onUnassign,
  onStatusChange,
  onOpenEscalate,
  onOpenTransfer,
  escalatedSuccess = false,
}: TicketHeaderProps) {
  // Compute valid next states based on status state-machine
  const validNextStatuses = useMemo((): string[] => {
    switch (ticket.status) {
      case "New":
        return ["Open", "Pending", "Escalated", "Closed"];
      case "Open":
        return ["Pending", "Escalated", "Resolved", "Closed"];
      case "Pending":
        return ["Open", "Escalated", "Resolved", "Closed"];
      case "Escalated":
        return ["Open", "Pending", "Resolved", "Closed"];
      case "Resolved":
        return ["Closed", "Open"];
      case "Closed":
        return isLead ? ["Open"] : [];
      default:
        return ["Open", "Pending", "Resolved", "Closed"];
    }
  }, [ticket.status, isLead]);

  const isAssignedToMe = ticket.assigned_to === currentUserId;
  const isClosed = ticket.status === "Closed";
  const isEscalated = ticket.status === "Escalated";

  return (
    <div className="mb-6">
      {/* 1. BREADCRUMB: "Queue / TCK-xxxx" */}
      <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-caption text-content-secondary mb-3">
        <Link
          href="/"
          className="hover:text-content-primary inline-flex items-center gap-1 transition-subtle"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          <span>Queue</span>
        </Link>
        <span className="text-content-tertiary">/</span>
        <span className="font-mono-numbers font-semibold text-content-primary">
          {ticket.id}
        </span>
      </nav>

      {/* 2. ACTION HEADER CARD */}
      <div
        className={cn(
          "bg-surface border border-border rounded-card p-5 shadow-xs transition-all duration-700",
          escalatedSuccess &&
            "border-violet-400 ring-2 ring-violet-500/50 bg-violet-50/30 shadow-md shadow-violet-100/50 animate-in fade-in"
        )}
      >
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          {/* Metadata & Title with Eyebrow */}
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2.5">
              <span className="font-mono-numbers text-xs font-semibold px-2 py-0.5 rounded bg-surface-subtle text-content-primary border border-border">
                {ticket.id}
              </span>
              <StatusChip status={ticket.status} />
              <PriorityMark priority={ticket.priority} />

              {/* Large SlaBadge + SlaRing Container */}
              <div className="inline-flex items-center gap-2 px-2.5 py-1 bg-surface-subtle rounded-card border border-border">
                <SlaRing
                  status={ticket.sla.status}
                  hoursRemaining={ticket.sla.hours_remaining}
                  size={20}
                />
                <SlaBadge
                  sla={ticket.sla}
                  size="lg"
                  isEscalated={isEscalated}
                  className="border-0 bg-transparent p-0 shadow-none font-semibold"
                />
              </div>
            </div>

            <div>
              <div className="text-[11px] font-semibold text-content-tertiary uppercase tracking-wider mb-1">
                Booking Incident · {ticket.tboh_id} · {ticket.agency_id}
              </div>
              <h1 className="text-xl sm:text-2xl font-semibold text-content-primary tracking-tight">
                {ticket.title}
              </h1>
            </div>
          </div>

          {/* Action Buttons (Staff Only) */}
          {isStaff && (
            <div className="flex flex-wrap items-center gap-2 shrink-0">
              {/* 1. ASSIGN / CLAIM BUTTON */}
              {isClosed ? (
                <Tooltip content="Cannot assign a closed ticket">
                  <span>
                    <Button
                      variant="secondary"
                      size="sm"
                      icon={<UserCheck className="w-3.5 h-3.5 text-content-disabled" />}
                      disabled
                    >
                      Assign
                    </Button>
                  </span>
                </Tooltip>
              ) : isAssignedToMe ? (
                <Tooltip content="Case is assigned to your active queue">
                  <span>
                    <Button
                      variant="secondary"
                      size="sm"
                      icon={<UserCheck className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />}
                      disabled
                    >
                      Assigned to You
                    </Button>
                  </span>
                </Tooltip>
              ) : ticket.assigned_to ? (
                <Button
                  variant="primary"
                  size="sm"
                  icon={<UserCheck className="w-3.5 h-3.5" />}
                  onClick={onClaim}
                >
                  Claim (Reassign)
                </Button>
              ) : (
                <Button
                  variant="primary"
                  size="sm"
                  icon={<UserCheck className="w-3.5 h-3.5" />}
                  onClick={onClaim}
                >
                  Assign to Me
                </Button>
              )}

              {/* 2. UNASSIGN BUTTON */}
              {isClosed ? (
                <Tooltip content="Cannot unassign a closed ticket">
                  <span>
                    <Button
                      variant="secondary"
                      size="sm"
                      icon={<UserX className="w-3.5 h-3.5 text-content-disabled" />}
                      disabled
                    >
                      Unassign
                    </Button>
                  </span>
                </Tooltip>
              ) : ticket.assigned_to ? (
                <Button
                  variant="secondary"
                  size="sm"
                  icon={<UserX className="w-3.5 h-3.5 text-content-secondary" />}
                  onClick={onUnassign}
                >
                  Unassign
                </Button>
              ) : (
                <Tooltip content="Case is not currently assigned to any agent">
                  <span>
                    <Button
                      variant="secondary"
                      size="sm"
                      icon={<UserX className="w-3.5 h-3.5 text-content-disabled" />}
                      disabled
                    >
                      Unassign
                    </Button>
                  </span>
                </Tooltip>
              )}

              {/* 3. CHANGE STATUS (VALID NEXT STATES ONLY) */}
              <div className="flex items-center">
                {isClosed && !isLead ? (
                  <Tooltip content="Closed tickets are terminal. Only Operations Leads can reopen.">
                    <span>
                      <Button variant="secondary" size="sm" disabled>
                        Closed (Terminal)
                      </Button>
                    </span>
                  </Tooltip>
                ) : (
                  <div className="relative">
                    <select
                      value={ticket.status}
                      onChange={(e) => onStatusChange(e.target.value)}
                      className="h-8 pl-2.5 pr-7 bg-surface border border-border rounded-input text-caption font-medium text-content-primary hover:border-border-strong focus:outline-none focus:ring-2 focus:ring-brand-500 transition-subtle cursor-pointer appearance-none"
                      aria-label="Change ticket status"
                    >
                      <option value={ticket.status} disabled>
                        Status: {ticket.status}
                      </option>
                      {validNextStatuses.map((st) => (
                        <option key={st} value={st}>
                          {isClosed && st === "Open" ? "Reopen as Open" : `Mark as ${st}`}
                        </option>
                      ))}
                    </select>
                    <ChevronDown className="w-3.5 h-3.5 text-content-tertiary absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none" />
                  </div>
                )}
              </div>

              {/* 4. ESCALATE (RED OUTLINE, STATE COLOUR) */}
              {isEscalated ? (
                <Tooltip content="Ticket is already escalated to Operations Escalation Manager">
                  <span>
                    <button
                      type="button"
                      disabled
                      className="inline-flex items-center gap-1.5 h-8 px-3 text-caption font-semibold rounded-input border border-[#EDB9B3] bg-[#F8E1DE]/20 text-[#9B1C1C] opacity-60 cursor-not-allowed"
                    >
                      <ShieldAlert className="w-3.5 h-3.5 text-[#9B1C1C]" />
                      <span>Escalated</span>
                    </button>
                  </span>
                </Tooltip>
              ) : isClosed ? (
                <Tooltip content="Cannot escalate a closed ticket">
                  <span>
                    <button
                      type="button"
                      disabled
                      className="inline-flex items-center gap-1.5 h-8 px-3 text-caption font-semibold rounded-input border border-[#EDB9B3] bg-[#F8E1DE]/20 text-[#9B1C1C] opacity-60 cursor-not-allowed"
                    >
                      <ShieldAlert className="w-3.5 h-3.5 text-[#9B1C1C]" />
                      <span>Escalate</span>
                    </button>
                  </span>
                </Tooltip>
              ) : (
                <button
                  type="button"
                  onClick={onOpenEscalate}
                  className="border border-[#EDB9B3] text-[#9B1C1C] bg-[#F8E1DE]/20 hover:bg-[#F8E1DE]/50 font-semibold rounded-input px-3 h-8 text-caption inline-flex items-center gap-1.5 transition-colors cursor-pointer focus:outline-none focus:ring-2 focus:ring-[#9B1C1C]"
                >
                  <ShieldAlert className="w-3.5 h-3.5 text-[#9B1C1C]" />
                  <span>Escalate</span>
                </button>
              )}

              {/* 5. TRANSFER */}
              {isClosed ? (
                <Tooltip content="Cannot transfer a closed ticket">
                  <span>
                    <Button
                      variant="secondary"
                      size="sm"
                      icon={<Shuffle className="w-3.5 h-3.5 text-content-disabled" />}
                      disabled
                    >
                      Transfer
                    </Button>
                  </span>
                </Tooltip>
              ) : (
                <Button
                  variant="secondary"
                  size="sm"
                  icon={<Shuffle className="w-3.5 h-3.5 text-content-secondary" />}
                  onClick={onOpenTransfer}
                >
                  Transfer
                </Button>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
