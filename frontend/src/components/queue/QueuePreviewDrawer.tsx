"use client";

import React, { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import {
  ExternalLink,
  UserPlus,
  ArrowUpCircle,
  Copy,
  Calendar,
  Clock,
  MessageSquare,
  Link2,
  ChevronLeft,
  ChevronRight,
  ShieldAlert,
} from "lucide-react";
import { TicketDetail, DEMO_USERS } from "@/lib/types";
import { fetchTicketDetail, assignTicket, escalateTicket } from "@/lib/api";
import {
  Drawer,
  SlaBadge,
  SlaRing,
  PriorityMark,
  StatusChip,
  FlightPathTimeline,
  Avatar,
  Button,
  Skeleton,
} from "@/components/ui";
import { useUser } from "@/context/UserContext";
import { useToast } from "@/context/ToastContext";
import { formatDate, parseUtc } from "@/lib/utils";

export interface QueuePreviewDrawerProps {
  ticketId: string | null;
  isOpen: boolean;
  onClose: () => void;
  onNextTicket?: () => void;
  onPrevTicket?: () => void;
  onRefresh?: () => void;
}

export function QueuePreviewDrawer({
  ticketId,
  isOpen,
  onClose,
  onNextTicket,
  onPrevTicket,
  onRefresh,
}: QueuePreviewDrawerProps) {
  const router = useRouter();
  const { currentUser, isStaff } = useUser();
  const { showToast } = useToast();

  const [ticket, setTicket] = useState<TicketDetail | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Load ticket details when ticketId changes
  useEffect(() => {
    if (!ticketId || !isOpen) return;

    let isMounted = true;
    setLoading(true);
    setError(null);

    fetchTicketDetail(ticketId, currentUser.id)
      .then((data) => {
        if (isMounted) {
          setTicket(data);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (isMounted) {
          setError(err instanceof Error ? err.message : "Failed to load case details");
          setLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [ticketId, isOpen, currentUser.id]);

  // Global Keyboard Shortcuts when Drawer is open: J/K, Enter, Esc
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      // Don't trigger if user is typing in an input or textarea
      if (
        document.activeElement?.tagName === "INPUT" ||
        document.activeElement?.tagName === "TEXTAREA"
      ) {
        return;
      }

      if (e.key === "j" || e.key === "ArrowDown") {
        e.preventDefault();
        onNextTicket?.();
      } else if (e.key === "k" || e.key === "ArrowUp") {
        e.preventDefault();
        onPrevTicket?.();
      } else if (e.key === "Enter" && ticketId) {
        e.preventDefault();
        router.push(`/ticket/${ticketId}`);
      } else if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, ticketId, onNextTicket, onPrevTicket, onClose, router]);

  const handleAssignToMe = async () => {
    if (!ticket) return;
    try {
      await assignTicket(ticket.id, currentUser.id, currentUser.id);
      showToast(`Assigned ticket ${ticket.id} to you`, "success");
      onRefresh?.();
      // Reload drawer ticket
      const updated = await fetchTicketDetail(ticket.id, currentUser.id);
      setTicket(updated);
    } catch {
      showToast("Failed to assign ticket", "error");
    }
  };

  const handleEscalate = async () => {
    if (!ticket) return;
    try {
      await escalateTicket(ticket.id, "Operational escalation from split view drawer", currentUser.id);
      showToast(`Escalated ticket ${ticket.id}`, "warning");
      onRefresh?.();
      const updated = await fetchTicketDetail(ticket.id, currentUser.id);
      setTicket(updated);
    } catch {
      showToast("Failed to escalate ticket", "error");
    }
  };

  const handleCopyTboh = () => {
    if (!ticket) return;
    navigator.clipboard.writeText(ticket.tboh_id);
    showToast(`Copied ${ticket.tboh_id} to clipboard`, "info");
  };

  if (!isOpen) return null;

  return (
    <Drawer
      isOpen={isOpen}
      onClose={onClose}
      width="lg"
      title={
        <div className="flex items-center gap-2">
          <span className="font-mono-numbers text-[16px] font-bold text-content-primary">
            {ticketId}
          </span>
          {ticket && (
            <span className="font-mono-numbers text-caption text-content-tertiary">
              ({ticket.tboh_id})
            </span>
          )}
        </div>
      }
      subtitle={
        <div className="flex items-center gap-2 text-[11px] font-mono-numbers text-content-tertiary">
          <span>Use J/K to navigate rows</span>
          <span>•</span>
          <span>Enter to open full page</span>
        </div>
      }
    >
      {/* Navigation Controls Bar */}
      <div className="flex items-center justify-between pb-3 mb-4 border-b border-border text-caption">
        <div className="flex items-center gap-1.5">
          <Button
            variant="ghost"
            size="sm"
            onClick={onPrevTicket}
            icon={<ChevronLeft className="w-3.5 h-3.5" />}
            title="Previous case (K)"
          >
            Prev (K)
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={onNextTicket}
            icon={<ChevronRight className="w-3.5 h-3.5" />}
            iconPosition="right"
            title="Next case (J)"
          >
            Next (J)
          </Button>
        </div>

        <Button
          variant="primary"
          size="sm"
          onClick={() => {
            if (ticketId) router.push(`/ticket/${ticketId}`);
          }}
          icon={<ExternalLink className="w-3.5 h-3.5" />}
          iconPosition="right"
          className="bg-brand-600 hover:bg-brand-700 text-white font-medium"
        >
          Open full page
        </Button>
      </div>

      {loading ? (
        <div className="flex flex-col gap-4 py-4">
          <Skeleton className="h-6 w-3/4 rounded-input" />
          <Skeleton className="h-20 w-full rounded-card" />
          <Skeleton className="h-32 w-full rounded-card" />
        </div>
      ) : error ? (
        <div className="p-4 bg-red-50 text-red-700 rounded-card border border-red-200 text-caption">
          {error}
        </div>
      ) : ticket ? (
        <div className="flex flex-col gap-5 text-sans select-none">
          {/* Title & Badges */}
          <div className="flex flex-col gap-2">
            <h3 className="text-section font-semibold text-content-primary leading-tight">
              {ticket.title}
            </h3>
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <SlaRing status={ticket.sla.status} hoursRemaining={ticket.sla.hours_remaining} size={18} />
              <SlaBadge sla={ticket.sla} size="md" isEscalated={ticket.status === "Escalated"} />
              <PriorityMark priority={ticket.priority} />
              <StatusChip status={ticket.status} />
              {ticket.intent && (
                <span className="text-[11px] font-medium text-brand-700 bg-brand-50 border border-brand-200 px-2 py-0.5 rounded-chip">
                  {ticket.intent}
                </span>
              )}
            </div>
          </div>

          {/* Quick Actions Row (Staff Only) */}
          {isStaff && (
            <div className="flex items-center gap-2 p-2.5 rounded-card bg-surface-subtle border border-border">
              {!ticket.assigned_to && (
                <Button
                  variant="secondary"
                  size="sm"
                  icon={<UserPlus className="w-3.5 h-3.5 text-brand-600" />}
                  onClick={handleAssignToMe}
                >
                  Assign to me
                </Button>
              )}
              <Button
                variant="secondary"
                size="sm"
                icon={<ArrowUpCircle className="w-3.5 h-3.5 text-amber-600" />}
                onClick={handleEscalate}
              >
                Escalate
              </Button>
              <Button
                variant="secondary"
                size="sm"
                icon={<Copy className="w-3.5 h-3.5" />}
                onClick={handleCopyTboh}
              >
                Copy TBOH
              </Button>
            </div>
          )}

          {/* Flight Path Timeline */}
          <div className="border border-border rounded-card p-3.5 bg-surface shadow-2xs">
            <h4 className="text-micro-label uppercase font-bold text-content-tertiary tracking-wider mb-1">
              Flight Path &amp; Deadlines
            </h4>
            <FlightPathTimeline
              variant="full"
              checkIn={ticket.check_in_date}
              lcd={ticket.lcd_date}
              createdAt={ticket.created_at}
            />
          </div>

          {/* Booking & Agency Metadata */}
          <div className="grid grid-cols-2 gap-3 p-3 rounded-card bg-surface border border-border text-caption">
            <div>
              <span className="text-content-tertiary text-[11px] block">Agency Tenant</span>
              <div className="flex items-center gap-1.5 mt-0.5">
                <Avatar name={ticket.agency_id} id={ticket.agency_id} size="sm" />
                <span className="font-semibold text-content-primary">{ticket.agency_id}</span>
              </div>
            </div>

            <div>
              <span className="text-content-tertiary text-[11px] block">Assignee</span>
              <div className="flex items-center gap-1.5 mt-0.5">
                {ticket.assigned_to ? (
                  <>
                    <Avatar name={ticket.assigned_to} id={ticket.assigned_to} size="sm" />
                    <span className="font-semibold text-content-primary">{ticket.assigned_to}</span>
                  </>
                ) : (
                  <span className="text-content-disabled italic text-[11px]">Unassigned</span>
                )}
              </div>
            </div>

            <div>
              <span className="text-content-tertiary text-[11px] block">Check-in Date</span>
              <span className="font-mono-numbers text-content-primary flex items-center gap-1 mt-0.5">
                <Calendar className="w-3 h-3 text-content-tertiary" />
                {formatDate(ticket.check_in_date)}
              </span>
            </div>

            <div>
              <span className="text-content-tertiary text-[11px] block">Last Cancellation Date</span>
              <span className="font-mono-numbers text-content-primary flex items-center gap-1 mt-0.5">
                <Clock className="w-3 h-3 text-content-tertiary" />
                {ticket.lcd_date ? formatDate(ticket.lcd_date) : "None"}
              </span>
            </div>
          </div>

          {/* Description */}
          <div className="flex flex-col gap-1.5">
            <h4 className="text-micro-label uppercase font-bold text-content-tertiary tracking-wider">
              Issue Description
            </h4>
            <p className="text-body text-content-secondary bg-surface-subtle/50 p-3 rounded-card border border-border whitespace-pre-wrap leading-relaxed">
              {ticket.description || "No description provided."}
            </p>
          </div>

          {/* Routing Explanation (Staff Only) */}
          {isStaff && ticket.routing_reason && (
            <div className="flex items-start gap-2 p-3 bg-amber-50/70 border border-amber-200/80 rounded-card text-caption text-amber-900">
              <ShieldAlert className="w-4 h-4 text-amber-700 shrink-0 mt-0.5" />
              <div>
                <span className="font-semibold block text-[11px] uppercase tracking-wider text-amber-800">
                  Routing Reason
                </span>
                <span className="text-[12px]">{ticket.routing_reason}</span>
              </div>
            </div>
          )}

          {/* Linked Tickets */}
          {ticket.linked_ticket_ids && ticket.linked_ticket_ids.length > 0 && (
            <div className="flex flex-col gap-1.5">
              <h4 className="text-micro-label uppercase font-bold text-content-tertiary tracking-wider flex items-center gap-1.5">
                <Link2 className="w-3.5 h-3.5 text-brand-600" />
                Linked Sibling Cases ({ticket.linked_ticket_ids.length})
              </h4>
              <div className="flex flex-wrap gap-1.5">
                {ticket.linked_ticket_ids.map((id) => (
                  <button
                    key={id}
                    type="button"
                    onClick={() => router.push(`/ticket/${id}`)}
                    className="font-mono-numbers text-[12px] font-semibold text-brand-700 bg-brand-50 hover:bg-brand-100 border border-brand-200 px-2 py-1 rounded-chip transition-colors cursor-pointer"
                  >
                    {id} →
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Recent Messages Preview */}
          {ticket.messages && ticket.messages.length > 0 && (
            <div className="flex flex-col gap-2 pt-2 border-t border-border">
              <h4 className="text-micro-label uppercase font-bold text-content-tertiary tracking-wider flex items-center gap-1.5">
                <MessageSquare className="w-3.5 h-3.5 text-content-tertiary" />
                Messages ({ticket.messages.length})
              </h4>
              <div className="flex flex-col gap-2">
                {ticket.messages.slice(-2).map((msg) => (
                  <div
                    key={msg.id}
                    className="p-2.5 rounded-card bg-surface border border-border text-caption flex flex-col gap-1"
                  >
                    <div className="flex items-center justify-between text-[11px] text-content-tertiary">
                      <span className="font-semibold text-content-secondary">
                        {msg.sender_name ||
                          DEMO_USERS.find((u) => u.id === (msg.sender_id || msg.sender_user_id))?.name ||
                          msg.sender_id ||
                          msg.sender_user_id ||
                          "Agent"}
                      </span>
                      <span className="font-mono-numbers">
                        {parseUtc(msg.created_at)?.toLocaleTimeString([], {
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </span>
                    </div>
                    <p className="text-content-primary line-clamp-2">{msg.content}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      ) : null}
    </Drawer>
  );
}
