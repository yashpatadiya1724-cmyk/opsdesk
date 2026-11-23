"use client";

import React, { useState, useRef, useEffect } from "react";
import { TicketDetail, TicketMessage, DEMO_USERS } from "@/lib/types";
import {
  Card,
  Avatar,
  Chip,
  Button,
  Tabs,
  Tooltip,
  EmptyState,
} from "@/components/ui";
import {
  Send,
  Lock,
  Globe,
  RotateCcw,
  MessageSquare,
  Copy,
  Check,
  Quote,
} from "lucide-react";
import { cn, formatDate, formatRelativeTime } from "@/lib/utils";
import { TicketSupplierThreads } from "./TicketSupplierThreads";
import { TicketActivityTimeline } from "./TicketActivityTimeline";

export interface TicketConversationProps {
  ticket: TicketDetail;
  isStaff: boolean;
  currentUserId?: string;
  onPostMessage: (type: "PublicReply" | "InternalNote", content: string) => Promise<void>;
  sendingMessage: boolean;
  messageError: string | null;
  onRetryMessage?: () => void;
  // Supplier thread handlers
  activeSideThreadId: string | null;
  onSelectSideThread: (id: string) => void;
  onOpenNewThreadModal: () => void;
  onPostSupplierReply: (threadId: string, message: string) => Promise<void>;
  sendingSupplierReply: boolean;
}

export function TicketConversation({
  ticket,
  isStaff,
  onPostMessage,
  sendingMessage,
  messageError,
  onRetryMessage,
  activeSideThreadId,
  onSelectSideThread,
  onOpenNewThreadModal,
  onPostSupplierReply,
  sendingSupplierReply,
}: TicketConversationProps) {
  // Tabs: "public" | "internal" | "suppliers" | "activity"
  const [activeTab, setActiveTab] = useState<string>("public");
  const [content, setContent] = useState<string>("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Copy & Quote state
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);

  // Auto-grow textarea effect
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${Math.min(
        Math.max(textareaRef.current.scrollHeight, 84),
        260
      )}px`;
    }
  }, [content]);

  // Keyboard shortcut Cmd/Ctrl + Enter
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleSubmit = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!content.trim() || sendingMessage) return;

    const messageType: "PublicReply" | "InternalNote" =
      activeTab === "internal" ? "InternalNote" : "PublicReply";

    await onPostMessage(messageType, content.trim());
    setContent("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "84px";
    }
  };

  // Copy message text to clipboard
  const handleCopyMessage = (msg: TicketMessage) => {
    navigator.clipboard.writeText(msg.content);
    setCopiedMessageId(msg.id);
    setTimeout(() => {
      setCopiedMessageId((prev) => (prev === msg.id ? null : prev));
    }, 2000);
  };

  // Quote message into composer
  const handleQuoteMessage = (msg: TicketMessage) => {
    const quoteText = `> ${msg.sender_name}: "${msg.content}"\n\n`;
    setContent((prev) => (prev ? `${prev}\n${quoteText}` : quoteText));
    // If quoting an internal note as staff, switch to internal tab; otherwise public
    if (isStaff && msg.message_type === "InternalNote") {
      setActiveTab("internal");
    } else {
      setActiveTab("public");
    }
    textareaRef.current?.focus();
  };

  // Determine role of message sender for role chip
  const getSenderRole = (
    userId: string,
    senderName: string
  ): { label: string; variant: "brand" | "subtle" | "default" } => {
    const user = DEMO_USERS.find((u) => u.id === userId || u.name === senderName);
    if (user) {
      if (user.role === "Lead") return { label: "Operations Lead", variant: "brand" };
      if (user.role === "EscalationManager") return { label: "Escalation Manager", variant: "brand" };
      if (user.role === "Agent") return { label: "Operations Specialist", variant: "brand" };
      if (user.role === "Requester") return { label: "Agency Partner", variant: "subtle" };
    }
    return { label: "Staff", variant: "default" };
  };

  // Filter messages based on role visibility (Requesters NEVER see internal notes)
  const visibleMessages: TicketMessage[] = (ticket.messages || []).filter((m) => {
    if (!isStaff) return m.message_type === "PublicReply";
    return true;
  });

  const supplierThreadCount = ticket.side_conversations?.length || 0;

  // Build segmented tabs based on role
  const tabsList = isStaff
    ? [
        { id: "public", label: "Public Reply" },
        { id: "internal", label: "Internal Note" },
        { id: "suppliers", label: `Supplier Threads (${supplierThreadCount})` },
        { id: "activity", label: "Activity Timeline" },
      ]
    : [
        { id: "public", label: "Conversation" },
        { id: "activity", label: "Activity Timeline" },
      ];

  return (
    <div className="space-y-6">
      {/* Case Description Card */}
      <Card padding="md">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-caption font-semibold text-content-tertiary uppercase tracking-wider">
            Case Description
          </h2>
          {ticket.intent && (
            <span className="text-[11px] font-medium text-brand-700 dark:text-amber-200 bg-brand-50 dark:bg-amber-950/40 px-2 py-0.5 rounded border border-brand-200 dark:border-amber-800">
              Intent: {ticket.intent}
            </span>
          )}
        </div>
        <div className="text-body text-content-primary leading-relaxed bg-surface-subtle p-3.5 rounded-input border border-border whitespace-pre-wrap">
          {ticket.description}
        </div>
      </Card>

      {/* Main Conversation & Threads Card */}
      <Card padding="none" className="overflow-hidden">
        {/* Header with Segmented Tabs */}
        <div className="p-4 border-b border-border bg-surface flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <MessageSquare className="w-4 h-4 text-brand-600" />
            <h2 className="text-section font-semibold text-content-primary">
              {isStaff ? "Case Communications" : "Agency Support Thread"}
            </h2>
          </div>

          <Tabs
            tabs={tabsList}
            activeTab={activeTab}
            onChange={(tabId) => setActiveTab(tabId)}
            variant="pill"
          />
        </div>

        {/* TAB 1: Supplier Threads (Staff Only) */}
        {activeTab === "suppliers" && isStaff ? (
          <TicketSupplierThreads
            ticket={ticket}
            activeSideThreadId={activeSideThreadId}
            onSelectSideThread={onSelectSideThread}
            onOpenNewThreadModal={onOpenNewThreadModal}
            onPostReply={onPostSupplierReply}
            sendingReply={sendingSupplierReply}
          />
        ) : activeTab === "activity" ? (
          /* TAB 2: Activity Timeline */
          <div className="p-5">
            <TicketActivityTimeline ticket={ticket} />
          </div>
        ) : (
          /* TAB 3 & 4: Public Reply or Internal Note Stream + Composer */
          <div className="p-5 space-y-6">
            {/* Messages Stream - Keyboard accessible scrollable region per WCAG 2.1.1 and axe-core scrollable-region-focusable */}
            <div
              role="region"
              aria-label="Messages stream"
              tabIndex={0}
              className="space-y-4 max-h-[500px] overflow-y-auto pr-1 focus:outline-none focus:ring-1 focus:ring-brand-500/50 rounded-card"
            >
              {visibleMessages.length > 0 ? (
                visibleMessages.map((msg) => {
                  const isInternal = msg.message_type === "InternalNote";
                  const roleInfo = getSenderRole(msg.sender_user_id, msg.sender_name);
                  const isCopied = copiedMessageId === msg.id;

                  return (
                    <div
                      key={msg.id}
                      className={cn(
                        "group relative rounded-card p-4 transition-all duration-200",
                        isInternal
                          ? "bg-yellow-50/80 dark:bg-amber-950/20 border border-amber-300 dark:border-amber-700/60 border-dashed"
                          : "bg-surface border border-border shadow-xs"
                      )}
                    >
                      {/* Bubble Header */}
                      <div className="flex items-center justify-between gap-3 mb-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <Avatar name={msg.sender_name} size="sm" />
                          <span className="text-table font-semibold text-content-primary">
                            {msg.sender_name}
                          </span>
                          <Chip size="sm" variant={roleInfo.variant}>
                            {roleInfo.label}
                          </Chip>
                          {isInternal ? (
                            <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-amber-900 dark:text-amber-200 bg-amber-100/90 dark:bg-amber-900/40 px-2 py-0.5 rounded border border-amber-200 dark:border-amber-700">
                              <Lock className="w-3 h-3 text-amber-700 dark:text-amber-400" />
                              Internal Note
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 text-[11px] font-medium text-brand-700 dark:text-brand-300 bg-brand-50 dark:bg-brand-950/40 px-2 py-0.5 rounded border border-brand-200 dark:border-brand-800">
                              <Globe className="w-3 h-3 text-brand-600 dark:text-brand-400" />
                              Public Reply
                            </span>
                          )}
                        </div>

                        {/* Top-right Actions: Hover Copy / Quote & Timestamp */}
                        <div className="flex items-center gap-2">
                          {/* Hover Action Buttons */}
                          <div className="opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1">
                            <Tooltip content={isCopied ? "Copied" : "Copy message"}>
                              <button
                                type="button"
                                onClick={() => handleCopyMessage(msg)}
                                aria-label="Copy message text"
                                className="p-1 rounded hover:bg-slate-200/60 dark:hover:bg-slate-700/50 text-content-secondary hover:text-content-primary transition-colors cursor-pointer"
                              >
                                {isCopied ? (
                                  <Check className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />
                                ) : (
                                  <Copy className="w-3.5 h-3.5" />
                                )}
                              </button>
                            </Tooltip>
                            <Tooltip content="Quote message in composer">
                              <button
                                type="button"
                                onClick={() => handleQuoteMessage(msg)}
                                aria-label="Quote message"
                                className="p-1 rounded hover:bg-slate-200/60 dark:hover:bg-slate-700/50 text-content-secondary hover:text-content-primary transition-colors cursor-pointer"
                              >
                                <Quote className="w-3.5 h-3.5" />
                              </button>
                            </Tooltip>
                          </div>

                          {/* Relative time with absolute in tooltip */}
                          <Tooltip content={formatDate(msg.created_at)}>
                            <span className="text-caption text-content-tertiary cursor-default">
                              {formatRelativeTime(msg.created_at)}
                            </span>
                          </Tooltip>
                        </div>
                      </div>

                      {/* Message Content */}
                      <div
                        className={cn(
                          "text-body whitespace-pre-wrap leading-relaxed pl-8",
                          isInternal ? "text-amber-950 dark:text-amber-200 font-normal" : "text-content-primary"
                        )}
                      >
                        {msg.content}
                      </div>
                    </div>
                  );
                })
              ) : (
                <EmptyState
                  title="No Messages Recorded"
                  description={
                    isStaff
                      ? "Start the communication by dispatching a public customer reply or logging an internal staff note."
                      : "Send an inquiry or update regarding this reservation below."
                  }
                />
              )}
            </div>

            {/* Composer Box */}
            <form
              onSubmit={handleSubmit}
              className={cn(
                "rounded-card p-4 border transition-all duration-200 space-y-3",
                activeTab === "internal"
                  ? "bg-yellow-50/80 dark:bg-amber-950/20 border-amber-300 dark:border-amber-700"
                  : "bg-surface border-border"
              )}
            >
              <div className="flex items-center justify-between text-caption">
                <div className="flex items-center gap-1.5 font-semibold">
                  {activeTab === "internal" ? (
                    <>
                      <Lock className="w-3.5 h-3.5 text-amber-700 dark:text-amber-400" />
                      <span className="text-amber-900 dark:text-amber-200">Only visible to staff</span>
                    </>
                  ) : (
                    <>
                      <Globe className="w-3.5 h-3.5 text-brand-600 dark:text-brand-400" />
                      <span className="text-content-secondary">Visible to the agency</span>
                    </>
                  )}
                </div>
                <span className="text-[11px] text-content-tertiary">
                  Cmd / Ctrl + Enter to send
                </span>
              </div>

              {/* Auto-growing Textarea */}
              <textarea
                ref={textareaRef}
                value={content}
                onChange={(e) => setContent(e.target.value)}
                onKeyDown={handleKeyDown}
                rows={3}
                placeholder={
                  activeTab === "internal"
                    ? "Record internal note (visible only to staff)..."
                    : "Write a courteous response to the agency partner..."
                }
                className={cn(
                  "w-full px-3.5 py-2.5 rounded-input border text-table text-content-primary placeholder:text-content-tertiary resize-none focus:outline-none focus:ring-2 transition-subtle leading-relaxed",
                  activeTab === "internal"
                    ? "bg-surface/90 border-amber-300 dark:border-amber-700 focus:ring-amber-500"
                    : "bg-surface border-border focus:ring-brand-500"
                )}
              />

              {/* Error State with Retry Button */}
              {messageError && (
                <div className="flex items-center justify-between gap-2 p-2.5 rounded bg-red-50 text-red-700 text-caption border border-red-200 animate-in fade-in">
                  <span>{messageError}</span>
                  {onRetryMessage && (
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      icon={<RotateCcw className="w-3 h-3" />}
                      onClick={onRetryMessage}
                    >
                      Retry
                    </Button>
                  )}
                </div>
              )}

              {/* Actions & Submit */}
              <div className="flex items-center justify-end gap-2 pt-1">
                <Button
                  type="submit"
                  variant={activeTab === "internal" ? "secondary" : "primary"}
                  size="md"
                  loading={sendingMessage}
                  disabled={!content.trim() || sendingMessage}
                  icon={<Send className="w-3.5 h-3.5" />}
                >
                  {activeTab === "internal" ? "Record Internal Note" : "Send Agency Reply"}
                </Button>
              </div>
            </form>
          </div>
        )}
      </Card>
    </div>
  );
}
