"use client";

import React, { useState, useEffect, useCallback, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import { useUser } from "@/context/UserContext";
import { useToast } from "@/context/ToastContext";
import {
  fetchTicketDetail,
  assignTicket,
  unassignTicket,
  updateTicketStatus,
  escalateTicket,
  transferTicket,
  postMessage,
  createSideThread,
  postSideThreadMessage,
  linkSuggestedBug,
} from "@/lib/api";
import { TicketDetail } from "@/lib/types";
import { ErrorState } from "@/components/ui";
import {
  TicketHeader,
  TicketBookingContext,
  TicketConversation,
  TicketInsightRail,
  EscalateModal,
  TransferModal,
  BugLinkModal,
  SupplierThreadModal,
} from "@/components/ticket";
import { cn } from "@/lib/utils";

export default function TicketDetailPage() {
  const params = useParams();
  const router = useRouter();
  const ticketId = params.id as string;
  const { currentUser, isStaff, isLead } = useUser();
  const { showToast } = useToast();

  const [ticket, setTicket] = useState<TicketDetail | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Short violet transition pulse after successful escalation
  const [escalatedSuccess, setEscalatedSuccess] = useState(false);

  // Mobile column switcher: "conversation" | "context" | "insights"
  const [mobileTab, setMobileTab] = useState<"conversation" | "context" | "insights">("conversation");

  // Message composer states
  const [sendingMessage, setSendingMessage] = useState(false);
  const [messageError, setMessageError] = useState<string | null>(null);
  const [lastFailedMessage, setLastFailedMessage] = useState<{
    type: "PublicReply" | "InternalNote";
    content: string;
  } | null>(null);

  // Supplier side thread states
  const [activeSideThreadId, setActiveSideThreadId] = useState<string | null>(null);
  const [sendingSupplierReply, setSendingSupplierReply] = useState(false);

  // Modals
  const [escalateModalOpen, setEscalateModalOpen] = useState(false);
  const [escalating, setEscalating] = useState(false);

  const [transferModalOpen, setTransferModalOpen] = useState(false);
  const [transferring, setTransferring] = useState(false);

  const [bugModalOpen, setBugModalOpen] = useState(false);
  const [linkingBug, setLinkingBug] = useState(false);

  const [supplierModalOpen, setSupplierModalOpen] = useState(false);
  const [creatingSupplierThread, setCreatingSupplierThread] = useState(false);

  // Resilient polling refs & AbortController (M4 load hardening)
  const abortControllerRef = useRef<AbortController | null>(null);
  const backoffDelayRef = useRef<number>(5000);
  const timerIdRef = useRef<NodeJS.Timeout | null>(null);

  // Load ticket detail with AbortSignal & background poll support
  const loadTicket = useCallback(async (isBackgroundPoll = false) => {
    if (!isBackgroundPoll) {
      setLoading(true);
    }
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const data = await fetchTicketDetail(ticketId, currentUser.id, controller.signal);
      setTicket(data);
      if (data.side_conversations && data.side_conversations.length > 0 && !activeSideThreadId) {
        setActiveSideThreadId(data.side_conversations[0].id);
      }
      setError(null);
      backoffDelayRef.current = 5000;
      return true;
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === "AbortError") {
        return false;
      }
      setError(err instanceof Error ? err.message : "Failed to load ticket details");
      return false;
    } finally {
      if (!isBackgroundPoll) {
        setLoading(false);
      }
    }
  }, [ticketId, currentUser.id, activeSideThreadId]);

  // Resilient 30s live polling with jitter, visibility change listener, and backoff
  useEffect(() => {
    let isCancelled = false;

    const scheduleNextPoll = (isError = false) => {
      if (timerIdRef.current) {
        clearTimeout(timerIdRef.current);
      }
      if (typeof document !== "undefined" && document.hidden) {
        return;
      }

      let delay: number;
      if (isError) {
        delay = backoffDelayRef.current;
        backoffDelayRef.current = Math.min(backoffDelayRef.current * 2, 60000);
      } else {
        const jitter = Math.random() * 6000 - 3000;
        delay = Math.max(10000, 30000 + jitter);
      }

      timerIdRef.current = setTimeout(async () => {
        if (isCancelled || (typeof document !== "undefined" && document.hidden)) return;
        const success = await loadTicket(true);
        if (!isCancelled) {
          scheduleNextPoll(!success);
        }
      }, delay);
    };

    loadTicket(false).then((success) => {
      if (!isCancelled) {
        scheduleNextPoll(!success);
      }
    });

    const handleVisibility = () => {
      if (typeof document !== "undefined" && !document.hidden) {
        loadTicket(true).then((success) => {
          if (!isCancelled) {
            scheduleNextPoll(!success);
          }
        });
      } else {
        if (timerIdRef.current) {
          clearTimeout(timerIdRef.current);
        }
        if (abortControllerRef.current) {
          abortControllerRef.current.abort();
        }
      }
    };

    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", handleVisibility);
    }

    return () => {
      isCancelled = true;
      if (typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", handleVisibility);
      }
      if (timerIdRef.current) {
        clearTimeout(timerIdRef.current);
      }
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, [loadTicket]);

  // Real-time Server-Sent Events (SSE) listener for instant 0ms ticket detail updates
  useEffect(() => {
    if (typeof window === "undefined" || typeof EventSource === "undefined") return;

    const token = localStorage.getItem("opsdesk_token");
    const query = token
      ? `?token=${encodeURIComponent(token)}`
      : `?user_id=${encodeURIComponent(currentUser.id)}`;
    const eventSource = new EventSource(`/api/events/stream${query}`);

    const handleTicketEvent = (e: MessageEvent) => {
      try {
        const payload = JSON.parse(e.data);
        if (payload.ticket_id === ticketId) {
          loadTicket(true);
        }
      } catch {
        loadTicket(true);
      }
    };

    eventSource.addEventListener("ticket.assigned", handleTicketEvent);
    eventSource.addEventListener("ticket.unassigned", handleTicketEvent);
    eventSource.addEventListener("ticket.status_changed", handleTicketEvent);
    eventSource.addEventListener("ticket.escalated", handleTicketEvent);
    eventSource.addEventListener("ticket.transferred", handleTicketEvent);
    eventSource.addEventListener("message.created", handleTicketEvent);
    eventSource.addEventListener("side_thread.message_created", handleTicketEvent);

    return () => {
      eventSource.close();
    };
  }, [currentUser.id, ticketId, loadTicket]);

  // Actions
  const handleClaim = async () => {
    try {
      await assignTicket(ticketId, currentUser.id, currentUser.id);
      showToast("Ticket claimed and assigned to your queue", "success");
      loadTicket();
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : "Assignment failed", "error");
    }
  };

  const handleUnassign = async () => {
    try {
      await unassignTicket(ticketId, currentUser.id);
      showToast("Ticket unassigned and returned to triage queue", "info");
      loadTicket();
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : "Unassign failed", "error");
    }
  };

  const handleStatusChange = async (newStatus: string) => {
    try {
      await updateTicketStatus(ticketId, newStatus, currentUser.id);
      showToast(`Status updated to ${newStatus}`, "info");
      loadTicket();
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : "Invalid status transition", "error");
    }
  };

  const handleEscalateConfirm = async (reason: string) => {
    setEscalating(true);
    try {
      await escalateTicket(ticketId, reason, currentUser.id);
      setEscalateModalOpen(false);
      setEscalatedSuccess(true);
      setTimeout(() => setEscalatedSuccess(false), 3500);
      showToast("Ticket escalated to Operations Escalation Manager (Vikram Joshi)", "warning");
      loadTicket();
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : "Escalation failed", "error");
    } finally {
      setEscalating(false);
    }
  };

  const handleTransferConfirm = async (targetAgentId: string, reason: string) => {
    setTransferring(true);
    try {
      await transferTicket(ticketId, targetAgentId, reason, currentUser.id);
      setTransferModalOpen(false);
      showToast(
        `Ticket transferred to ${targetAgentId} (supplier thread recipients preserved)`,
        "success"
      );
      loadTicket();
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : "Transfer failed", "error");
    } finally {
      setTransferring(false);
    }
  };

  const handleBugLinkConfirm = async (bugLink: string) => {
    setLinkingBug(true);
    try {
      await linkSuggestedBug(ticketId, bugLink, currentUser.id);
      setBugModalOpen(false);
      showToast("Internal product defect reference linked", "success");
      loadTicket();
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : "Defect link failed", "error");
    } finally {
      setLinkingBug(false);
    }
  };

  const handleCreateSupplierThread = async (payload: {
    supplier_name: string;
    subject: string;
    recipients: string[];
    initial_message: string;
  }) => {
    setCreatingSupplierThread(true);
    try {
      await createSideThread(ticketId, payload, currentUser.id);
      setSupplierModalOpen(false);
      showToast(`Supplier thread opened with ${payload.supplier_name}`, "success");
      loadTicket();
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : "Failed to open supplier thread", "error");
    } finally {
      setCreatingSupplierThread(false);
    }
  };

  const handlePostMessage = async (type: "PublicReply" | "InternalNote", content: string) => {
    setSendingMessage(true);
    setMessageError(null);
    setLastFailedMessage({ type, content });
    try {
      await postMessage(ticketId, type, content, currentUser.id);
      setLastFailedMessage(null);
      showToast(
        type === "PublicReply"
          ? "Customer reply dispatched to agency"
          : "Internal note recorded on audit trail",
        "success"
      );
      loadTicket();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to post message";
      setMessageError(msg);
      showToast(msg, "error");
    } finally {
      setSendingMessage(false);
    }
  };

  const handleRetryMessage = async () => {
    if (lastFailedMessage) {
      await handlePostMessage(lastFailedMessage.type, lastFailedMessage.content);
    }
  };

  const handlePostSupplierReply = async (threadId: string, message: string) => {
    setSendingSupplierReply(true);
    try {
      await postSideThreadMessage(ticketId, threadId, message, currentUser.id);
      showToast("Supplier email reply dispatched", "success");
      loadTicket();
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : "Failed to send supplier reply", "error");
    } finally {
      setSendingSupplierReply(false);
    }
  };

  // Loading Skeleton
  if (loading) {
    return (
      <div className="max-w-[1440px] mx-auto py-8 px-4 sm:px-6 w-full overflow-x-hidden">
        <div className="flex items-center gap-2 mb-6">
          <div className="w-20 h-4 bg-surface-subtle border border-border rounded animate-pulse" />
          <div className="w-4 h-4 bg-surface-subtle border border-border rounded animate-pulse" />
          <div className="w-24 h-4 bg-surface-subtle border border-border rounded animate-pulse" />
        </div>
        <div className="h-28 bg-surface border border-border rounded-card animate-pulse mb-6" />
        <div className="grid grid-cols-1 xl:grid-cols-[280px_1fr_320px] gap-6">
          <div className="h-96 bg-surface border border-border rounded-card animate-pulse" />
          <div className="h-[600px] bg-surface border border-border rounded-card animate-pulse" />
          <div className="h-96 bg-surface border border-border rounded-card animate-pulse" />
        </div>
      </div>
    );
  }

  // Error State
  if (error || !ticket) {
    return (
      <div className="max-w-2xl mx-auto py-16 px-6">
        <ErrorState
          title="Case Not Found or Access Restricted"
          message={error || "Unable to display this case. It may have been archived or restricted to internal staff."}
          onRetry={() => router.push("/")}
        />
      </div>
    );
  }

  return (
    <div className="max-w-[1440px] w-full mx-auto py-6 px-4 sm:px-6 overflow-x-hidden">
      {/* 1. HEADER */}
      <TicketHeader
        ticket={ticket}
        isStaff={isStaff}
        isLead={isLead}
        currentUserId={currentUser.id}
        onClaim={handleClaim}
        onUnassign={handleUnassign}
        onStatusChange={handleStatusChange}
        onOpenEscalate={() => setEscalateModalOpen(true)}
        onOpenTransfer={() => setTransferModalOpen(true)}
        escalatedSuccess={escalatedSuccess}
      />

      {/* 2. MOBILE STICKY NAVIGATION TABS (< 768px) */}
      <div className="md:hidden sticky top-[56px] z-20 bg-surface/95 backdrop-blur border-b border-border py-2 mb-4">
        <div className="flex gap-1.5 overflow-x-auto">
          <button
            type="button"
            onClick={() => setMobileTab("conversation")}
            className={cn(
              "flex-1 py-1.5 px-3 rounded-input text-caption font-semibold transition-subtle text-center whitespace-nowrap cursor-pointer",
              mobileTab === "conversation"
                ? "bg-brand-600 text-white shadow-xs"
                : "bg-surface-subtle text-content-secondary hover:text-content-primary"
            )}
          >
            Conversation
          </button>
          <button
            type="button"
            onClick={() => setMobileTab("context")}
            className={cn(
              "flex-1 py-1.5 px-3 rounded-input text-caption font-semibold transition-subtle text-center whitespace-nowrap cursor-pointer",
              mobileTab === "context"
                ? "bg-brand-600 text-white shadow-xs"
                : "bg-surface-subtle text-content-secondary hover:text-content-primary"
            )}
          >
            Booking Context
          </button>
          {isStaff && (
            <button
              type="button"
              onClick={() => setMobileTab("insights")}
              className={cn(
                "flex-1 py-1.5 px-3 rounded-input text-caption font-semibold transition-subtle text-center whitespace-nowrap cursor-pointer",
                mobileTab === "insights"
                  ? "bg-brand-600 text-white shadow-xs"
                  : "bg-surface-subtle text-content-secondary hover:text-content-primary"
              )}
            >
              Insight Rail
            </button>
          )}
        </div>
      </div>

      {/* 3. RESPONSIVE LAYOUT CONTAINER */}
      {/* Desktop >= 1280px: 280px | flexible | 320px
          Tablet 768px - 1279px: 280px | flexible, with insight rail dropping below
          Mobile < 768px: single column with sticky tabs
          Requester: 2-column layout (Booking Context + Conversation), NO insight rail */}
      {isStaff ? (
        <div className="grid grid-cols-1 md:grid-cols-[280px_1fr] xl:grid-cols-[280px_1fr_320px] gap-6 items-start">
          {/* LEFT COLUMN: Booking Context */}
          <div
            className={cn(
              "w-full md:w-[280px] shrink-0",
              mobileTab !== "context" && "hidden md:block"
            )}
          >
            <TicketBookingContext ticket={ticket} currentUserId={currentUser.id} />
          </div>

          {/* CENTRE COLUMN: Conversation */}
          <div
            className={cn(
              "min-w-0 flex-1 w-full",
              mobileTab !== "conversation" && "hidden md:block"
            )}
          >
            <TicketConversation
              ticket={ticket}
              isStaff={isStaff}
              currentUserId={currentUser.id}
              onPostMessage={handlePostMessage}
              sendingMessage={sendingMessage}
              messageError={messageError}
              onRetryMessage={handleRetryMessage}
              activeSideThreadId={activeSideThreadId}
              onSelectSideThread={(id) => setActiveSideThreadId(id)}
              onOpenNewThreadModal={() => setSupplierModalOpen(true)}
              onPostSupplierReply={handlePostSupplierReply}
              sendingSupplierReply={sendingSupplierReply}
            />
          </div>

          {/* RIGHT COLUMN: Insight Rail (STAFF ONLY) */}
          <div
            className={cn(
              "w-full md:col-span-2 xl:col-span-1 xl:w-[320px] shrink-0",
              mobileTab !== "insights" && "hidden md:block"
            )}
          >
            <TicketInsightRail
              ticket={ticket}
              onOpenBugModal={() => setBugModalOpen(true)}
              currentUserId={currentUser.id}
            />
          </div>
        </div>
      ) : (
        /* REQUESTER VARIANT: Clean, 2-column layout, no staff cards, no internal notes */
        <div className="grid grid-cols-1 md:grid-cols-[280px_1fr] xl:grid-cols-[300px_1fr] gap-6 items-start">
          {/* LEFT COLUMN */}
          <div
            className={cn(
              "w-full md:w-[280px] xl:w-[300px] shrink-0",
              mobileTab !== "context" && "hidden md:block"
            )}
          >
            <TicketBookingContext ticket={ticket} currentUserId={currentUser.id} />
          </div>

          {/* CENTRE COLUMN */}
          <div
            className={cn(
              "min-w-0 flex-1 w-full",
              mobileTab !== "conversation" && "hidden md:block"
            )}
          >
            <TicketConversation
              ticket={ticket}
              isStaff={false}
              currentUserId={currentUser.id}
              onPostMessage={handlePostMessage}
              sendingMessage={sendingMessage}
              messageError={messageError}
              onRetryMessage={handleRetryMessage}
              activeSideThreadId={activeSideThreadId}
              onSelectSideThread={(id) => setActiveSideThreadId(id)}
              onOpenNewThreadModal={() => setSupplierModalOpen(true)}
              onPostSupplierReply={handlePostSupplierReply}
              sendingSupplierReply={sendingSupplierReply}
            />
          </div>
        </div>
      )}

      {/* 4. MODALS */}
      <EscalateModal
        isOpen={escalateModalOpen}
        onClose={() => setEscalateModalOpen(false)}
        onConfirm={handleEscalateConfirm}
        loading={escalating}
      />

      <TransferModal
        isOpen={transferModalOpen}
        onClose={() => setTransferModalOpen(false)}
        onConfirm={handleTransferConfirm}
        loading={transferring}
        currentAssigneeId={ticket.assigned_to}
      />

      <BugLinkModal
        isOpen={bugModalOpen}
        onClose={() => setBugModalOpen(false)}
        onConfirm={handleBugLinkConfirm}
        currentBugLink={ticket.suggested_bug_link}
        loading={linkingBug}
      />

      <SupplierThreadModal
        isOpen={supplierModalOpen}
        onClose={() => setSupplierModalOpen(false)}
        onConfirm={handleCreateSupplierThread}
        loading={creatingSupplierThread}
      />
    </div>
  );
}
