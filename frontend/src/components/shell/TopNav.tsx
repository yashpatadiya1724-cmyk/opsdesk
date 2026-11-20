"use client";

import React, { useState, useRef, useEffect, useCallback } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useUser } from "@/context/UserContext";
import { DEMO_USERS, DemoUser } from "@/lib/types";
import { Avatar } from "@/components/ui/Avatar";
import { RegionTag } from "@/components/ui/Badge";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { Search, ChevronDown, Check, ShieldAlert, X, AlertCircle, RefreshCw, Eye } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Geometric 'O' logo mark with flight-path arc SVG
 */
export function LogoMark({ className = "w-7 h-7" }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-hidden="true"
    >
      {/* Geometric 'O' ring in brand orange */}
      <circle cx="16" cy="16" r="11" stroke="#EA580C" strokeWidth="2.5" />
      {/* Flight path arc crossing the ring */}
      <path
        d="M 6 22 C 12 18, 18 10, 26 6"
        stroke="#FB923C"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
      {/* Departure beacon: amber departure accent */}
      <circle cx="26" cy="6" r="2.5" fill="#FFB020" />
    </svg>
  );
}

const ROLE_PERMISSIONS: Record<string, { label: string; permissions: string[] }> = {
  Lead: {
    label: "Operations Lead (Supervisor)",
    permissions: [
      "Full dispatch & SLA controls",
      "Manual ticket reassignments",
      "Root-cause themes & insights",
      "Global cross-region metrics",
    ],
  },
  Agent: {
    label: "Operations Dispatcher (Agent)",
    permissions: [
      "Active queue triage & actions",
      "Ticket status & priority edits",
      "Supplier threads & booking notes",
      "Internal team handover notes",
    ],
  },
  Requester: {
    label: "External Agency Requester",
    permissions: [
      "Own agency booking requests",
      "Travel timeline milestones",
      "Public replies to dispatchers",
      "Filtered view (no internal scores)",
    ],
  },
  EscalationManager: {
    label: "Escalation Manager",
    permissions: [
      "Breached / At-risk SLA overrides",
      "Supplier dispute arbitrations",
      "Executive escalations log",
      "Root-cause analytics",
    ],
  },
};

export function TopNav() {
  const router = useRouter();
  const { currentUser, setCurrentUser } = useUser();
  const [isBannerDismissed, setIsBannerDismissed] = useState<boolean>(false);

  useEffect(() => {
    if (typeof window !== "undefined") {
      const dismissed = sessionStorage.getItem("opsdesk_demo_banner_dismissed") === "true";
      if (dismissed) {
        setIsBannerDismissed(true);
      }
    }
  }, []);
  const [isDropdownOpen, setIsDropdownOpen] = useState<boolean>(false);
  const [isHoverCardOpen, setIsHoverCardOpen] = useState<boolean>(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const hoverCardTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const [globalSearch, setGlobalSearch] = useState<string>("");
  const [isSearchFocused, setIsSearchFocused] = useState<boolean>(false);

  // Keyboard shortcut: Ctrl+K / Cmd+K focuses global search bar
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        searchInputRef.current?.focus();
        searchInputRef.current?.select();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  // API unreachable monitoring state
  const [isApiDown, setIsApiDown] = useState<boolean>(false);
  const [retryingIn, setRetryingIn] = useState<number>(15);
  const [isRetrying, setIsRetrying] = useState<boolean>(false);

  const checkApiHealth = useCallback(async () => {
    setIsRetrying(true);
    try {
      const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
      const res = await fetch(`${apiBase}/docs`, {
        method: "HEAD",
        mode: "no-cors",
      }).catch(() => null);

      if (res !== null) {
        setIsApiDown(false);
        setRetryingIn(15);
      } else {
        setIsApiDown(true);
      }
    } catch {
      setIsApiDown(true);
    } finally {
      setIsRetrying(false);
    }
  }, []);

  // Periodic API health check
  useEffect(() => {
    checkApiHealth();
    const interval = setInterval(() => {
      checkApiHealth();
    }, 30000);
    return () => clearInterval(interval);
  }, [checkApiHealth]);

  // Countdown timer when API is detected down
  useEffect(() => {
    if (!isApiDown) return;
    const timer = setInterval(() => {
      setRetryingIn((prev) => {
        if (prev <= 1) {
          checkApiHealth();
          return 15;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [isApiDown, checkApiHealth]);

  // Close dropdown on outside click
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setIsDropdownOpen(false);
        setIsHoverCardOpen(false);
      }
    };
    if (isDropdownOpen || isHoverCardOpen) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [isDropdownOpen, isHoverCardOpen]);

  const handleDismissBanner = () => {
    setIsBannerDismissed(true);
    if (typeof window !== "undefined") {
      sessionStorage.setItem("opsdesk_demo_banner_dismissed", "true");
    }
  };

  const handleMouseEnterRole = () => {
    if (hoverCardTimeoutRef.current) clearTimeout(hoverCardTimeoutRef.current);
    setIsHoverCardOpen(true);
  };

  const handleMouseLeaveRole = () => {
    hoverCardTimeoutRef.current = setTimeout(() => {
      setIsHoverCardOpen(false);
    }, 250);
  };

  const currentRoleInfo = ROLE_PERMISSIONS[currentUser.role] || {
    label: currentUser.role,
    permissions: ["Standard operations access"],
  };

  return (
    <header className="sticky top-0 z-40 w-full bg-canvas border-b border-border py-2.5 px-3 sm:px-6 transition-colors select-none shadow-xs">
      {/* 1. Full-width API Unreachable Error State Banner */}
      {isApiDown && (
        <div
          role="alert"
          aria-live="assertive"
          className="w-full -mt-2.5 -mx-3 sm:-mx-6 mb-2 bg-red-600 dark:bg-red-950 border-b border-red-700 dark:border-red-800 px-4 py-2 text-caption text-white dark:text-red-200 transition-subtle shadow-md"
        >
          <div className="max-w-[1440px] mx-auto flex items-center justify-center gap-3 flex-wrap">
            <div className="flex items-center gap-2">
              <AlertCircle className="w-4 h-4 text-white dark:text-red-400 shrink-0" />
              <span className="font-medium text-[12px] sm:text-[13px]">
                Can&apos;t reach the server. Retrying in {retryingIn}s...
              </span>
            </div>
            <button
              type="button"
              onClick={checkApiHealth}
              disabled={isRetrying}
              className="min-h-[32px] px-3 py-1 bg-white/20 hover:bg-white/30 dark:bg-red-900/50 dark:hover:bg-red-900 text-white font-semibold rounded-input cursor-pointer disabled:opacity-50 inline-flex items-center gap-1.5 text-[11px] sm:text-[12px] transition-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
            >
              <RefreshCw className={cn("w-3.5 h-3.5", isRetrying && "animate-spin")} />
              Retry now
            </button>
          </div>
        </div>
      )}

      {/* 2. Slim demo-auth banner (32px, dismissible per session) */}
      {!isBannerDismissed && !isApiDown && (
        <div className="max-w-[1440px] mx-auto mb-2 bg-amber-500/10 dark:bg-amber-500/15 border border-amber-300 dark:border-amber-700/50 rounded-full h-8 px-4 text-[12px] text-amber-800 dark:text-amber-300 flex items-center justify-between transition-subtle font-medium shadow-xs">
          <div className="flex items-center gap-2 mx-auto">
            <ShieldAlert className="w-3.5 h-3.5 text-amber-600 dark:text-amber-400 shrink-0" />
            <span>Demo authentication — identity is client-supplied and not secure.</span>
          </div>
          <button
            type="button"
            onClick={handleDismissBanner}
            aria-label="Dismiss demo authentication banner"
            className="text-amber-700 dark:text-amber-300 hover:text-amber-900 dark:hover:text-amber-100 p-1 rounded-full transition-subtle cursor-pointer shrink-0"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* 3. Floating Pill Top Bar (surface, fully rounded, shadow sm, sticky with solid opaque surface) */}
      <div className="w-full max-w-[1440px] mx-auto h-14 bg-surface border border-border rounded-full shadow-sm px-4 sm:px-6 flex items-center justify-between gap-4 transition-subtle">
        {/* Left: Geometric flight-path 'O' logo mark + 'OpsDesk' */}
        <div className="flex items-center gap-3 shrink-0">
          <Link
            href="/"
            className="flex items-center gap-2.5 text-content-primary hover:opacity-90 transition-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring rounded-full min-h-[40px]"
            aria-label="OpsDesk Home"
          >
            <LogoMark className="w-7 h-7 shrink-0" />
            <div className="flex items-center gap-2">
              <span className="font-heading font-bold text-section tracking-tight text-content-primary">
                OpsDesk
              </span>
              <span className="hidden sm:inline-block text-[10px] font-mono-numbers font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full bg-surface-subtle text-brand-orange-text dark:text-brand-orange border border-border">
                CONTROL TOWER
              </span>
            </div>
          </Link>
        </div>

        {/* Center: Global Search Pill with Ctrl+K hint */}
        <div className="flex-1 max-w-md mx-auto hidden sm:block">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (globalSearch.trim()) {
                router.push(`/?search=${encodeURIComponent(globalSearch.trim())}`);
              }
            }}
            className="relative flex items-center justify-center"
          >
            <Search
              className={cn(
                "w-4 h-4 absolute left-3.5 pointer-events-none transition-colors duration-120",
                isSearchFocused ? "text-brand-orange" : "text-content-tertiary"
              )}
            />
            <input
              ref={searchInputRef}
              type="search"
              value={globalSearch}
              onChange={(e) => setGlobalSearch(e.target.value)}
              onFocus={() => setIsSearchFocused(true)}
              onBlur={() => setIsSearchFocused(false)}
              onKeyDown={(e) => {
                if (e.key === "Escape") {
                  searchInputRef.current?.blur();
                }
              }}
              placeholder="Search tickets, PNR, TBOH... (Ctrl+K)"
              aria-label="Search tickets and bookings (Ctrl+K)"
              className={cn(
                "w-full h-9 pl-9 pr-16 rounded-full bg-surface-subtle text-caption text-content-primary placeholder:text-content-disabled border border-border hover:border-border-strong focus:border-brand-orange focus:bg-surface focus:outline-none transition-all duration-120",
                isSearchFocused && "ring-2 ring-focus-ring shadow-sm max-w-lg"
              )}
            />
            <kbd className="absolute right-3 font-mono-numbers text-[10px] bg-surface text-content-tertiary px-1.5 py-0.5 rounded-full border border-border pointer-events-none select-none">
              Ctrl+K
            </kbd>
          </form>
        </div>

        {/* Right: ThemeToggle + Role Switcher */}
        <div className="flex items-center gap-2.5 shrink-0">
          {/* Light / Dark / System Segmented Control */}
          <ThemeToggle />

          {/* Role Switcher with avatar, name, role, region, and hover card */}
          <div
            className="relative"
            ref={dropdownRef}
            onMouseEnter={handleMouseEnterRole}
            onMouseLeave={handleMouseLeaveRole}
          >
            <button
              type="button"
              onClick={() => setIsDropdownOpen(!isDropdownOpen)}
              aria-haspopup="listbox"
              aria-expanded={isDropdownOpen}
              aria-label={`Active user persona: ${currentUser.name} (${currentUser.role})`}
              className="flex items-center gap-2 p-1 pl-1.5 pr-2.5 rounded-full hover:bg-surface-subtle transition-subtle cursor-pointer border border-transparent hover:border-border min-h-[38px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring"
            >
              <Avatar name={currentUser.name} id={currentUser.id} size="sm" />
              <div className="hidden md:flex flex-col text-left">
                <span className="text-caption font-semibold text-content-primary leading-tight">
                  {currentUser.name}
                </span>
                <div className="flex items-center gap-1.5 text-[11px] text-content-tertiary leading-tight font-mono-numbers">
                  <span>{currentUser.role}</span>
                  {currentUser.region && (
                    <RegionTag region={currentUser.region} className="h-4 px-1.5 text-[10px]" />
                  )}
                </div>
              </div>
              <ChevronDown
                className={cn(
                  "w-3.5 h-3.5 text-content-tertiary shrink-0 transition-transform duration-120 ml-0.5",
                  isDropdownOpen && "rotate-180"
                )}
              />
            </button>

            {/* Persona Hover Card (informative popover when hovering button) */}
            {isHoverCardOpen && !isDropdownOpen && (
              <div className="absolute right-0 top-full mt-2 w-72 bg-surface text-content-primary border border-border-strong rounded-card shadow-lg p-3 z-50 animate-in fade-in zoom-in-95 duration-120 select-none">
                <div className="flex items-center gap-2 pb-2 border-b border-border">
                  <Avatar name={currentUser.name} id={currentUser.id} size="sm" />
                  <div className="min-w-0">
                    <p className="text-caption font-semibold text-content-primary truncate">
                      {currentUser.name}
                    </p>
                    <p className="text-[11px] text-content-secondary font-mono-numbers">
                      {currentRoleInfo.label}
                    </p>
                  </div>
                </div>
                <div className="mt-2 text-[11px]">
                  <p className="font-semibold text-brand-orange-text dark:text-brand-orange mb-1 flex items-center gap-1">
                    <Eye className="w-3.5 h-3.5" /> Capabilities
                  </p>
                  <ul className="text-content-secondary space-y-0.5 pl-4 list-disc text-[10px]">
                    {currentRoleInfo.permissions.map((p, i) => (
                      <li key={i}>{p}</li>
                    ))}
                  </ul>
                </div>
                <div className="mt-2 pt-2 border-t border-border text-[10px] text-content-tertiary text-center">
                  Click to switch persona
                </div>
              </div>
            )}

            {/* Role Switcher Dropdown Popover */}
            {isDropdownOpen && (
              <div
                role="listbox"
                className="absolute right-0 top-full mt-2 w-80 bg-surface text-content-primary border border-border-strong rounded-card shadow-xl py-1.5 z-50 animate-in fade-in zoom-in-95 duration-120 select-none"
              >
                <div className="px-3.5 py-2 border-b border-border bg-surface-subtle rounded-t-card">
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-content-tertiary">
                    Switch Active Persona
                  </p>
                </div>

                <div className="max-h-72 overflow-y-auto py-1">
                  {DEMO_USERS.map((user: DemoUser) => {
                    const isSelected = user.id === currentUser.id;
                    return (
                      <button
                        key={user.id}
                        type="button"
                        role="option"
                        aria-selected={isSelected}
                        onClick={() => {
                          setCurrentUser(user);
                          setIsDropdownOpen(false);
                          setIsHoverCardOpen(false);
                        }}
                        className={cn(
                          "w-full flex items-center justify-between px-3.5 py-2.5 text-left hover:bg-surface-subtle transition-subtle cursor-pointer min-h-[44px]",
                          isSelected && "bg-brand-50/70 dark:bg-orange-950/30"
                        )}
                      >
                        <div className="flex items-center gap-2.5 truncate">
                          <Avatar name={user.name} id={user.id} size="sm" />
                          <div className="truncate">
                            <p className="text-caption font-semibold text-content-primary leading-tight truncate">
                              {user.name}
                            </p>
                            <p className="text-[11px] text-content-secondary leading-tight truncate">
                              {user.description}
                            </p>
                          </div>
                        </div>
                        {isSelected && (
                          <Check className="w-4 h-4 text-brand-orange-text dark:text-brand-orange shrink-0 ml-2" />
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}
