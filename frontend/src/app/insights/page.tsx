"use client";

import React, { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { useUser } from "@/context/UserContext";
import { fetchInsightsThemes, getExportUrl } from "@/lib/api";
import { InsightsResponse } from "@/lib/types";
import {
  BarChart3,
  Download,
  ShieldAlert,
  ArrowRight,
  TrendingUp,
  FileSpreadsheet,
  AlertCircle,
  Clock,
  RefreshCw,
} from "lucide-react";

export default function InsightsPage() {
  const { currentUser, isLead, isEscalationManager } = useUser();
  const [data, setData] = useState<InsightsResponse | null>(null);
  const [days, setDays] = useState<number>(7);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [isExporting, setIsExporting] = useState<boolean>(false);

  const loadData = useCallback(async () => {
    if (!isLead && !isEscalationManager) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await fetchInsightsThemes(days, currentUser.id);
      setData(res);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to load insights";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [days, currentUser.id, isLead, isEscalationManager]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Handle CSV export with X-User-Id header
  const handleExportCsv = async () => {
    if (!isLead) {
      alert("CSV export is restricted to Operations Team Lead (RBAC rule). Current role: " + currentUser.role);
      return;
    }
    setIsExporting(true);
    try {
      const res = await fetch(getExportUrl(), {
        headers: {
          "X-User-Id": currentUser.id,
        },
      });
      if (!res.ok) {
        const errJson = await res.json().catch(() => null);
        throw new Error(errJson?.detail || `Export failed with status ${res.status}`);
      }
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `opsdesk_tickets_export_${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Export failed";
      alert("Error exporting CSV: " + msg);
    } finally {
      setIsExporting(false);
    }
  };

  // RBAC Access Guard for Non-staff/Non-leadership
  if (!isLead && !isEscalationManager) {
    return (
      <div className="bg-white rounded-lg border border-slate-200 p-8 text-center max-w-lg mx-auto mt-12 shadow-sm">
        <ShieldAlert className="w-12 h-12 text-amber-500 mx-auto mb-4" />
        <h2 className="text-lg font-bold text-slate-900 mb-2">Restricted Access (RBAC)</h2>
        <p className="text-sm text-slate-600 mb-6">
          The <strong>Operational Insights & Trends</strong> dashboard is restricted to <strong>Lead</strong> and{" "}
          <strong>EscalationManager</strong> roles.
        </p>
        <p className="text-xs text-slate-500 mb-6">
          Current identity: <code className="bg-slate-100 px-1 py-0.5 rounded">{currentUser.name} ({currentUser.role})</code>
        </p>
        <Link
          href="/"
          className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-md text-sm font-medium hover:bg-indigo-700 transition-colors"
        >
          Return to Operations Queue
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-4 border-b border-slate-200">
        <div>
          <div className="flex items-center gap-2">
            <BarChart3 className="w-6 h-6 text-indigo-600" />
            <h1 className="text-2xl font-bold text-slate-900">Operational Insights & Trends</h1>
          </div>
          <p className="text-sm text-slate-500 mt-1">
            MVP-5 Top recurring themes, volume breakdown, and sample ticket tracking (Travel Ops Analytics).
          </p>
        </div>

        <div className="flex items-center gap-3">
          {/* Period selector */}
          <div className="flex items-center gap-1.5 bg-white border border-slate-200 rounded-lg p-1 text-xs">
            <Clock className="w-3.5 h-3.5 text-slate-400 ml-1.5" />
            <span className="text-slate-500 font-medium">Window:</span>
            {[7, 14, 30, 90].map((d) => (
              <button
                key={d}
                onClick={() => setDays(d)}
                className={`px-2.5 py-1 rounded font-medium transition-colors ${
                  days === d
                    ? "bg-indigo-50 text-indigo-700 font-semibold"
                    : "text-slate-600 hover:text-slate-900 hover:bg-slate-50"
                }`}
              >
                {d}d
              </button>
            ))}
          </div>

          {/* Refresh */}
          <button
            onClick={loadData}
            disabled={loading}
            className="p-2 bg-white border border-slate-200 text-slate-600 hover:text-slate-900 rounded-lg text-sm hover:bg-slate-50 transition-colors"
            title="Refresh analytics"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
          </button>

          {/* Export CSV Button (MVP-6) */}
          <button
            onClick={handleExportCsv}
            disabled={isExporting || !isLead}
            title={isLead ? "Stream full dataset as CSV (Lead only)" : "Export CSV is restricted to Operations Lead"}
            className={`inline-flex items-center gap-2 px-3.5 py-2 rounded-lg text-sm font-semibold transition-colors shadow-sm ${
              isLead
                ? "bg-slate-900 text-white hover:bg-slate-800 disabled:opacity-50"
                : "bg-slate-200 text-slate-400 cursor-not-allowed"
            }`}
          >
            <Download className="w-4 h-4" />
            <span>{isExporting ? "Exporting CSV..." : "Export CSV (MVP-6)"}</span>
          </button>
        </div>
      </div>

      {!isLead && isEscalationManager && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg px-4 py-2.5 text-xs text-blue-900 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-blue-700 shrink-0" />
            <span>
              <strong>Escalation Manager View:</strong> You have full visibility into operational themes and trends. Note: Uncapped CSV Export requires <strong>Lead</strong> role.
            </span>
          </div>
        </div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-800 flex items-start gap-2">
          <AlertCircle className="w-5 h-5 text-red-600 shrink-0 mt-0.5" />
          <div>
            <strong className="font-semibold">Error loading analytics:</strong> {error}
          </div>
        </div>
      )}

      {/* Metrics Row */}
      {data && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="bg-white rounded-lg border border-slate-200 p-5 shadow-sm">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                Total Volume Analyzed
              </span>
              <FileSpreadsheet className="w-4 h-4 text-slate-400" />
            </div>
            <div className="text-3xl font-extrabold text-slate-900 mt-2">
              {data.total_tagged_records.toLocaleString()}
            </div>
            <div className="text-xs text-slate-500 mt-1">
              Tickets created in the last {data.time_window_days} days
            </div>
          </div>

          <div className="bg-white rounded-lg border border-slate-200 p-5 shadow-sm">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                Top Recurring Driver
              </span>
              <TrendingUp className="w-4 h-4 text-indigo-600" />
            </div>
            <div className="text-xl font-bold text-slate-900 mt-2 truncate">
              {data.themes.length > 0 ? data.themes[0].theme : "None"}
            </div>
            <div className="text-xs text-slate-500 mt-1">
              {data.themes.length > 0 ? `${data.themes[0].percentage}% of recent inbound tickets` : "-"}
            </div>
          </div>

          <div className="bg-white rounded-lg border border-slate-200 p-5 shadow-sm">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                Active Intent Categories
              </span>
              <BarChart3 className="w-4 h-4 text-slate-400" />
            </div>
            <div className="text-3xl font-extrabold text-slate-900 mt-2">
              {data.themes.length}
            </div>
            <div className="text-xs text-slate-500 mt-1">
              Tracked operational taxonomies
            </div>
          </div>
        </div>
      )}

      {/* Top Themes Breakdown */}
      <div className="bg-white rounded-lg border border-slate-200 shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-200 bg-slate-50/50 flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold text-slate-900">Intent Breakdown & Sample Verification</h2>
            <p className="text-xs text-slate-500">
              Aggregated by rule classifier and audit metadata. Click sample IDs to inspect operational context.
            </p>
          </div>
        </div>

        {loading ? (
          <div className="p-12 text-center text-slate-400">
            <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2 text-indigo-600" />
            <p className="text-sm">Calculating operational theme distributions...</p>
          </div>
        ) : !data || data.themes.length === 0 ? (
          <div className="p-12 text-center text-slate-500 text-sm">
            No tickets found in the selected {days}-day time window.
          </div>
        ) : (
          <div className="divide-y divide-slate-100">
            {data.themes.map((t, idx) => (
              <div key={t.theme} className="p-6 hover:bg-slate-50/40 transition-colors">
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 mb-2">
                  <div className="flex items-center gap-3">
                    <span className="w-6 h-6 rounded-full bg-slate-100 text-slate-600 text-xs font-bold flex items-center justify-center shrink-0">
                      {idx + 1}
                    </span>
                    <h3 className="text-sm font-semibold text-slate-900">{t.theme}</h3>
                  </div>
                  <div className="flex items-center gap-3 text-sm">
                    <span className="font-bold text-slate-900">{t.count.toLocaleString()} tickets</span>
                    <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-indigo-50 text-indigo-700 border border-indigo-200">
                      {t.percentage}%
                    </span>
                  </div>
                </div>

                {/* Progress bar */}
                <div className="w-full bg-slate-100 rounded-full h-2 mb-3 overflow-hidden">
                  <div
                    className={`h-2 rounded-full transition-all duration-500 ${
                      t.theme === "Emergency Check-in Assist"
                        ? "bg-red-500"
                        : t.theme === "Cancellation & Refund"
                        ? "bg-amber-500"
                        : t.theme === "Unclassified"
                        ? "bg-slate-400"
                        : "bg-indigo-600"
                    }`}
                    style={{ width: `${Math.min(100, Math.max(2, t.percentage))}%` }}
                  />
                </div>

                {/* Sample Tickets */}
                {t.sample_ticket_ids && t.sample_ticket_ids.length > 0 && (
                  <div className="flex items-center gap-2 text-xs text-slate-500 pt-1">
                    <span className="font-medium text-slate-600">Sample Tickets:</span>
                    <div className="flex items-center gap-2 flex-wrap">
                      {t.sample_ticket_ids.map((ticketId) => (
                        <Link
                          key={ticketId}
                          href={`/ticket/${ticketId}`}
                          className="inline-flex items-center gap-1 font-mono text-xs px-2 py-0.5 rounded bg-slate-100 text-indigo-700 hover:bg-indigo-50 border border-slate-200 transition-colors"
                        >
                          <span>{ticketId}</span>
                          <ArrowRight className="w-3 h-3 text-indigo-500" />
                        </Link>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Audit & Compliance Footnote */}
      <div className="bg-slate-100 rounded-lg p-4 text-xs text-slate-600 border border-slate-200 flex items-start gap-3">
        <ShieldAlert className="w-4 h-4 text-slate-500 shrink-0 mt-0.5" />
        <div className="space-y-1">
          <p className="font-semibold text-slate-800">
            Governance & Data Integrity (Zendesk-Darwin box Automation Architecture)
          </p>
          <p>
            Themes are derived from deterministic rule-based classifications and validated against the 5,000-ticket operational pool.
            Export functionality streams memory-safe CSV chunks using SQL batch cursors without memory buffering.
          </p>
        </div>
      </div>
    </div>
  );
}
