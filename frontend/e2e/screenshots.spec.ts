import { test, expect } from '@playwright/test';
import path from 'path';
import fs from 'fs';

const SCREENSHOT_DIR = path.resolve(__dirname, '../../docs/verification/screenshots');

test.beforeAll(() => {
  if (!fs.existsSync(SCREENSHOT_DIR)) {
    fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
  }
});

test.describe('OpsDesk Demo UI Screenshots', () => {
  test('1. Agent Portal Screenshot (Aisha - USR-101)', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/login');
    // Set demo user to USR-101 via localStorage or UI
    await page.evaluate(() => {
      localStorage.setItem('opsdesk_user_id', 'USR-101');
      localStorage.setItem('opsdesk_role', 'Agent');
    });
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
    const screenshotPath = path.join(SCREENSHOT_DIR, 'portal_agent.png');
    await page.screenshot({ path: screenshotPath, fullPage: false });
    console.log(`Saved screenshot: ${screenshotPath}`);
  });

  test('2. Lead Portal Screenshot (Priya - USR-104)', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/login');
    await page.evaluate(() => {
      localStorage.setItem('opsdesk_user_id', 'USR-104');
      localStorage.setItem('opsdesk_role', 'Lead');
    });
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
    const screenshotPath = path.join(SCREENSHOT_DIR, 'portal_lead.png');
    await page.screenshot({ path: screenshotPath, fullPage: false });
    console.log(`Saved screenshot: ${screenshotPath}`);
  });

  test('3. Escalation Manager Portal Screenshot (Vikram - USR-103)', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/login');
    await page.evaluate(() => {
      localStorage.setItem('opsdesk_user_id', 'USR-103');
      localStorage.setItem('opsdesk_role', 'EscalationManager');
    });
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
    const screenshotPath = path.join(SCREENSHOT_DIR, 'portal_escalation_manager.png');
    await page.screenshot({ path: screenshotPath, fullPage: false });
    console.log(`Saved screenshot: ${screenshotPath}`);
  });

  test('4. Requester Portal Screenshot (Agency - USR-201)', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/login');
    await page.evaluate(() => {
      localStorage.setItem('opsdesk_user_id', 'USR-201');
      localStorage.setItem('opsdesk_role', 'Requester');
    });
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
    const screenshotPath = path.join(SCREENSHOT_DIR, 'portal_requester.png');
    await page.screenshot({ path: screenshotPath, fullPage: false });
    console.log(`Saved screenshot: ${screenshotPath}`);
  });

  test('5. TBOH-89104 Case View Screenshot (TCK-1008 Linked History)', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/login');
    await page.evaluate(() => {
      localStorage.setItem('opsdesk_user_id', 'USR-101');
      localStorage.setItem('opsdesk_role', 'Agent');
    });
    await page.goto('/ticket/TCK-1008');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1000);
    const screenshotPath = path.join(SCREENSHOT_DIR, 'case_view_tboh89104.png');
    await page.screenshot({ path: screenshotPath, fullPage: false });
    console.log(`Saved screenshot: ${screenshotPath}`);
  });
});
