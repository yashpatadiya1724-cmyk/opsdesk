import React from "react";
import { CheckCircle2, AlertTriangle, AlertOctagon, PauseCircle } from "lucide-react";
import { SLAStatus } from "@/lib/types";

export function SLABadge({ sla }: { sla: SLAStatus }) {
  if (sla.status === "STOPPED") {
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-700 border border-gray-200">
        <PauseCircle className="w-3.5 h-3.5 text-gray-500" />
        {sla.badge}
      </span>
    );
  }

  if (sla.status === "BREACHED") {
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-red-100 text-red-800 border border-red-200">
        <AlertOctagon className="w-3.5 h-3.5 text-red-600" />
        {sla.badge}
      </span>
    );
  }

  if (sla.status === "AT_RISK") {
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-amber-100 text-amber-900 border border-amber-300">
        <AlertTriangle className="w-3.5 h-3.5 text-amber-600" />
        {sla.badge}
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-50 text-emerald-800 border border-emerald-200">
      <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
      {sla.badge}
    </span>
  );
}

export function PriorityBadge({ priority }: { priority: string }) {
  const styles: Record<string, string> = {
    Urgent: "bg-red-50 text-red-700 border-red-200 font-semibold",
    High: "bg-amber-50 text-amber-800 border-amber-200 font-medium",
    Medium: "bg-blue-50 text-blue-700 border-blue-200 font-medium",
    Low: "bg-slate-50 text-slate-600 border-slate-200 font-normal",
  };
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs border ${styles[priority] || "bg-gray-50 text-gray-700"}`}>
      {priority}
    </span>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    New: "bg-indigo-50 text-indigo-700 border-indigo-200",
    Open: "bg-sky-50 text-sky-700 border-sky-200",
    Pending: "bg-amber-50 text-amber-700 border-amber-200",
    Escalated: "bg-rose-50 text-rose-700 border-rose-300 font-semibold",
    Resolved: "bg-emerald-50 text-emerald-700 border-emerald-200",
    Closed: "bg-slate-100 text-slate-600 border-slate-200",
  };
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium border ${styles[status] || "bg-gray-100 text-gray-700"}`}>
      {status}
    </span>
  );
}
