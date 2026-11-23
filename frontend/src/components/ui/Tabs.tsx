"use client";

import React, { useRef, useState, useEffect } from "react";
import { cn } from "@/lib/utils";

export interface TabItem {
  id: string;
  label: string;
  count?: number;
  icon?: React.ReactNode;
}

export interface TabsProps {
  tabs: TabItem[];
  activeTab: string;
  onChange: (tabId: string) => void;
  className?: string;
  ariaLabel?: string;
  variant?: "underline" | "pill";
}

/**
 * SegmentedTabs: Pill language, with sliding indicator that glides between items.
 * Light mode: navy indicator with white text.
 * Dark mode: orange indicator with navy text.
 */
export function SegmentedTabs({
  tabs,
  activeTab,
  onChange,
  className,
  ariaLabel = "Segmented tabs",
}: Omit<TabsProps, "variant">) {
  const containerRef = useRef<HTMLDivElement>(null);
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const [indicator, setIndicator] = useState<{ left: number; width: number; height: number }>({
    left: 0,
    width: 0,
    height: 0,
  });

  useEffect(() => {
    const activeIndex = tabs.findIndex((t) => t.id === activeTab);
    const activeEl = tabRefs.current[activeIndex];
    if (activeEl && containerRef.current) {
      setIndicator({
        left: activeEl.offsetLeft,
        width: activeEl.offsetWidth,
        height: activeEl.offsetHeight,
      });
    }
  }, [activeTab, tabs]);

  const handleKeyDown = (e: React.KeyboardEvent, index: number) => {
    if (e.key === "ArrowRight") {
      e.preventDefault();
      const nextIndex = (index + 1) % tabs.length;
      onChange(tabs[nextIndex].id);
      tabRefs.current[nextIndex]?.focus();
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      const prevIndex = (index - 1 + tabs.length) % tabs.length;
      onChange(tabs[prevIndex].id);
      tabRefs.current[prevIndex]?.focus();
    }
  };

  return (
    <div
      ref={containerRef}
      role="tablist"
      aria-label={ariaLabel}
      className={cn(
        "relative flex items-center p-1 bg-surface-subtle border border-border rounded-full w-fit overflow-x-auto max-w-full select-none",
        className
      )}
    >
      {/* Gliding sliding indicator pill */}
      {indicator.width > 0 && (
        <span
          className="absolute rounded-full transition-all duration-200 ease-out pointer-events-none bg-[#0F172A] text-white dark:bg-[#F97316] dark:text-[#0F172A] shadow-xs"
          style={{
            left: `${indicator.left}px`,
            width: `${indicator.width}px`,
            height: `${indicator.height}px`,
          }}
          aria-hidden="true"
        />
      )}

      {tabs.map((tab, idx) => {
        const isActive = tab.id === activeTab;
        return (
          <button
            key={tab.id}
            ref={(el) => {
              tabRefs.current[idx] = el;
            }}
            role="tab"
            aria-selected={isActive}
            tabIndex={isActive ? 0 : -1}
            onClick={() => onChange(tab.id)}
            onKeyDown={(e) => handleKeyDown(e, idx)}
            className={cn(
              "relative z-10 flex items-center gap-2 px-3.5 py-1.5 rounded-full text-caption font-medium transition-colors duration-150 shrink-0 cursor-pointer select-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring",
              isActive
                ? "text-white dark:text-[#0F172A] font-semibold"
                : "text-content-secondary hover:text-content-primary"
            )}
          >
            {tab.icon && <span className="w-4 h-4 shrink-0">{tab.icon}</span>}
            <span>{tab.label}</span>
            {tab.count !== undefined && (
              <span
                className={cn(
                  "font-mono-numbers px-1.5 py-0.5 rounded-full text-[11px] leading-none shrink-0 transition-colors",
                  isActive
                    ? "bg-black/25 text-white dark:bg-black/40 dark:text-white font-bold"
                    : "bg-surface text-content-tertiary"
                )}
              >
                {tab.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/**
 * Tabs: Underline variant with gliding orange underline indicator.
 * Also supports variant="pill" delegating to SegmentedTabs.
 */
export function Tabs({
  tabs,
  activeTab,
  onChange,
  className,
  ariaLabel = "Navigation tabs",
  variant = "underline",
}: TabsProps) {
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const [indicator, setIndicator] = useState<{ left: number; width: number }>({ left: 0, width: 0 });

  useEffect(() => {
    if (variant !== "underline") return;
    const activeIndex = tabs.findIndex((t) => t.id === activeTab);
    const activeEl = tabRefs.current[activeIndex];
    if (activeEl) {
      setIndicator({
        left: activeEl.offsetLeft,
        width: activeEl.offsetWidth,
      });
    }
  }, [activeTab, tabs, variant]);

  const handleKeyDown = (e: React.KeyboardEvent, index: number) => {
    if (e.key === "ArrowRight") {
      e.preventDefault();
      const nextIndex = (index + 1) % tabs.length;
      onChange(tabs[nextIndex].id);
      tabRefs.current[nextIndex]?.focus();
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      const prevIndex = (index - 1 + tabs.length) % tabs.length;
      onChange(tabs[prevIndex].id);
      tabRefs.current[prevIndex]?.focus();
    }
  };

  if (variant === "pill") {
    return (
      <SegmentedTabs
        tabs={tabs}
        activeTab={activeTab}
        onChange={onChange}
        className={className}
        ariaLabel={ariaLabel}
      />
    );
  }

  // Underline style with gliding active indicator
  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className={cn(
        "relative flex items-center gap-6 border-b border-border w-full overflow-x-auto select-none",
        className
      )}
    >
      {tabs.map((tab, idx) => {
        const isActive = tab.id === activeTab;
        return (
          <button
            key={tab.id}
            ref={(el) => {
              tabRefs.current[idx] = el;
            }}
            role="tab"
            aria-selected={isActive}
            tabIndex={isActive ? 0 : -1}
            onClick={() => onChange(tab.id)}
            onKeyDown={(e) => handleKeyDown(e, idx)}
            className={cn(
              "flex items-center gap-2 pb-2.5 pt-1 text-table font-medium transition-colors shrink-0 cursor-pointer border-b-2 -mb-px focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring rounded-t",
              isActive
                ? "border-transparent text-brand-orange-text dark:text-brand-orange font-semibold"
                : "border-transparent text-content-secondary hover:text-content-primary hover:border-border-strong"
            )}
          >
            {tab.icon && <span className="w-4 h-4 shrink-0">{tab.icon}</span>}
            <span>{tab.label}</span>
            {tab.count !== undefined && (
              <span
                className={cn(
                  "font-mono-numbers px-1.5 py-0.5 rounded-full text-[11px] leading-none shrink-0",
                  isActive
                    ? "bg-brand-50 text-brand-orange-text dark:text-brand-orange font-semibold"
                    : "bg-surface-subtle text-content-tertiary"
                )}
              >
                {tab.count}
              </span>
            )}
          </button>
        );
      })}
      {/* Gliding active underline indicator */}
      {indicator.width > 0 && (
        <span
          className="absolute bottom-0 h-0.5 bg-brand-orange rounded-full transition-all duration-200 ease-out pointer-events-none"
          style={{
            left: `${indicator.left}px`,
            width: `${indicator.width}px`,
          }}
          aria-hidden="true"
        />
      )}
    </div>
  );
}
