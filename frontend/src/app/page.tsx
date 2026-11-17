"use client";

import React, { useState, useEffect, useCallback, useRef } from "react";
import { useUser } from "@/context/UserContext";
import { useToast } from "@/context/ToastContext";
import { fetchTickets, getExportUrl, computePollDelay, ApiError } from "@/lib/api";
import { TicketSummary } from "@/lib/types";
import { EmptyState, ErrorState } from "@/components/ui";
import {
  QueueHeader,
  QueueKpiStrip,
  QueueTabs,
  QueueFilterBar,
  QueueTable,
  QueueCardsView,
  QueuePagination,
  CreateTicketModal,
  MobileFilterSheet,
  MobileTicketCard,
  DepartureBoardStrip,
  QueuePreviewDrawer,
} from "@/components/queue";

export default function QueuePage() {
  const { currentUser, isStaff, isRequester } = useUser();
  const { showToast } = useToast();

  // Navigation & Data state
  const [activeTab, setActiveTab] = useState<string>("triage");
  const [viewMode, setViewMode] = useState<"table" | "cards">("table");
  const [tickets, setTickets] = useState<TicketSummary[]>([]);
  const [totalCount, setTotalCount] = useState<number>(0);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState<number>(0);
  const pageSize = 50;

  // Filter state
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [debouncedSearch, setDebouncedSearch] = useState<string>("");
  const [intentFilter, setIntentFilter] = useState<string>("");
  const [priorityFilter, setPriorityFilter] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [atRiskOnly, setAtRiskOnly] = useState<boolean>(false);
  const [unassignedOnly, setUnassignedOnly] = useState<boolean>(false);
  const [healthBarFilter, setHealthBarFilter] = useState<string>("ALL");
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState<boolean>(false);

  // Split-View Preview Drawer state
  const [selectedTicketId, setSelectedTicketId] = useState<string | null>(null);
  const [isDrawerOpen, setIsDrawerOpen] = useState<boolean>(false);

  // Export & Modal state
  const [isExporting, setIsExporting] = useState<boolean>(false);
  const [isCreateOpen, setIsCreateOpen] = useState<boolean>(false);

  // Debounce search input
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(searchQuery);
      setPage(0);
    }, 250);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  // Set default tab on role switch
  useEffect(() => {
    if (isRequester) {
      setActiveTab("my_agency");
    } else {
      setActiveTab("triage");
    }
    setPage(0);
  }, [currentUser.id, isRequester]);

  // Resilient polling refs & AbortController (M4 load hardening)
  const abortControllerRef = useRef<AbortController | null>(null);
  const backoffDelayRef = useRef<number>(5000);
  const lastErrorRef = useRef<{ status?: number; retryAfter?: number } | undefined>(undefined);
  const timerIdRef = useRef<NodeJS.Timeout | null>(null);

  // Load Queue Data with signal and background polling support
  const loadData = useCallback(async (isBackgroundPoll = false) => {
    if (!isBackgroundPoll) {
      setLoading(true);
    }
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const viewParam = isRequester
        ? activeTab === "my_agency"
          ? "triage"
          : activeTab
        : activeTab;

      const res = await fetchTickets(
        viewParam,
        pageSize,
        page * pageSize,
        currentUser.id,
        intentFilter || undefined,
        debouncedSearch || undefined,
        priorityFilter || undefined,
        statusFilter || undefined,
        controller.signal
      );

      let fetchedTickets = res.tickets || [];

      // Client-side At Risk / Breached filter toggle
      if (atRiskOnly) {
        fetchedTickets = fetchedTickets.filter(
          (t) => t.sla.status === "AT_RISK" || t.sla.status === "BREACHED"
        );
      }

      // Client-side Unassigned filter toggle
      if (unassignedOnly) {
        fetchedTickets = fetchedTickets.filter((t) => !t.assigned_to);
      }

      setTickets(fetchedTickets);
      setTotalCount(res.total || 0);
      setError(null);
      lastErrorRef.current = undefined;
      backoffDelayRef.current = 5000;
      return true;
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === "AbortError") {
        return false;
      }
      if (err instanceof ApiError) {
        lastErrorRef.current = { status: err.status, retryAfter: err.retryAfter };
      } else {
        lastErrorRef.current = { status: 500 };
      }
      setError(err instanceof Error ? err.message : "Failed to load operations queue");
      return false;
    } finally {
      if (!isBackgroundPoll) {
        setLoading(false);
      }
    }
  }, [
    activeTab,
    page,
    currentUser.id,
    isRequester,
    intentFilter,
    debouncedSearch,
    priorityFilter,
    statusFilter,
    atRiskOnly,
    unassignedOnly,
    pageSize,
  ]);

  // Load on change and resilient poll with jitter, visibilitychange pause, and exponential backoff
  useEffect(() => {
    let isCancelled = false;

    const scheduleNextPoll = (isError = false) => {
      if (timerIdRef.current) {
        clearTimeout(timerIdRef.current);
      }
      if (typeof document !== "undefined" && document.hidden) {
        return;
      }

      const pollCalculation = computePollDelay(
        30000,
        isError ? lastErrorRef.current || { status: 500 } : undefined,
        backoffDelayRef.current
      );
      backoffDelayRef.current = pollCalculation.nextBackoff;
      const delay = pollCalculation.delay;

      timerIdRef.current = setTimeout(async () => {
        if (isCancelled || (typeof document !== "undefined" && document.hidden)) return;
        const success = await loadData(true);
        if (!isCancelled) {
          scheduleNextPoll(!success);
        }
      }, delay);
    };

    loadData(false).then((success) => {
      if (!isCancelled) {
        scheduleNextPoll(!success);
      }
    });

    const handleVisibility = () => {
      if (typeof document !== "undefined" && !document.hidden) {
        loadData(true).then((success) => {
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
  }, [loadData]);

  // Clear filters
  const hasActiveFilters =
    Boolean(searchQuery) ||
    Boolean(intentFilter) ||
    Boolean(priorityFilter) ||
    Boolean(statusFilter) ||
    atRiskOnly ||
    unassignedOnly;

  const handleClearFilters = () => {
    setSearchQuery("");
    setDebouncedSearch("");
    setIntentFilter("");
    setPriorityFilter("");
    setStatusFilter("");
    setAtRiskOnly(false);
    setUnassignedOnly(false);
    setHealthBarFilter("ALL");
    setPage(0);
  };

  // HealthBar filter handler
  const handleHealthBarFilter = (
    type: "ALL" | "OPEN" | "AT_RISK" | "BREACHED" | "UNASSIGNED"
  ) => {
    setHealthBarFilter(type);
    setPage(0);
    if (type === "ALL") {
      setAtRiskOnly(false);
      setUnassignedOnly(false);
      setStatusFilter("");
    } else if (type === "AT_RISK") {
      setAtRiskOnly(true);
      setUnassignedOnly(false);
      setStatusFilter("");
    } else if (type === "BREACHED") {
      setAtRiskOnly(true);
      setUnassignedOnly(false);
      setStatusFilter("");
    } else if (type === "UNASSIGNED") {
      setUnassignedOnly(true);
      setAtRiskOnly(false);
      setStatusFilter("");
    } else if (type === "OPEN") {
      setAtRiskOnly(false);
      setUnassignedOnly(false);
      setStatusFilter("Open");
    }
  };

  // CSV Export Handler
  const handleExportCsv = async () => {
    if (!isStaff) {
      showToast("CSV export is restricted to internal operations staff.", "warning");
      return;
    }
    setIsExporting(true);
    showToast("Preparing download: generating operations export...", "info");
    try {
      const res = await fetch(getExportUrl(), {
        headers: { "X-User-Id": currentUser.id },
      });
      if (!res.ok) {
        throw new Error(`Export failed with HTTP ${res.status}`);
      }
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `opsdesk_export_${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
      showToast("Operations queue export downloaded successfully.", "success");
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : "Export failed. Please try again.", "error");
    } finally {
      setIsExporting(false);
    }
  };

  // Split-View Drawer Selection & Keyboard Navigation (J/K)
  const handleSelectTicket = (ticketId: string) => {
    setSelectedTicketId(ticketId);
    setIsDrawerOpen(true);
  };

  const handleNextTicket = () => {
    if (!selectedTicketId || tickets.length === 0) return;
    const currentIndex = tickets.findIndex((t) => t.id === selectedTicketId);
    if (currentIndex < tickets.length - 1) {
      setSelectedTicketId(tickets[currentIndex + 1].id);
    }
  };

  const handlePrevTicket = () => {
    if (!selectedTicketId || tickets.length === 0) return;
    const currentIndex = tickets.findIndex((t) => t.id === selectedTicketId);
    if (currentIndex > 0) {
      setSelectedTicketId(tickets[currentIndex - 1].id);
    }
  };

  const firstTicketId = tickets.length > 0 ? tickets[0].id : null;

  return (
    <div className="flex flex-col gap-5">
      {/* 1. Header: Operations Queue + "Work next" + "Export CSV" + "New ticket" */}
      <QueueHeader
        totalCount={totalCount}
        firstTicketId={firstTicketId}
        isStaff={isStaff}
        isExporting={isExporting}
        onExport={handleExportCsv}
        onCreateOpen={() => setIsCreateOpen(true)}
      />

      {/* 2. Signature Departure Board Strip (top 5 most urgent check-ins) */}
      <DepartureBoardStrip
        tickets={tickets}
        onSelectTicket={handleSelectTicket}
      />

      {/* 3. HealthBar Strip (replaces old KPI cards with stacked SLA split + CountUp) */}
      <QueueKpiStrip
        tickets={tickets}
        activeFilter={healthBarFilter}
        onFilterClick={handleHealthBarFilter}
      />

      {/* 4. View Tabs & View Mode Toggle (Table | Cards) */}
      <QueueTabs
        activeTab={activeTab}
        onTabChange={(tabId) => {
          setActiveTab(tabId);
          setPage(0);
        }}
        isRequester={isRequester}
        totalCount={totalCount}
        viewMode={viewMode}
        onViewModeChange={setViewMode}
        hasActiveFilters={hasActiveFilters}
        onToggleMobileFilters={() => setMobileFiltersOpen((prev) => !prev)}
      />

      {/* 5. Filter Bar (Desktop) - compact 36px row with removable chips */}
      <QueueFilterBar
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        debouncedSearch={debouncedSearch}
        intentFilter={intentFilter}
        onIntentChange={(val) => {
          setIntentFilter(val);
          setPage(0);
        }}
        priorityFilter={priorityFilter}
        onPriorityChange={(val) => {
          setPriorityFilter(val);
          setPage(0);
        }}
        statusFilter={statusFilter}
        onStatusChange={(val) => {
          setStatusFilter(val);
          setPage(0);
        }}
        atRiskOnly={atRiskOnly}
        onToggleAtRisk={() => {
          setAtRiskOnly((prev) => !prev);
          setPage(0);
        }}
        hasActiveFilters={hasActiveFilters}
        onClearFilters={handleClearFilters}
        className="hidden sm:flex"
      />

      {/* 6. Main Content Area (Table or Cards) */}
      <div className="bg-surface border border-border rounded-card shadow-xs overflow-hidden">
        {error ? (
          <div className="p-6">
            <ErrorState title="Failed to load tickets" message={error} onRetry={loadData} />
          </div>
        ) : !loading && tickets.length === 0 ? (
          <EmptyState
            title="No cases found in this view"
            description={
              hasActiveFilters
                ? "Try adjusting your search keywords or resetting active filters."
                : "Your operations dispatch queue is clear. Good job!"
            }
            actionLabel={hasActiveFilters ? "Clear active filters" : "Create new ticket"}
            onAction={hasActiveFilters ? handleClearFilters : () => setIsCreateOpen(true)}
            className="my-6"
          />
        ) : (
          <>
            {/* Desktop Table View (Fits 1280px with NO horizontal scrollbar) */}
            <div className="hidden md:block">
              {viewMode === "table" ? (
                <QueueTable
                  tickets={tickets}
                  loading={loading}
                  page={page}
                  pageSize={pageSize}
                  isStaff={isStaff}
                  selectedTicketId={selectedTicketId}
                  onSelectTicket={handleSelectTicket}
                  onIntentFilter={(intent) => {
                    setIntentFilter(intent);
                    setPage(0);
                  }}
                  onPriorityFilter={(priority) => {
                    setPriorityFilter(priority);
                    setPage(0);
                  }}
                  onRefresh={loadData}
                />
              ) : (
                <QueueCardsView
                  tickets={tickets}
                  selectedTicketId={selectedTicketId}
                  onSelectTicket={handleSelectTicket}
                  onRefresh={loadData}
                />
              )}
            </div>

            {/* Mobile View (< 768px): Stacked cards with "..." quick actions */}
            <div className="block md:hidden divide-y divide-border">
              {tickets.map((t, idx) => (
                <MobileTicketCard
                  key={t.id}
                  ticket={t}
                  rank={page * pageSize + idx + 1}
                  onRefresh={loadData}
                  onSelectTicket={handleSelectTicket}
                />
              ))}
            </div>

            {/* 7. Pagination Footer */}
            <QueuePagination
              page={page}
              pageSize={pageSize}
              totalCount={totalCount}
              loading={loading}
              onPageChange={setPage}
            />
          </>
        )}
      </div>

      {/* 8. Split View Preview Panel (Drawer loading ticket via fetchTicketDetail) */}
      <QueuePreviewDrawer
        ticketId={selectedTicketId}
        isOpen={isDrawerOpen}
        onClose={() => setIsDrawerOpen(false)}
        onNextTicket={handleNextTicket}
        onPrevTicket={handlePrevTicket}
        onRefresh={loadData}
      />

      {/* 9. Mobile Filter Bottom Sheet */}
      <MobileFilterSheet
        isOpen={mobileFiltersOpen}
        onClose={() => setMobileFiltersOpen(false)}
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        intentFilter={intentFilter}
        onIntentChange={(val) => {
          setIntentFilter(val);
          setPage(0);
        }}
        priorityFilter={priorityFilter}
        onPriorityChange={(val) => {
          setPriorityFilter(val);
          setPage(0);
        }}
        statusFilter={statusFilter}
        onStatusChange={(val) => {
          setStatusFilter(val);
          setPage(0);
        }}
        atRiskOnly={atRiskOnly}
        onToggleAtRisk={() => {
          setAtRiskOnly((prev) => !prev);
          setPage(0);
        }}
        hasActiveFilters={hasActiveFilters}
        onClearFilters={handleClearFilters}
      />

      {/* 10. Create Ticket Modal (640px) */}
      <CreateTicketModal
        isOpen={isCreateOpen}
        onClose={() => setIsCreateOpen(false)}
        onSuccess={loadData}
      />
    </div>
  );
}
