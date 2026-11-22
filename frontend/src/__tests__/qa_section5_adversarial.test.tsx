import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import fs from "fs";
import path from "path";
import { Popover } from "../components/ui/Popover";
import { MobileFilterSheet } from "../components/queue/MobileFilterSheet";

describe("Section 5 Adversarial QA Tests", () => {
  it("Hypothesis 1 & 3: Popover restores focus to trigger element on Escape", () => {
    render(
      <div>
        <button id="outside-btn" type="button">Outside</button>
        <Popover
          trigger={<button id="popover-trigger" type="button">Open Menu</button>}
        >
          <div id="popover-content">Popover Content</div>
        </Popover>
      </div>
    );

    const triggerBtn = screen.getByRole("button", { name: /Open Menu/i });
    triggerBtn.focus();
    expect(document.activeElement).toBe(triggerBtn);

    fireEvent.click(triggerBtn);
    expect(screen.getByText("Popover Content")).toBeTruthy();

    // Press Escape
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByText("Popover Content")).toBeNull();
    expect(document.activeElement).toBe(triggerBtn);
  });

  it("Hypothesis 3: MobileFilterSheet restores focus to trigger element on Escape dismissal", () => {
    const onClose = vi.fn();
    const { rerender } = render(
      <div>
        <button id="open-filters-btn" type="button">Filters</button>
        <MobileFilterSheet
          isOpen={false}
          onClose={onClose}
          searchQuery=""
          onSearchChange={vi.fn()}
          intentFilter=""
          onIntentChange={vi.fn()}
          priorityFilter=""
          onPriorityChange={vi.fn()}
          statusFilter=""
          onStatusChange={vi.fn()}
          atRiskOnly={false}
          onToggleAtRisk={vi.fn()}
          hasActiveFilters={false}
          onClearFilters={vi.fn()}
        />
      </div>
    );

    const filterBtn = screen.getByRole("button", { name: /Filters/i });
    filterBtn.focus();
    expect(document.activeElement).toBe(filterBtn);

    // Open sheet
    rerender(
      <div>
        <button id="open-filters-btn" type="button">Filters</button>
        <MobileFilterSheet
          isOpen={true}
          onClose={onClose}
          searchQuery=""
          onSearchChange={vi.fn()}
          intentFilter=""
          onIntentChange={vi.fn()}
          priorityFilter=""
          onPriorityChange={vi.fn()}
          statusFilter=""
          onStatusChange={vi.fn()}
          atRiskOnly={false}
          onToggleAtRisk={vi.fn()}
          hasActiveFilters={false}
          onClearFilters={vi.fn()}
        />
      </div>
    );

    expect(screen.getByRole("dialog", { name: /Queue filter sheet/i })).toBeTruthy();

    // Press Escape
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("Hypothesis 2: axe_report.json exists, is valid JSON, and covers all 4 routes", () => {
    const reportPath = path.resolve(process.cwd(), "../docs/verification/axe_report.json");
    expect(fs.existsSync(reportPath)).toBe(true);

    const content = fs.readFileSync(reportPath, "utf-8");
    const json = JSON.parse(content);

    expect(json.summary).toBeDefined();
    expect(json.summary.totalScans).toBeGreaterThanOrEqual(16);
    expect(json.summary.violationsByImpact.critical).toBe(0);

    const routesScanned = new Set(json.scans.map((s: { page: string }) => s.page));
    expect(routesScanned.has("/login")).toBe(true);
    expect(routesScanned.has("/")).toBe(true);
    expect(routesScanned.has("/insights")).toBe(true);
    expect(routesScanned.has("/ticket/TCK-1001")).toBe(true);
  });

  it("Hypothesis 4: ACCESSIBILITY_WCAG.md is truthful and contains required sections", () => {
    const docPath = path.resolve(process.cwd(), "../docs/ACCESSIBILITY_WCAG.md");
    expect(fs.existsSync(docPath)).toBe(true);

    const docText = fs.readFileSync(docPath, "utf-8");

    // Must not claim 100% compliant
    expect(docText.toLowerCase()).not.toContain("100% compliant");

    // Must cite axe report contrast measurements
    expect(docText).toContain("axe_report.json");
    expect(docText).toContain("15.8:1");

    // Must document manual check scopes
    expect(docText).toContain("NVDA");
    expect(docText).toContain("Zoom");
    expect(docText).toContain("Reduced Motion");
  });
});
