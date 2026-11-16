"use client";

import React, { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useUser } from "@/context/UserContext";
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
import { SLABadge, PriorityBadge, StatusBadge } from "@/components/Badge";
import {
  ArrowLeft,
  Clock,
  Send,
  MessageSquare,
  Lock,
  Globe,
  Share2,
  AlertTriangle,
  UserCheck,
  UserX,
  Shuffle,
  ShieldAlert,
  Bug,
  Plus,
  Mail,
} from "lucide-react";

export default function TicketDetailPage() {
  const params = useParams();
  const ticketId = params.id as string;
  const { currentUser, isStaff } = useUser();

  const [ticket, setTicket] = useState<TicketDetail | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Form states
  const [messageType, setMessageType] = useState<"PublicReply" | "InternalNote">("PublicReply");
  const [messageContent, setMessageContent] = useState("");
  const [sendingMessage, setSendingMessage] = useState(false);

  // Side thread reply states
  const [activeSideThread, setActiveSideThread] = useState<string | null>(null);
  const [sideReplyBody, setSideReplyBody] = useState("");
  const [sendingSideReply, setSendingSideReply] = useState(false);

  // Action Modals
  const [transferModalOpen, setTransferModalOpen] = useState(false);
  const [transferAgentId, setTransferAgentId] = useState("USR-102");
  const [transferReason, setTransferReason] = useState("");

  const [escalateModalOpen, setEscalateModalOpen] = useState(false);
  const [escalateReason, setEscalateReason] = useState("");

  const [bugModalOpen, setBugModalOpen] = useState(false);
  const [bugLink, setBugLink] = useState("");

  const [sideThreadModalOpen, setSideThreadModalOpen] = useState(false);
  const [newSupplierName, setNewSupplierName] = useState("");
  const [newSubject, setNewSubject] = useState("");
  const [newRecipients, setNewRecipients] = useState("");
  const [newInitialMsg, setNewInitialMsg] = useState("");

  const loadTicket = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchTicketDetail(ticketId, currentUser.id);
      setTicket(data);
      if (data.side_conversations && data.side_conversations.length > 0) {
        setActiveSideThread(data.side_conversations[0].id);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load ticket details");
    } finally {
      setLoading(false);
    }
  }, [ticketId, currentUser.id]);

  useEffect(() => {
    loadTicket();
  }, [loadTicket]);

  const handlePostMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!messageContent.trim()) return;
    setSendingMessage(true);
    try {
      await postMessage(ticketId, messageType, messageContent, currentUser.id);
      setMessageContent("");
      loadTicket();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Failed to post message");
    } finally {
      setSendingMessage(false);
    }
  };

  const handlePostSideReply = async (sideId: string) => {
    if (!sideReplyBody.trim()) return;
    setSendingSideReply(true);
    try {
      await postSideThreadMessage(ticketId, sideId, sideReplyBody, currentUser.id);
      setSideReplyBody("");
      loadTicket();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Failed to post supplier reply");
    } finally {
      setSendingSideReply(false);
    }
  };

  const handleCreateSideThread = async (e: React.FormEvent) => {
    e.preventDefault();
    const recipientList = newRecipients
      .split(",")
      .map((r) => r.trim())
      .filter(Boolean);
    try {
      await createSideThread(
        ticketId,
        {
          supplier_name: newSupplierName,
          subject: newSubject,
          recipients: recipientList,
          initial_message: newInitialMsg,
        },
        currentUser.id
      );
      setSideThreadModalOpen(false);
      setNewSupplierName("");
      setNewSubject("");
      setNewRecipients("");
      setNewInitialMsg("");
      loadTicket();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Failed to create side conversation");
    }
  };

  const handleStatusChange = async (newStatus: string) => {
    try {
      await updateTicketStatus(ticketId, newStatus, currentUser.id);
      loadTicket();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Invalid status transition");
    }
  };

  const handleTransfer = async () => {
    if (!transferReason.trim()) return;
    try {
      await transferTicket(ticketId, transferAgentId, transferReason, currentUser.id);
      setTransferModalOpen(false);
      setTransferReason("");
      loadTicket();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Transfer failed");
    }
  };

  const handleEscalate = async () => {
    if (!escalateReason.trim()) return;
    try {
      await escalateTicket(ticketId, escalateReason, currentUser.id);
      setEscalateModalOpen(false);
      setEscalateReason("");
      loadTicket();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Escalation failed");
    }
  };

  const handleLinkBug = async () => {
    if (!bugLink.trim()) return;
    try {
      await linkSuggestedBug(ticketId, bugLink, currentUser.id);
      setBugModalOpen(false);
      setBugLink("");
      loadTicket();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Bug link failed");
    }
  };

  const handleUnassign = async () => {
    try {
      await unassignTicket(ticketId, currentUser.id);
      loadTicket();
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : "Unassign failed");
    }
  };

  if (loading) {
    return (
      <div className="max-w-7xl mx-auto px-4 py-16 text-center text-slate-500">
        <Clock className="w-8 h-8 animate-spin mx-auto mb-2 text-indigo-600" />
        <p className="text-sm">Loading ticket {ticketId}...</p>
      </div>
    );
  }

  if (error || !ticket) {
    return (
      <div className="max-w-3xl mx-auto px-4 py-16 text-center">
        <AlertTriangle className="w-10 h-10 text-red-500 mx-auto mb-2" />
        <h2 className="text-lg font-bold text-slate-900">Access Denied or Not Found</h2>
        <p className="text-sm text-slate-600 mt-1">{error || "Unable to display this case."}</p>
        <Link
          href="/"
          className="mt-4 inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold text-white bg-indigo-600 rounded-md shadow-sm"
        >
          <ArrowLeft className="w-4 h-4" /> Return to Queue
        </Link>
      </div>
    );
  }

  const selectedSideThread = ticket.side_conversations?.find((s) => s.id === activeSideThread);

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      {/* Back Link */}
      <div className="mb-4">
        <Link
          href="/"
          className="inline-flex items-center gap-1 text-xs font-semibold text-indigo-600 hover:text-indigo-800"
        >
          <ArrowLeft className="w-3.5 h-3.5" /> Back to Queue
        </Link>
      </div>

      {/* Main Header Card */}
      <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-sm mb-6">
        <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-4">
          <div>
            <div className="flex flex-wrap items-center gap-2 mb-2">
              <span className="font-mono text-xs font-semibold px-2 py-0.5 rounded bg-slate-100 text-slate-800 border border-slate-300">
                {ticket.id}
              </span>
              <span className="font-mono text-xs font-medium px-2 py-0.5 rounded bg-indigo-50 text-indigo-700 border border-indigo-200">
                {ticket.tboh_id}
              </span>
              <PriorityBadge priority={ticket.priority} />
              <StatusBadge status={ticket.status} />
              <SLABadge sla={ticket.sla} />
            </div>
            <h1 className="text-xl font-bold text-slate-900 tracking-tight">{ticket.title}</h1>
            <p className="text-xs text-slate-600 mt-1">Agency: {ticket.agency_id}</p>
          </div>

          {/* Quick Date Pills */}
          <div className="flex flex-col sm:flex-row md:flex-col gap-2 text-xs text-slate-600 text-right">
            <div className="bg-slate-50 border border-slate-200 rounded px-2.5 py-1">
              <span className="font-semibold text-slate-700">Check-in:</span>{" "}
              {new Date(ticket.check_in_date).toLocaleString()}
            </div>
            {ticket.lcd_date && (
              <div className="bg-amber-50 border border-amber-200 rounded px-2.5 py-1 text-amber-900">
                <span className="font-semibold text-amber-800">LCD Deadline:</span>{" "}
                {new Date(ticket.lcd_date).toLocaleString()}
              </div>
            )}
          </div>
        </div>

        {/* Routing Reason Tooltip / Box (Staff Only) */}
        {isStaff && ticket.routing_reason && (
          <div className="mt-4 p-3 bg-slate-50 border border-slate-200 rounded-lg text-xs text-slate-700">
            <span className="font-semibold text-slate-900">Why Routed:</span> {ticket.routing_reason}
          </div>
        )}

        {/* Suggested Bug Link (MVP-5) */}
        {ticket.suggested_bug_link && (
          <div className="mt-3 p-2.5 bg-indigo-50 border border-indigo-200 rounded-lg text-xs text-indigo-900 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Bug className="w-4 h-4 text-indigo-600 shrink-0" />
              <span>
                <strong>Linked Product Defect / Bug:</strong>{" "}
                <a
                  href={ticket.suggested_bug_link}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-mono text-indigo-700 underline"
                >
                  {ticket.suggested_bug_link}
                </a>
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Grid Layout: Left Column (Details & Messages), Right Column (Actions, Side Threads, Linked Cases) */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* LEFT COLUMN: 2 Cols Wide */}
        <div className="lg:col-span-2 space-y-6">
          {/* Description Card */}
          <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-sm">
            <h2 className="text-sm font-bold text-slate-900 mb-2">Case Description</h2>
            <div className="text-xs text-slate-700 whitespace-pre-wrap leading-relaxed bg-slate-50 p-4 rounded border border-slate-100">
              {ticket.description}
            </div>
          </div>

          {/* Conversation History (Messages) */}
          <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-sm">
            <h2 className="text-sm font-bold text-slate-900 mb-4 flex items-center gap-2">
              <MessageSquare className="w-4 h-4 text-indigo-600" />
              <span>Conversation Timeline</span>
            </h2>

            {/* Message List */}
            <div className="space-y-3 mb-6 max-h-96 overflow-y-auto">
              {ticket.messages && ticket.messages.length > 0 ? (
                ticket.messages.map((msg) => (
                  <div
                    key={msg.id}
                    className={`p-3.5 rounded-lg border text-xs ${
                      msg.message_type === "InternalNote"
                        ? "bg-amber-50/60 border-amber-200 text-amber-900"
                        : "bg-slate-50 border-slate-200 text-slate-800"
                    }`}
                  >
                    <div className="flex items-center justify-between mb-1.5">
                      <div className="flex items-center gap-1.5 font-semibold">
                        {msg.message_type === "InternalNote" ? (
                          <>
                            <Lock className="w-3.5 h-3.5 text-amber-700" />
                            <span className="text-amber-800">Internal Staff Note</span>
                          </>
                        ) : (
                          <>
                            <Globe className="w-3.5 h-3.5 text-indigo-600" />
                            <span>Public Customer Reply</span>
                          </>
                        )}
                        <span className="text-slate-500 font-normal">by {msg.sender_name}</span>
                      </div>
                      <span className="text-[10px] text-slate-400">
                        {new Date(msg.created_at).toLocaleString()}
                      </span>
                    </div>
                    <div className="whitespace-pre-wrap leading-relaxed">{msg.content}</div>
                  </div>
                ))
              ) : (
                <p className="text-xs text-slate-400 italic">No messages on this case yet.</p>
              )}
            </div>

            {/* Post Message Form */}
            <form onSubmit={handlePostMessage} className="border-t border-slate-200 pt-4 space-y-3">
              {isStaff && (
                <div className="flex items-center gap-4 text-xs">
                  <label className="flex items-center gap-1.5 cursor-pointer font-medium text-slate-700">
                    <input
                      type="radio"
                      name="msgType"
                      checked={messageType === "PublicReply"}
                      onChange={() => setMessageType("PublicReply")}
                      className="text-indigo-600 focus:ring-indigo-500"
                    />
                    <span>Public Reply (Visible to Agency)</span>
                  </label>
                  <label className="flex items-center gap-1.5 cursor-pointer font-medium text-amber-900">
                    <input
                      type="radio"
                      name="msgType"
                      checked={messageType === "InternalNote"}
                      onChange={() => setMessageType("InternalNote")}
                      className="text-amber-600 focus:ring-amber-500"
                    />
                    <span>Internal Note (Hidden from Agency)</span>
                  </label>
                </div>
              )}

              <textarea
                required
                rows={3}
                value={messageContent}
                onChange={(e) => setMessageContent(e.target.value)}
                placeholder={
                  messageType === "InternalNote"
                    ? "Add internal observation or instructions for operations team..."
                    : "Write reply to travel agency..."
                }
                className="w-full px-3 py-2 border border-slate-300 rounded-md focus:ring-1 focus:ring-indigo-500 text-xs"
              />

              <div className="flex justify-end">
                <button
                  type="submit"
                  disabled={sendingMessage || !messageContent.trim()}
                  className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold text-white bg-indigo-600 rounded-md shadow-sm hover:bg-indigo-700 disabled:opacity-50"
                >
                  <Send className="w-3.5 h-3.5" />
                  {sendingMessage ? "Posting..." : "Post Message"}
                </button>
              </div>
            </form>
          </div>
        </div>

        {/* RIGHT COLUMN: 1 Col Wide (Actions, Linked Tickets, Side Threads) */}
        <div className="space-y-6">
          {/* Operations Actions Card (Staff Only) */}
          {isStaff && (
            <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
              <h2 className="text-sm font-bold text-slate-900 mb-3">Case Operations</h2>
              <div className="space-y-2 text-xs">
                {/* Status Switcher */}
                <div>
                  <label className="block text-slate-600 font-semibold mb-1">Update Status</label>
                  <select
                    value={ticket.status}
                    onChange={(e) => handleStatusChange(e.target.value)}
                    className="w-full px-2.5 py-1.5 bg-slate-50 border border-slate-300 rounded-md text-xs font-medium focus:ring-1 focus:ring-indigo-500"
                  >
                    <option value="New">New</option>
                    <option value="Open">Open</option>
                    <option value="Pending">Pending</option>
                    <option value="Escalated">Escalated</option>
                    <option value="Resolved">Resolved</option>
                    <option value="Closed">Closed</option>
                  </select>
                </div>

                {/* Transfer & Escalate Buttons */}
                <div className="grid grid-cols-2 gap-2 pt-2">
                  <button
                    onClick={() => setTransferModalOpen(true)}
                    className="inline-flex items-center justify-center gap-1.5 px-2.5 py-1.5 border border-slate-300 rounded bg-white text-slate-700 hover:bg-slate-50 font-medium"
                  >
                    <Shuffle className="w-3.5 h-3.5 text-slate-500" /> Transfer
                  </button>
                  <button
                    onClick={() => setEscalateModalOpen(true)}
                    className="inline-flex items-center justify-center gap-1.5 px-2.5 py-1.5 border border-rose-200 rounded bg-rose-50 text-rose-700 hover:bg-rose-100 font-semibold"
                  >
                    <ShieldAlert className="w-3.5 h-3.5 text-rose-600" /> Escalate
                  </button>
                </div>

                {/* Assign / Unassign */}
                <div className="pt-2 flex items-center gap-2">
                  {ticket.assigned_to ? (
                    <button
                      onClick={handleUnassign}
                      className="w-full inline-flex items-center justify-center gap-1.5 px-2.5 py-1.5 border border-slate-300 rounded bg-white text-slate-700 hover:bg-slate-50 font-medium"
                    >
                      <UserX className="w-3.5 h-3.5 text-slate-400" /> Unassign (Triage)
                    </button>
                  ) : (
                    <button
                      onClick={() => assignTicket(ticket.id, currentUser.id, currentUser.id).then(loadTicket)}
                      className="w-full inline-flex items-center justify-center gap-1.5 px-2.5 py-1.5 bg-indigo-50 border border-indigo-200 text-indigo-700 rounded hover:bg-indigo-100 font-semibold"
                    >
                      <UserCheck className="w-3.5 h-3.5 text-indigo-600" /> Claim Ticket
                    </button>
                  )}
                </div>

                {/* Link Bug (MVP-5) */}
                <div className="pt-2">
                  <button
                    onClick={() => setBugModalOpen(true)}
                    className="w-full inline-flex items-center justify-center gap-1.5 px-2.5 py-1.5 border border-slate-300 rounded bg-white text-slate-700 hover:bg-slate-50 font-medium"
                  >
                    <Bug className="w-3.5 h-3.5 text-slate-500" /> Link Product Defect
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Linked Tickets (TBOH Linkage) */}
          <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
            <h2 className="text-sm font-bold text-slate-900 mb-2 flex items-center gap-1.5">
              <Share2 className="w-4 h-4 text-indigo-600" />
              <span>Linked Booking History</span>
            </h2>
            <p className="text-[11px] text-slate-500 mb-3">
              Cases sharing booking reference <strong>{ticket.tboh_id}</strong>
            </p>

            {ticket.linked_ticket_ids && ticket.linked_ticket_ids.length > 0 ? (
              <div className="space-y-2">
                {ticket.linked_ticket_ids.map((id) => (
                  <Link
                    key={id}
                    href={`/ticket/${id}`}
                    className="flex items-center justify-between p-2 rounded bg-slate-50 hover:bg-indigo-50 border border-slate-200 text-xs font-semibold text-indigo-700 transition-colors"
                  >
                    <span>{id}</span>
                    <span className="text-[10px] text-slate-400 font-normal">View Case →</span>
                  </Link>
                ))}
              </div>
            ) : (
              <p className="text-xs text-slate-400 italic">No prior cases found for this TBOH booking.</p>
            )}
          </div>

          {/* Supplier Side Threads (Staff Only) */}
          {isStaff && (
            <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-sm font-bold text-slate-900 flex items-center gap-1.5">
                  <Mail className="w-4 h-4 text-indigo-600" />
                  <span>Supplier Side Threads</span>
                </h2>
                <button
                  onClick={() => setSideThreadModalOpen(true)}
                  className="inline-flex items-center gap-1 text-[11px] font-semibold text-indigo-600 hover:text-indigo-800"
                >
                  <Plus className="w-3 h-3" /> New Thread
                </button>
              </div>

              {ticket.side_conversations && ticket.side_conversations.length > 0 ? (
                <div className="space-y-4">
                  {/* Thread Tabs */}
                  <div className="flex gap-1 overflow-x-auto border-b border-slate-100 pb-2">
                    {ticket.side_conversations.map((sc) => (
                      <button
                        key={sc.id}
                        onClick={() => setActiveSideThread(sc.id)}
                        className={`px-2 py-1 text-[11px] rounded whitespace-nowrap font-medium ${
                          activeSideThread === sc.id
                            ? "bg-indigo-600 text-white"
                            : "bg-slate-100 text-slate-700 hover:bg-slate-200"
                        }`}
                      >
                        {sc.supplier_name}
                      </button>
                    ))}
                  </div>

                  {/* Active Thread Details */}
                  {selectedSideThread && (
                    <div className="text-xs space-y-3">
                      <div>
                        <span className="text-[11px] font-semibold text-slate-500 block">Recipients (Transfer-Proof):</span>
                        <div className="flex flex-wrap gap-1 mt-0.5">
                          {selectedSideThread.recipients.map((email, idx) => (
                            <span key={idx} className="bg-slate-100 text-slate-700 px-1.5 py-0.5 rounded text-[10px] font-mono border border-slate-200">
                              {email}
                            </span>
                          ))}
                        </div>
                      </div>

                      {/* Side Thread Message Stream */}
                      <div className="space-y-2 max-h-48 overflow-y-auto bg-slate-50 p-2.5 rounded border border-slate-200">
                        {selectedSideThread.messages.map((m) => (
                          <div key={m.id} className="text-[11px] bg-white p-2 rounded border border-slate-100">
                            <div className="flex items-center justify-between text-[10px] text-slate-400 mb-1">
                              <span className="font-semibold text-slate-700">{m.sender_email}</span>
                              <span>{new Date(m.created_at).toLocaleTimeString()}</span>
                            </div>
                            <p className="text-slate-800">{m.body}</p>
                          </div>
                        ))}
                      </div>

                      {/* Reply Box */}
                      <div className="flex gap-2">
                        <input
                          type="text"
                          value={sideReplyBody}
                          onChange={(e) => setSideReplyBody(e.target.value)}
                          placeholder="Send reply to supplier..."
                          className="w-full px-2 py-1 border border-slate-300 rounded text-xs focus:ring-1 focus:ring-indigo-500"
                        />
                        <button
                          onClick={() => handlePostSideReply(selectedSideThread.id)}
                          disabled={sendingSideReply || !sideReplyBody.trim()}
                          className="px-2.5 py-1 bg-indigo-600 text-white rounded text-xs font-semibold hover:bg-indigo-700 disabled:opacity-50 shrink-0"
                        >
                          Send
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <p className="text-xs text-slate-400 italic">No supplier side conversations initiated.</p>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Transfer Modal */}
      {transferModalOpen && (
        <div className="fixed inset-0 z-50 bg-slate-900/40 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl max-w-sm w-full p-5 border border-slate-200">
            <h3 className="text-sm font-bold text-slate-900 mb-2">Transfer Case</h3>
            <p className="text-xs text-slate-500 mb-3">
              Assigns this case to another agent. All supplier side-conversation recipients remain preserved.
            </p>
            <div className="space-y-3 text-xs">
              <div>
                <label className="block text-slate-600 font-semibold mb-1">Target Agent</label>
                <select
                  value={transferAgentId}
                  onChange={(e) => setTransferAgentId(e.target.value)}
                  className="w-full px-2 py-1.5 border border-slate-300 rounded"
                >
                  <option value="USR-101">Aisha Khan (MEA)</option>
                  <option value="USR-102">Rahul Verma (APAC)</option>
                  <option value="USR-103">Vikram Joshi (Escalation)</option>
                  <option value="USR-104">Elena Rostova (Lead)</option>
                </select>
              </div>
              <div>
                <label className="block text-slate-600 font-semibold mb-1">Transfer Reason</label>
                <input
                  type="text"
                  required
                  value={transferReason}
                  onChange={(e) => setTransferReason(e.target.value)}
                  placeholder="e.g. Guest language match / desk handoff"
                  className="w-full px-2 py-1.5 border border-slate-300 rounded"
                />
              </div>
              <div className="flex justify-end gap-2 pt-2 border-t">
                <button
                  onClick={() => setTransferModalOpen(false)}
                  className="px-3 py-1.5 border rounded text-slate-600 hover:bg-slate-50"
                >
                  Cancel
                </button>
                <button
                  onClick={handleTransfer}
                  className="px-3 py-1.5 bg-indigo-600 text-white font-semibold rounded hover:bg-indigo-700"
                >
                  Confirm Transfer
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Escalate Modal */}
      {escalateModalOpen && (
        <div className="fixed inset-0 z-50 bg-slate-900/40 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl max-w-sm w-full p-5 border border-slate-200">
            <h3 className="text-sm font-bold text-slate-900 mb-2">Escalate Case to Manager</h3>
            <p className="text-xs text-slate-500 mb-3">
              Reassigns case directly to Escalation Manager (Vikram Joshi) and writes to outbox.
            </p>
            <div className="space-y-3 text-xs">
              <div>
                <label className="block text-slate-600 font-semibold mb-1">Escalation Justification</label>
                <textarea
                  rows={3}
                  required
                  value={escalateReason}
                  onChange={(e) => setEscalateReason(e.target.value)}
                  placeholder="Critical supplier delay, high VIP customer impact..."
                  className="w-full px-2 py-1.5 border border-slate-300 rounded"
                />
              </div>
              <div className="flex justify-end gap-2 pt-2 border-t">
                <button
                  onClick={() => setEscalateModalOpen(false)}
                  className="px-3 py-1.5 border rounded text-slate-600 hover:bg-slate-50"
                >
                  Cancel
                </button>
                <button
                  onClick={handleEscalate}
                  className="px-3 py-1.5 bg-rose-600 text-white font-semibold rounded hover:bg-rose-700"
                >
                  Confirm Escalation
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Link Bug Modal */}
      {bugModalOpen && (
        <div className="fixed inset-0 z-50 bg-slate-900/40 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl max-w-sm w-full p-5 border border-slate-200">
            <h3 className="text-sm font-bold text-slate-900 mb-2">Suggest Product Defect Link</h3>
            <p className="text-xs text-slate-500 mb-3">
              Attach a JIRA ticket, GitHub issue, or internal defect tracking link (MVP-5).
            </p>
            <div className="space-y-3 text-xs">
              <div>
                <label className="block text-slate-600 font-semibold mb-1">Defect Link / Reference</label>
                <input
                  type="text"
                  required
                  value={bugLink}
                  onChange={(e) => setBugLink(e.target.value)}
                  placeholder="https://jira.internal.example.com/browse/OPS-102"
                  className="w-full px-2 py-1.5 border border-slate-300 rounded font-mono"
                />
              </div>
              <div className="flex justify-end gap-2 pt-2 border-t">
                <button
                  onClick={() => setBugModalOpen(false)}
                  className="px-3 py-1.5 border rounded text-slate-600 hover:bg-slate-50"
                >
                  Cancel
                </button>
                <button
                  onClick={handleLinkBug}
                  className="px-3 py-1.5 bg-indigo-600 text-white font-semibold rounded hover:bg-indigo-700"
                >
                  Save Link
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* New Side Thread Modal */}
      {sideThreadModalOpen && (
        <div className="fixed inset-0 z-50 bg-slate-900/40 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl max-w-md w-full p-5 border border-slate-200">
            <h3 className="text-sm font-bold text-slate-900 mb-2">Start Supplier Side Thread</h3>
            <form onSubmit={handleCreateSideThread} className="space-y-3 text-xs">
              <div>
                <label className="block text-slate-600 font-semibold mb-1">Supplier / Vendor Name</label>
                <input
                  type="text"
                  required
                  value={newSupplierName}
                  onChange={(e) => setNewSupplierName(e.target.value)}
                  placeholder="e.g. Kryos Heights Resort"
                  className="w-full px-2 py-1.5 border border-slate-300 rounded"
                />
              </div>
              <div>
                <label className="block text-slate-600 font-semibold mb-1">Subject</label>
                <input
                  type="text"
                  required
                  value={newSubject}
                  onChange={(e) => setNewSubject(e.target.value)}
                  placeholder="Urgent voucher verification"
                  className="w-full px-2 py-1.5 border border-slate-300 rounded"
                />
              </div>
              <div>
                <label className="block text-slate-600 font-semibold mb-1">Recipients (comma separated)</label>
                <input
                  type="text"
                  required
                  value={newRecipients}
                  onChange={(e) => setNewRecipients(e.target.value)}
                  placeholder="reservations@vendor.example.com, frontdesk@vendor.example.com"
                  className="w-full px-2 py-1.5 border border-slate-300 rounded"
                />
              </div>
              <div>
                <label className="block text-slate-600 font-semibold mb-1">Initial Inquiry</label>
                <textarea
                  rows={3}
                  required
                  value={newInitialMsg}
                  onChange={(e) => setNewInitialMsg(e.target.value)}
                  placeholder="Hello, please confirm room availability for guest..."
                  className="w-full px-2 py-1.5 border border-slate-300 rounded"
                />
              </div>
              <div className="flex justify-end gap-2 pt-2 border-t">
                <button
                  type="button"
                  onClick={() => setSideThreadModalOpen(false)}
                  className="px-3 py-1.5 border rounded text-slate-600 hover:bg-slate-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-3 py-1.5 bg-indigo-600 text-white font-semibold rounded hover:bg-indigo-700"
                >
                  Create Side Thread
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
