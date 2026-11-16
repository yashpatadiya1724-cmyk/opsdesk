"use client";

import React, { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { useUser } from "@/context/UserContext";
import { fetchTickets, createTicket, suggestIntent } from "@/lib/api";
import { TicketSummary } from "@/lib/types";
import { SLABadge, PriorityBadge, StatusBadge } from "@/components/Badge";
import {
  RefreshCw,
  PlusCircle,
  Sparkles,
  AlertCircle,
  Inbox,
  ArrowRight,
  ChevronLeft,
  ChevronRight,
  Filter,
} from "lucide-react";

export default function QueuePage() {
  const { currentUser, isStaff, isRequester } = useUser();
  const [activeTab, setActiveTab] = useState<string>("triage");
  const [tickets, setTickets] = useState<TicketSummary[]>([]);
  const [totalCount, setTotalCount] = useState<number>(0);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState<number>(0);
  const pageSize = 15;
  const [intentFilter, setIntentFilter] = useState<string>("");
  const [isCreateOpen, setIsCreateOpen] = useState<boolean>(false);

  // Default tab for requester vs staff
  useEffect(() => {
    if (isRequester) {
      setActiveTab("my_agency");
    } else {
      setActiveTab("triage");
    }
    setPage(0);
  }, [currentUser.id, isRequester]);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const viewParam = isRequester ? (activeTab === "my_agency" ? "triage" : activeTab) : activeTab;
      const res = await fetchTickets(
        viewParam,
        pageSize,
        page * pageSize,
        currentUser.id,
        intentFilter || undefined
      );
      setTickets(res.tickets || []);
      setTotalCount(res.total || 0);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load operations queue");
    } finally {
      setLoading(false);
    }
  }, [activeTab, page, currentUser.id, isRequester, intentFilter]);

  // Load on change and poll every 30s
  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 30000);
    return () => clearInterval(interval);
  }, [loadData]);

  // Create Ticket Form State
  const [createTitle, setCreateTitle] = useState("");
  const [createDesc, setCreateDesc] = useState("");
  const [createTboh, setCreateTboh] = useState("");
  const [createPrio, setCreatePrio] = useState("Medium");
  const [createCheckin, setCreateCheckin] = useState("");
  const [createLcd, setCreateLcd] = useState("");
  const [createIntent, setCreateIntent] = useState("");
  const [createAgency, setCreateAgency] = useState("AGY-001");
  const [suggestingIntent, setSuggestingIntent] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const handleSuggest = async () => {
    if (!createTitle && !createDesc) return;
    setSuggestingIntent(true);
    try {
      const res = await suggestIntent(createTitle, createDesc, currentUser.id);
      if (res && res.intent) {
        setCreateIntent(res.intent);
      }
    } catch (err: unknown) {
      console.error(err);
    } finally {
      setSuggestingIntent(false);
    }
  };

  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreating(true);
    setCreateError(null);
    try {
      await createTicket(
        {
          title: createTitle,
          description: createDesc,
          tboh_id: createTboh,
          priority: createPrio,
          check_in_date: new Date(createCheckin).toISOString(),
          lcd_date: createLcd ? new Date(createLcd).toISOString() : null,
          intent: createIntent || null,
          agency_id: isStaff ? createAgency : undefined,
        },
        currentUser.id
      );
      setIsCreateOpen(false);
      setCreateTitle("");
      setCreateDesc("");
      setCreateTboh("");
      setCreateCheckin("");
      setCreateLcd("");
      setCreateIntent("");
      loadData();
    } catch (err: unknown) {
      setCreateError(err instanceof Error ? err.message : "Failed to create ticket");
    } finally {
      setCreating(false);
    }
  };

  const staffTabs = [
    { id: "triage", label: "Triage (Unassigned)" },
    { id: "my_queue", label: "My Queue" },
    { id: "by_region", label: `By Region (${currentUser.region || "All"})` },
    { id: "by_intent", label: "By Intent" },
    { id: "linked", label: "Linked Cases" },
  ];

  const requesterTabs = [
    { id: "my_agency", label: "All Agency Tickets" },
    { id: "by_intent", label: "By Intent" },
    { id: "linked", label: "Linked Cases" },
  ];

  const availableTabs = isRequester ? requesterTabs : staffTabs;

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      {/* Top Header */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight">
            {isRequester ? `${currentUser.name} Operations Portal` : "Operations Queue & Triage"}
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            {isRequester
              ? "View and create support cases for your agency bookings."
              : "Live B2B travel operations desk with intent-aware SLAs and 2-tier workload routing."}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={loadData}
            disabled={loading}
            className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-medium text-slate-700 bg-white border border-slate-300 rounded-md shadow-sm hover:bg-slate-50 disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin text-indigo-600" : ""}`} />
            Refresh
          </button>
          <button
            onClick={() => setIsCreateOpen(true)}
            className="inline-flex items-center gap-1.5 px-3.5 py-2 text-xs font-semibold text-white bg-indigo-600 rounded-md shadow-sm hover:bg-indigo-700 transition-colors"
          >
            <PlusCircle className="w-4 h-4" />
            New Ticket
          </button>
        </div>
      </div>

      {/* Tabs Bar */}
      <div className="border-b border-slate-200 flex flex-wrap items-center justify-between gap-4 mb-6">
        <nav className="flex space-x-4 overflow-x-auto" aria-label="Tabs">
          {availableTabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => {
                setActiveTab(tab.id);
                setPage(0);
              }}
              className={`py-3 px-2 border-b-2 font-medium text-sm whitespace-nowrap transition-colors ${
                activeTab === tab.id
                  ? "border-indigo-600 text-indigo-600"
                  : "border-transparent text-slate-500 hover:text-slate-700 hover:border-slate-300"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>

        {/* Optional Intent Filter */}
        {activeTab === "by_intent" && (
          <div className="flex items-center gap-2 pb-2">
            <Filter className="w-4 h-4 text-slate-400" />
            <select
              value={intentFilter}
              onChange={(e) => {
                setIntentFilter(e.target.value);
                setPage(0);
              }}
              aria-label="Filter by intent"
              className="text-xs bg-white border border-slate-300 text-slate-700 rounded-md px-2 py-1 focus:ring-1 focus:ring-indigo-500"
            >
              <option value="">All Intents</option>
              <option value="Refund Request">Refund Request</option>
              <option value="Cancellation Inconvenience">Cancellation Inconvenience</option>
              <option value="Emergency Check-in Assist">Emergency Check-in Assist</option>
              <option value="Date Amendment">Date Amendment</option>
              <option value="Bedding / Room Preference">Bedding / Room Preference</option>
              <option value="Voucher Resend">Voucher Resend</option>
              <option value="Unclassified">Unclassified</option>
            </select>
          </div>
        )}
      </div>

      {/* Table Content */}
      <div className="bg-white border border-slate-200 rounded-lg shadow-sm overflow-hidden">
        {error ? (
          <div className="p-8 text-center">
            <AlertCircle className="w-8 h-8 text-red-500 mx-auto mb-2" />
            <p className="text-sm font-semibold text-slate-800">Error Loading Tickets</p>
            <p className="text-xs text-red-600 mt-1">{error}</p>
          </div>
        ) : loading && tickets.length === 0 ? (
          <div className="p-12 text-center text-slate-400">
            <RefreshCw className="w-8 h-8 animate-spin mx-auto mb-2 text-indigo-500" />
            <p className="text-sm">Loading operations queue...</p>
          </div>
        ) : tickets.length === 0 ? (
          <div className="p-12 text-center text-slate-400">
            <Inbox className="w-10 h-10 mx-auto mb-2 stroke-1 text-slate-300" />
            <p className="text-sm font-medium text-slate-600">No tickets found</p>
            <p className="text-xs text-slate-400 mt-1">There are no records in this view matching current filters.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
              <thead className="bg-slate-50 text-slate-700 font-semibold text-xs uppercase tracking-wider">
                <tr>
                  <th className="px-4 py-3">ID & Title</th>
                  <th className="px-4 py-3">TBOH Ref</th>
                  <th className="px-4 py-3">Intent</th>
                  <th className="px-4 py-3">Priority</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">SLA Urgency</th>
                  {isStaff && <th className="px-4 py-3">Assignee</th>}
                  {isStaff && <th className="px-4 py-3 text-right">Queue Score</th>}
                  <th className="px-4 py-3 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-white">
                {tickets.map((ticket) => (
                  <tr key={ticket.id} className="hover:bg-slate-50 transition-colors">
                    <td className="px-4 py-3 font-medium">
                      <Link
                        href={`/ticket/${ticket.id}`}
                        className="text-indigo-600 hover:text-indigo-800 font-semibold hover:underline block"
                      >
                        {ticket.id}
                      </Link>
                      <span className="text-xs text-slate-700 block truncate max-w-xs">{ticket.title}</span>
                    </td>
                    <td className="px-4 py-3">
                      <span className="font-mono text-xs text-slate-600 bg-slate-100 px-1.5 py-0.5 rounded border border-slate-200">
                        {ticket.tboh_id}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-700">
                      {ticket.intent || <span className="text-slate-400 italic">Unclassified</span>}
                    </td>
                    <td className="px-4 py-3">
                      <PriorityBadge priority={ticket.priority} />
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={ticket.status} />
                    </td>
                    <td className="px-4 py-3">
                      <SLABadge sla={ticket.sla} />
                    </td>
                    {isStaff && (
                      <td className="px-4 py-3 text-xs text-slate-600">
                        {ticket.assigned_to ? (
                          <span className="font-medium text-slate-800">{ticket.assigned_to}</span>
                        ) : (
                          <span className="text-amber-700 bg-amber-50 px-1.5 py-0.5 rounded text-[11px] font-semibold">
                            Unassigned
                          </span>
                        )}
                      </td>
                    )}
                    {isStaff && (
                      <td className="px-4 py-3 text-xs font-mono font-semibold text-right text-slate-700">
                        {ticket.queue_score !== null ? ticket.queue_score.toFixed(1) : "—"}
                      </td>
                    )}
                    <td className="px-4 py-3 text-right">
                      <Link
                        href={`/ticket/${ticket.id}`}
                        className="inline-flex items-center gap-1 text-xs font-semibold text-indigo-600 hover:text-indigo-900"
                      >
                        <span>View</span>
                        <ArrowRight className="w-3.5 h-3.5" />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Pagination Footer */}
        <div className="px-4 py-3 bg-slate-50 border-t border-slate-200 flex items-center justify-between text-xs text-slate-600">
          <div>
            Showing <span className="font-semibold">{tickets.length > 0 ? page * pageSize + 1 : 0}</span> to{" "}
            <span className="font-semibold">{Math.min((page + 1) * pageSize, totalCount)}</span> of{" "}
            <span className="font-semibold">{totalCount}</span> cases
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0 || loading}
              className="inline-flex items-center px-2 py-1 border border-slate-300 rounded bg-white text-slate-700 hover:bg-slate-50 disabled:opacity-40"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
              Prev
            </button>
            <span className="px-2 font-medium">Page {page + 1}</span>
            <button
              onClick={() => setPage((p) => p + 1)}
              disabled={(page + 1) * pageSize >= totalCount || loading}
              className="inline-flex items-center px-2 py-1 border border-slate-300 rounded bg-white text-slate-700 hover:bg-slate-50 disabled:opacity-40"
            >
              Next
              <ChevronRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </div>

      {/* Create Ticket Modal */}
      {isCreateOpen && (
        <div className="fixed inset-0 z-50 overflow-y-auto bg-slate-900/40 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl max-w-lg w-full p-6 border border-slate-200">
            <h2 className="text-lg font-bold text-slate-900 mb-1">Create New Operations Case</h2>
            <p className="text-xs text-slate-500 mb-4">
              Enter case details. Shared TBOH codes automatically link prior booking history.
            </p>

            {createError && (
              <div className="mb-4 p-3 rounded bg-red-50 border border-red-200 text-xs text-red-700">
                {createError}
              </div>
            )}

            <form onSubmit={handleCreateSubmit} className="space-y-4 text-xs">
              <div>
                <label className="block font-semibold text-slate-700 mb-1">Ticket Title</label>
                <input
                  type="text"
                  required
                  value={createTitle}
                  onChange={(e) => setCreateTitle(e.target.value)}
                  placeholder="e.g. Flight delay or guest arrival check-in issue"
                  className="w-full px-3 py-2 border border-slate-300 rounded-md focus:ring-1 focus:ring-indigo-500 text-xs"
                />
              </div>

              <div>
                <label className="block font-semibold text-slate-700 mb-1">Description</label>
                <textarea
                  required
                  rows={3}
                  value={createDesc}
                  onChange={(e) => setCreateDesc(e.target.value)}
                  placeholder="Operational context and specific guest request"
                  className="w-full px-3 py-2 border border-slate-300 rounded-md focus:ring-1 focus:ring-indigo-500 text-xs"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">TBOH Booking ID</label>
                  <input
                    type="text"
                    required
                    pattern="^TBOH-[A-Za-z0-9-]{3,30}$"
                    value={createTboh}
                    onChange={(e) => setCreateTboh(e.target.value)}
                    placeholder="TBOH-12345"
                    className="w-full px-3 py-2 border border-slate-300 rounded-md focus:ring-1 focus:ring-indigo-500 text-xs font-mono"
                  />
                </div>
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Priority</label>
                  <select
                    value={createPrio}
                    onChange={(e) => setCreatePrio(e.target.value)}
                    className="w-full px-3 py-2 border border-slate-300 rounded-md focus:ring-1 focus:ring-indigo-500 text-xs"
                  >
                    <option value="Low">Low</option>
                    <option value="Medium">Medium</option>
                    <option value="High">High</option>
                    <option value="Urgent">Urgent</option>
                  </select>
                </div>
              </div>

              {isStaff && (
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Agency ID</label>
                  <select
                    value={createAgency}
                    onChange={(e) => setCreateAgency(e.target.value)}
                    className="w-full px-3 py-2 border border-slate-300 rounded-md focus:ring-1 focus:ring-indigo-500 text-xs"
                  >
                    <option value="AGY-001">Grand Travel Agency (AGY-001)</option>
                    <option value="AGY-002">Apex Journeys (AGY-002)</option>
                    <option value="AGY-003">Horizon Holidays (AGY-003)</option>
                  </select>
                </div>
              )}

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Check-in Date & Time</label>
                  <input
                    type="datetime-local"
                    required
                    value={createCheckin}
                    onChange={(e) => setCreateCheckin(e.target.value)}
                    className="w-full px-3 py-2 border border-slate-300 rounded-md focus:ring-1 focus:ring-indigo-500 text-xs"
                  />
                </div>
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">LCD Date (Optional)</label>
                  <input
                    type="datetime-local"
                    value={createLcd}
                    onChange={(e) => setCreateLcd(e.target.value)}
                    className="w-full px-3 py-2 border border-slate-300 rounded-md focus:ring-1 focus:ring-indigo-500 text-xs"
                  />
                </div>
              </div>

              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="block font-semibold text-slate-700">Intent Category</label>
                  <button
                    type="button"
                    onClick={handleSuggest}
                    disabled={suggestingIntent || (!createTitle && !createDesc)}
                    className="inline-flex items-center gap-1 text-[11px] text-indigo-600 hover:text-indigo-800 font-semibold"
                  >
                    <Sparkles className="w-3 h-3 text-indigo-500" />
                    {suggestingIntent ? "Suggesting..." : "Auto-Suggest"}
                  </button>
                </div>
                <input
                  type="text"
                  value={createIntent}
                  onChange={(e) => setCreateIntent(e.target.value)}
                  placeholder="e.g. Refund Request or Emergency Check-in Assist"
                  className="w-full px-3 py-2 border border-slate-300 rounded-md focus:ring-1 focus:ring-indigo-500 text-xs"
                />
              </div>

              <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-200">
                <button
                  type="button"
                  onClick={() => setIsCreateOpen(false)}
                  className="px-3 py-2 rounded border border-slate-300 text-slate-700 hover:bg-slate-50 font-medium"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creating}
                  className="px-4 py-2 rounded bg-indigo-600 text-white font-semibold hover:bg-indigo-700 disabled:opacity-50"
                >
                  {creating ? "Submitting..." : "Create Case"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
