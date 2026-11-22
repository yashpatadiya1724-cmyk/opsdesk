"use client";

import React, { useEffect } from "react";
import { X, Search, Clock, AlertTriangle, RotateCcw } from "lucide-react";
import { Input, Select, Button } from "@/components/ui";
import { cn } from "@/lib/utils";

export interface MobileFilterSheetProps {
  isOpen: boolean;
  onClose: () => void;
  searchQuery: string;
  onSearchChange: (val: string) => void;
  intentFilter: string;
  onIntentChange: (val: string) => void;
  priorityFilter: string;
  onPriorityChange: (val: string) => void;
  statusFilter: string;
  onStatusChange: (val: string) => void;
  atRiskOnly: boolean;
  onToggleAtRisk: () => void;
  hasActiveFilters: boolean;
  onClearFilters: () => void;
}

export function MobileFilterSheet({
  isOpen,
  onClose,
  searchQuery,
  onSearchChange,
  intentFilter,
  onIntentChange,
  priorityFilter,
  onPriorityChange,
  statusFilter,
  onStatusChange,
  atRiskOnly,
  onToggleAtRisk,
  hasActiveFilters,
  onClearFilters,
}: MobileFilterSheetProps) {
  // Lock body scroll when open
  useEffect(() => {
    if (!isOpen) return;
    const origOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = origOverflow;
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const intentOptions = [
    { value: "", label: "All Intents" },
    { value: "Refund Request", label: "Refund Request" },
    { value: "Cancellation Inconvenience", label: "Cancellation Inconvenience" },
    { value: "Date Amendment", label: "Date Amendment" },
    { value: "Bedding / Room Preference", label: "Bedding / Room Preference" },
    { value: "Voucher Resend", label: "Voucher Resend" },
    { value: "Emergency Check-in Assist", label: "Emergency Check-in Assist" },
    { value: "Unclassified", label: "Unclassified" },
  ];

  const priorityOptions = [
    { value: "", label: "All Priorities" },
    { value: "Urgent", label: "Urgent" },
    { value: "High", label: "High" },
    { value: "Medium", label: "Medium" },
    { value: "Low", label: "Low" },
  ];

  const statusOptions = [
    { value: "", label: "All Statuses" },
    { value: "New", label: "New" },
    { value: "Open", label: "Open" },
    { value: "Pending", label: "Pending" },
    { value: "Escalated", label: "Escalated" },
    { value: "Resolved", label: "Resolved" },
    { value: "Closed", label: "Closed" },
  ];

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Queue filter sheet"
      className="fixed inset-0 z-50 flex flex-col justify-end sm:hidden"
    >
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-slate-950/40 backdrop-blur-xs transition-opacity animate-in fade-in"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Bottom Sheet Card */}
      <div className="relative z-10 bg-surface rounded-t-[18px] border-t border-border shadow-2xl p-5 flex flex-col gap-4 max-h-[85vh] overflow-y-auto animate-in slide-in-from-bottom duration-200">
        {/* Drag handle */}
        <div className="w-10 h-1 bg-border rounded-full mx-auto -mt-2 mb-1" />

        {/* Sheet Header */}
        <div className="flex items-center justify-between pb-2 border-b border-border">
          <div className="flex items-center gap-2">
            <h3 className="text-section font-semibold text-content-primary">
              Filter Queue
            </h3>
            {hasActiveFilters && (
              <span className="text-[11px] font-medium text-brand-700 bg-brand-50 px-2 py-0.5 rounded-full">
                Active
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 text-content-tertiary hover:text-content-primary rounded-input"
            aria-label="Close filters"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Search */}
        <div>
          <label htmlFor="mobile-filter-search" className="text-caption font-medium text-content-secondary mb-1 block">
            Search
          </label>
          <Input
            id="mobile-filter-search"
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="Search TBOH, TCK-ID, keyword..."
            leftIcon={<Search className="w-4 h-4 text-content-tertiary" />}
            rightIcon={
              searchQuery ? (
                <button
                  type="button"
                  onClick={() => onSearchChange("")}
                  className="cursor-pointer text-content-tertiary hover:text-content-primary"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              ) : undefined
            }
          />
        </div>

        {/* Intent */}
        <div>
          <label htmlFor="mobile-filter-intent" className="text-caption font-medium text-content-secondary mb-1 block">
            Intent Category
          </label>
          <Select
            id="mobile-filter-intent"
            value={intentFilter}
            onChange={(e) => onIntentChange(e.target.value)}
            options={intentOptions}
          />
        </div>

        {/* Priority */}
        <div>
          <label htmlFor="mobile-filter-priority" className="text-caption font-medium text-content-secondary mb-1 block">
            Priority
          </label>
          <Select
            id="mobile-filter-priority"
            value={priorityFilter}
            onChange={(e) => onPriorityChange(e.target.value)}
            options={priorityOptions}
          />
        </div>

        {/* Status */}
        <div>
          <label htmlFor="mobile-filter-status" className="text-caption font-medium text-content-secondary mb-1 block">
            Status
          </label>
          <Select
            id="mobile-filter-status"
            value={statusFilter}
            onChange={(e) => onStatusChange(e.target.value)}
            options={statusOptions}
          />
        </div>

        {/* At Risk Only Toggle */}
        <button
          type="button"
          onClick={onToggleAtRisk}
          className={cn(
            "h-10 px-3 rounded-input text-caption font-medium border flex items-center justify-between transition-subtle w-full cursor-pointer select-none",
            atRiskOnly
              ? "bg-amber-100 text-amber-900 border-amber-300 font-semibold"
              : "bg-surface text-content-secondary border-border hover:border-border-strong"
          )}
        >
          <div className="flex items-center gap-2">
            {atRiskOnly ? (
              <AlertTriangle className="w-4 h-4 text-amber-700" />
            ) : (
              <Clock className="w-4 h-4 text-amber-600" />
            )}
            <span>At risk / Breached only</span>
          </div>
          <span className="text-[11px] font-mono-numbers">
            {atRiskOnly ? "ON" : "OFF"}
          </span>
        </button>

        {/* Actions Footer */}
        <div className="flex items-center gap-3 pt-3 border-t border-border mt-1">
          {hasActiveFilters && (
            <Button
              variant="secondary"
              size="md"
              icon={<RotateCcw className="w-3.5 h-3.5" />}
              onClick={onClearFilters}
              className="flex-1"
            >
              Reset
            </Button>
          )}
          <Button
            variant="primary"
            size="md"
            onClick={onClose}
            className="flex-1"
          >
            Apply Filters
          </Button>
        </div>
      </div>
    </div>
  );
}
