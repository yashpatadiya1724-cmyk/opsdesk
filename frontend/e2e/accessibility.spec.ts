import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import path from 'path';
import fs from 'fs';

interface AxeReportData {
  timestamp: string;
  standards: string[];
  summary: {
    totalScans: number;
    passedScans: number;
    failedScans: number;
    totalViolations: number;
    violationsByImpact: {
      critical: number;
      serious: number;
      moderate: number;
      minor: number;
    };
  };
  scans: Array<{
    page: string;
    theme: string;
    viewport: { width: number; height: number; type: 'desktop' | 'mobile' };
    violationsCount: number;
    violations: Array<{
      id: string;
      impact?: string | null;
      description: string;
      help: string;
      helpUrl: string;
      nodesCount: number;
      nodes: Array<{
        html: string;
        target: any;
        failureSummary?: string;
      }>;
    }>;
    passesCount: number;
    incompleteCount: number;
  }>;
  allViolations: Array<{
    page: string;
    theme: string;
    viewport: string;
    id: string;
    impact?: string | null;
    description: string;
    nodes: Array<{
      html: string;
      target: any;
      failureSummary?: string;
    }>;
  }>;
  colorContrastViolations: Array<{
    page: string;
    theme: string;
    viewport: string;
    nodes: Array<{
      html: string;
      target: any;
      failureSummary?: string;
    }>;
  }>;
}

const reportData: AxeReportData = {
  timestamp: new Date().toISOString(),
  standards: ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'],
  summary: {
    totalScans: 0,
    passedScans: 0,
    failedScans: 0,
    totalViolations: 0,
    violationsByImpact: {
      critical: 0,
      serious: 0,
      moderate: 0,
      minor: 0,
    },
  },
  scans: [],
  allViolations: [],
  colorContrastViolations: [],
};

const PAGES_TO_TEST = ['/login', '/', '/insights', '/ticket/TCK-1001'];
const VIEWPORTS = [
  { type: 'desktop' as const, width: 1280, height: 800 },
  { type: 'mobile' as const, width: 390, height: 844 },
];
const THEMES = ['light', 'dark'];

test.describe('WCAG 2.2 AA Accessibility Audits', () => {
  test.afterAll(async () => {
    // Write out the comprehensive axe report to docs/verification/axe_report.json
    const repoRoot = path.resolve(__dirname, '../..');
    const outDir = path.resolve(repoRoot, 'docs/verification');
    if (!fs.existsSync(outDir)) {
      fs.mkdirSync(outDir, { recursive: true });
    }
    const reportPath = path.resolve(outDir, 'axe_report.json');
    fs.writeFileSync(reportPath, JSON.stringify(reportData, null, 2), 'utf-8');
    console.log(`[Axe Audit] Comprehensive report written to: ${reportPath}`);
    console.log(`[Axe Audit] Total scans: ${reportData.summary.totalScans}`);
    console.log(
      `[Axe Audit] Violations by impact: critical=${reportData.summary.violationsByImpact.critical}, serious=${reportData.summary.violationsByImpact.serious}, moderate=${reportData.summary.violationsByImpact.moderate}, minor=${reportData.summary.violationsByImpact.minor}`
    );
  });

  for (const pagePath of PAGES_TO_TEST) {
    for (const vp of VIEWPORTS) {
      for (const theme of THEMES) {
        test(`axe scan: ${pagePath} [${theme} theme, ${vp.type} ${vp.width}px]`, async ({ page }) => {
          await page.setViewportSize({ width: vp.width, height: vp.height });
          await page.emulateMedia({ colorScheme: theme === 'dark' ? 'dark' : 'light' });

          // Preset theme and Lead user (USR-104) for full operational permissions
          await page.addInitScript(
            ({ t }) => {
              window.localStorage.setItem('opsdesk_theme', t);
              window.localStorage.setItem('opsdesk_user_id', 'USR-104');
              if (t === 'dark') {
                document.documentElement.setAttribute('data-theme', 'dark');
                document.documentElement.classList.add('dark');
              } else {
                document.documentElement.setAttribute('data-theme', 'light');
                document.documentElement.classList.remove('dark');
              }
            },
            { t: theme }
          );

          await page.goto(pagePath, { waitUntil: 'domcontentloaded' });
          await page.waitForTimeout(600);

          // Run Axe with specified WCAG tags
          const axeBuilder = new AxeBuilder({ page }).withTags([
            'wcag2a',
            'wcag2aa',
            'wcag21aa',
            'wcag22aa',
          ]);

          const results = await axeBuilder.analyze();

          reportData.summary.totalScans += 1;
          reportData.summary.totalViolations += results.violations.length;

          for (const v of results.violations) {
            const impact = (v.impact || 'minor') as 'critical' | 'serious' | 'moderate' | 'minor';
            if (reportData.summary.violationsByImpact[impact] !== undefined) {
              reportData.summary.violationsByImpact[impact] += 1;
            }

            reportData.allViolations.push({
              page: pagePath,
              theme,
              viewport: `${vp.type} (${vp.width}x${vp.height})`,
              id: v.id,
              impact: v.impact,
              description: v.description,
              nodes: v.nodes.map((n) => ({
                html: n.html,
                target: n.target,
                failureSummary: n.failureSummary,
              })),
            });

            if (v.id === 'color-contrast') {
              reportData.colorContrastViolations.push({
                page: pagePath,
                theme,
                viewport: `${vp.type} (${vp.width}x${vp.height})`,
                nodes: v.nodes.map((n) => ({
                  html: n.html,
                  target: n.target,
                  failureSummary: n.failureSummary,
                })),
              });
            }
          }

          reportData.scans.push({
            page: pagePath,
            theme,
            viewport: vp,
            violationsCount: results.violations.length,
            violations: results.violations.map((v) => ({
              id: v.id,
              impact: v.impact,
              description: v.description,
              help: v.help,
              helpUrl: v.helpUrl,
              nodesCount: v.nodes.length,
              nodes: v.nodes.map((n) => ({
                html: n.html,
                target: n.target,
                failureSummary: n.failureSummary,
              })),
            })),
            passesCount: results.passes.length,
            incompleteCount: results.incomplete.length,
          });

          // Strict WCAG AA: zero critical and zero serious violations across all scans with NO exclusions or allowlists
          const severeViolations = results.violations.filter(
            (v) => v.impact === 'critical' || v.impact === 'serious'
          );

          if (results.violations.length === 0) {
            reportData.summary.passedScans += 1;
          } else {
            reportData.summary.failedScans += 1;
          }

          expect(
            severeViolations,
            `Expected 0 critical/serious violations on ${pagePath} (${theme}, ${vp.type}), found: ${JSON.stringify(severeViolations, null, 2)}`
          ).toEqual([]);
        });
      }
    }
  }
});

test.describe('Keyboard Interaction Flows', () => {
  test('Tab key reaches queue rows and Enter key opens ticket', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.addInitScript(() => {
      window.localStorage.setItem('opsdesk_user_id', 'USR-104');
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });

    // Wait for queue rows to be loaded
    const queueRows = page.locator('tbody tr[tabindex="0"]');
    await expect(queueRows.first()).toBeVisible({ timeout: 10000 });

    // Focus on the queue filter search input directly above the table
    const searchInput = page.getByPlaceholder(/Search TBOH, TCK-ID/i).first();
    await expect(searchInput).toBeVisible({ timeout: 5000 });
    await searchInput.focus();

    // Tab through elements from the filter bar into the table rows
    let reachedRow = false;
    for (let i = 0; i < 20; i++) {
      await page.keyboard.press('Tab');
      const isRowFocused = await page.evaluate(() => {
        const active = document.activeElement;
        return active?.tagName === 'TR' && active?.getAttribute('tabindex') === '0';
      });
      if (isRowFocused) {
        reachedRow = true;
        break;
      }
    }

    expect(reachedRow, 'Tab key must reach at least one interactive queue row').toBe(true);

    // Press Enter to open the focused ticket
    await page.keyboard.press('Enter');
    await page.waitForURL(/\/ticket\/TCK-/, { timeout: 10000 });
    expect(page.url()).toContain('/ticket/TCK-');
  });

  test('Escape key closes mobile filter sheet and returns focus to trigger button', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.addInitScript(() => {
      window.localStorage.setItem('opsdesk_user_id', 'USR-104');
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });

    // Find and click the Filters button on mobile view
    const filtersBtn = page.getByRole('button', { name: /Filters/i });
    await expect(filtersBtn).toBeVisible({ timeout: 10000 });
    await filtersBtn.click();

    // Verify filter sheet dialog is open
    const sheetDialog = page.getByRole('dialog', { name: /Queue filter sheet/i });
    await expect(sheetDialog).toBeVisible({ timeout: 5000 });

    // Press Escape
    await page.keyboard.press('Escape');

    // Verify filter sheet dialog is closed and focus returns to filtersBtn
    await expect(sheetDialog).not.toBeVisible({ timeout: 5000 });
    await expect(filtersBtn).toBeFocused({ timeout: 5000 });
  });

  test('Escape key closes Popover menu and returns focus to trigger button', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.addInitScript(() => {
      window.localStorage.setItem('opsdesk_user_id', 'USR-104');
    });
    await page.goto('/', { waitUntil: 'domcontentloaded' });

    // Wait for mobile ticket card with options button
    const optionsButton = page.locator('button[aria-label="Ticket options"]').first();
    await expect(optionsButton).toBeVisible({ timeout: 10000 });

    // Click options button to open popover
    await optionsButton.click();

    // Verify popover dialog is visible
    const popoverDialog = page.locator('div[role="dialog"]').first();
    await expect(popoverDialog).toBeVisible({ timeout: 5000 });

    // Press Escape to close popover
    await page.keyboard.press('Escape');

    // Popover dialog must close
    await expect(popoverDialog).not.toBeVisible({ timeout: 5000 });

    // Focus must return to the trigger button
    await expect(optionsButton).toBeFocused({ timeout: 5000 });
  });
});
