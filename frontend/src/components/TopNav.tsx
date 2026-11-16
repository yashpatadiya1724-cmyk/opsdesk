"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useUser } from "@/context/UserContext";
import { DEMO_USERS } from "@/lib/types";
import { ShieldAlert, Compass, BarChart3, Layers } from "lucide-react";

export function TopNav() {
  const { currentUser, setCurrentUser, isLead, isEscalationManager } = useUser();
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-40 bg-white border-b border-slate-200 shadow-sm">
      {/* Top Demo Auth Warning Banner */}
      <div className="bg-amber-50 border-b border-amber-200 px-4 py-1.5 text-xs text-amber-900 flex items-center justify-center gap-2">
        <ShieldAlert className="w-4 h-4 text-amber-700 shrink-0" />
        <span>
          <strong>Demo Auth Mode:</strong> Identity is client-supplied via <code>X-User-Id</code> header (PDF p6 demo specification). In production, replace with signed session/JWT.
        </span>
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        {/* Brand & Nav Links */}
        <div className="flex items-center gap-8">
          <Link href="/" className="flex items-center gap-2 text-slate-900 font-bold text-lg tracking-tight">
            <Compass className="w-6 h-6 text-indigo-600" />
            <span>OpsDesk</span>
            <span className="text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-700 border border-indigo-200">
              B2B Travel Ops
            </span>
          </Link>

          <nav className="flex items-center gap-1">
            <Link
              href="/"
              className={`flex items-center gap-1.5 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                pathname === "/"
                  ? "bg-slate-100 text-slate-900"
                  : "text-slate-600 hover:text-slate-900 hover:bg-slate-50"
              }`}
            >
              <Layers className="w-4 h-4" />
              <span>Operations Queue</span>
            </Link>

            {(isLead || isEscalationManager) && (
              <Link
                href="/insights"
                className={`flex items-center gap-1.5 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                  pathname === "/insights"
                    ? "bg-slate-100 text-slate-900"
                    : "text-slate-600 hover:text-slate-900 hover:bg-slate-50"
                }`}
              >
                <BarChart3 className="w-4 h-4" />
                <span>Insights & Themes</span>
              </Link>
            )}
          </nav>
        </div>

        {/* User / Persona Role Switcher */}
        <div className="flex items-center gap-3">
          <label htmlFor="user-select" className="text-xs font-medium text-slate-500 hidden sm:inline">
            Active Persona:
          </label>
          <select
            id="user-select"
            value={currentUser.id}
            onChange={(e) => {
              const selected = DEMO_USERS.find((u) => u.id === e.target.value);
              if (selected) setCurrentUser(selected);
            }}
            aria-label="Active Persona"
            className="text-xs bg-slate-50 border border-slate-300 text-slate-900 rounded-md px-3 py-1.5 font-medium shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            {DEMO_USERS.map((user) => (
              <option key={user.id} value={user.id}>
                {user.name} ({user.role}) - {user.id}
              </option>
            ))}
          </select>
          <div className="hidden md:flex flex-col text-right">
            <span className="text-xs font-semibold text-slate-800">{currentUser.name}</span>
            <span className="text-[10px] text-slate-500">{currentUser.description}</span>
          </div>
        </div>
      </div>
    </header>
  );
}
