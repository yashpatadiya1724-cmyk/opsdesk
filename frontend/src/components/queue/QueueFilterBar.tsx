"use client";

import React from "react";
import { Search, X, Clock, AlertTriangle } from "lucide-react";
import { Input, Select, Chip } from "@/components/ui";
import { cn } from "@/lib/utils";

export interface QueueFilterBarProps {
  searchQuery: string;
  onSearchChange: (val: string) => void;
  debouncedSearch: string;
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
  className?: string;
}

export function QueueFilterBar({
  searchQuery,
  onSearchChange,
  debouncedSearch,
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
  className,
}: QueueFilterBarProps) {
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
      className={cn(
        "bg-surface border border-border rounded-card p-2.5 shadow-xs flex flex-col gap-2 select-none",
        className
      )}
    >
      {/* Primary compact 36px filter row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-12 gap-2 items-center">
        {/* Search Input: compact 36px */}
        <div className="lg:col-span-4">
          <Input
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="Search TBOH, TCK-ID, keyword..."
            leftIcon={<Search className="w-3.5 h-3.5 text-content-tertiary" />}
            className="h-9 text-[13px]"
            rightIcon={
              searchQuery ? (
                <button
                  type="button"
                  onClick={() => onSearchChange("")}
                  className="cursor-pointer text-content-tertiary hover:text-content-primary p-0.5"
                  aria-label="Clear search"
                >
                  <X className="w-3 h-3" />
                </button>
              ) : undefined
            }
          />
        </div>

        {/* Intent Select: compact 36px */}
        <div className="lg:col-span-3">
          <Select
            aria-label="Filter by intent"
            value={intentFilter}
            onChange={(e) => onIntentChange(e.target.value)}
            options={intentOptions}
            className="h-9 text-[13px]"
          />
        </div>

        {/* Priority Select: compact 36px */}
        <div className="lg:col-span-2">
          <Select
            aria-label="Filter by priority"
            value={priorityFilter}
            onChange={(e) => onPriorityChange(e.target.value)}
            options={priorityOptions}
            className="h-9 text-[13px]"
          />
        </div>

        {/* Status Select: compact 36px */}
        <div className="lg:col-span-2">
          <Select
            aria-label="Filter by status"
            value={statusFilter}
            onChange={(e) => onStatusChange(e.target.value)}
            options={statusOptions}
            className="h-9 text-[13px]"
          />
        </div>

        {/* At Risk / Breached Toggle: compact 36px */}
        <div className="lg:col-span-1 flex justify-end">
          <button
            type="button"
            onClick={onToggleAtRisk}
            className={cn(
              "h-9 px-2 rounded-input text-[12px] font-medium border flex items-center justify-center gap-1.5 transition-subtle cursor-pointer select-none whitespace-nowrap w-full",
              atRiskOnly
                ? "bg-amber-100 text-amber-900 border-amber-300 font-semibold shadow-xs"
                : "bg-surface text-content-secondary border-border hover:border-border-strong hover:bg-surface-subtle"
            )}
            title="Filter by At-Risk or Breached SLAs only"
          >
            {atRiskOnly ? (
              <AlertTriangle className="w-3.5 h-3.5 text-amber-700 shrink-0" />
            ) : (
              <Clock className="w-3.5 h-3.5 text-amber-600 shrink-0" />
            )}
            <span>At risk</span>
          </button>
        </div>
      </div>

      {/* Active filter chips & Clear filters link */}
      {hasActiveFilters && (
        <div className="flex flex-wrap items-center gap-1.5 pt-1.5 border-t border-border/60 text-caption">
          <span className="text-content-tertiary text-[11px] font-medium mr-1">Active:</span>

          {debouncedSearch && (
            <Chip size="sm" variant="brand" className="h-6 text-[11px]">
              Search: &quot;{debouncedSearch}&quot;
              <button
                type="button"
                onClick={() => onSearchChange("")}
                className="ml-1 text-content-tertiary hover:text-content-primary cursor-pointer"
                aria-label="Remove search filter"
              >
                <X className="w-3 h-3" />
              </button>
            </Chip>
          )}

          {intentFilter && (
            <Chip size="sm" variant="default" className="h-6 text-[11px]">
              Intent: {intentFilter}
              <button
                type="button"
                onClick={() => onIntentChange("")}
                className="ml-1 text-content-tertiary hover:text-content-primary cursor-pointer"
                aria-label="Remove intent filter"
              >
                <X className="w-3 h-3" />
              </button>
            </Chip>
          )}

          {priorityFilter && (
            <Chip size="sm" variant="default" className="h-6 text-[11px]">
              Priority: {priorityFilter}
              <button
                type="button"
                onClick={() => onPriorityChange("")}
                className="ml-1 text-content-tertiary hover:text-content-primary cursor-pointer"
                aria-label="Remove priority filter"
              >
                <X className="w-3 h-3" />
              </button>
            </Chip>
          )}

          {statusFilter && (
            <Chip size="sm" variant="default" className="h-6 text-[11px]">
              Status: {statusFilter}
              <button
                type="button"
                onClick={() => onStatusChange("")}
                className="ml-1 text-content-tertiary hover:text-content-primary cursor-pointer"
                aria-label="Remove status filter"
              >
                <X className="w-3 h-3" />
              </button>
            </Chip>
          )}

          {atRiskOnly && (
            <Chip
              size="sm"
              variant="default"
              className="h-6 text-[11px] bg-amber-50 text-amber-900 border-amber-200"
            >
              At risk / Breached
              <button
                type="button"
                onClick={onToggleAtRisk}
                className="ml-1 text-content-tertiary hover:text-content-primary cursor-pointer"
                aria-label="Remove at-risk filter"
              >
                <X className="w-3 h-3" />
              </button>
            </Chip>
          )}

          <button
            type="button"
            onClick={onClearFilters}
            className="text-brand-600 hover:text-brand-700 text-[12px] font-medium ml-auto cursor-pointer underline select-none"
          >
            Clear filters
          </button>
        </div>
      )}
    </div>
  );
}
