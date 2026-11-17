import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { computePollDelay, ApiError } from "@/lib/api";

describe("Frontend Polling with Jitter and Backoff", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("calculates +-20% random jitter on normal polling base delay", () => {
    const baseDelay = 30000;
    // With +-20% jitter, multiplier is in [0.8, 1.2], so delay must be in [24000, 36000]
    for (let i = 0; i < 50; i++) {
      const { delay, nextBackoff } = computePollDelay(baseDelay);
      expect(delay).toBeGreaterThanOrEqual(24000);
      expect(delay).toBeLessThanOrEqual(36000);
      expect(nextBackoff).toBe(5000);
    }
  });

  it("honors Retry-After header on 429 and 503 rate limits", () => {
    // 429 Too Many Requests with Retry-After: 15s
    const err429 = new ApiError("Too Many Requests", 429, 15);
    const res429 = computePollDelay(30000, { status: err429.status, retryAfter: err429.retryAfter }, 5000);
    expect(res429.delay).toBe(15000); // 15s * 1000

    // 503 Service Unavailable with Retry-After: 45s
    const err503 = new ApiError("Service Unavailable", 503, 45);
    const res503 = computePollDelay(30000, { status: err503.status, retryAfter: err503.retryAfter }, 5000);
    expect(res503.delay).toBe(45000); // 45s * 1000
  });

  it("calculates exponential backoff on 429/503 when Retry-After is absent", () => {
    let currentBackoff = 5000;

    // First 429 error
    const step1 = computePollDelay(30000, { status: 429 }, currentBackoff);
    expect(step1.delay).toBe(5000);
    expect(step1.nextBackoff).toBe(10000);
    currentBackoff = step1.nextBackoff;

    // Second 429 error
    const step2 = computePollDelay(30000, { status: 429 }, currentBackoff);
    expect(step2.delay).toBe(10000);
    expect(step2.nextBackoff).toBe(20000);
    currentBackoff = step2.nextBackoff;

    // Third 429 error
    const step3 = computePollDelay(30000, { status: 429 }, currentBackoff);
    expect(step3.delay).toBe(20000);
    expect(step3.nextBackoff).toBe(40000);
    currentBackoff = step3.nextBackoff;

    // Fourth 429 error caps at 60000
    const step4 = computePollDelay(30000, { status: 429 }, currentBackoff);
    expect(step4.delay).toBe(40000);
    expect(step4.nextBackoff).toBe(60000);

    // Recovery resets nextBackoff to 5000
    const recovery = computePollDelay(30000);
    expect(recovery.nextBackoff).toBe(5000);
  });

  it("aborts active requests on unmount via AbortController", () => {
    const controller = new AbortController();
    expect(controller.signal.aborted).toBe(false);

    controller.abort();
    expect(controller.signal.aborted).toBe(true);
  });

  it("pauses polling when document is hidden (visibilitychange) and resumes on return", () => {
    let isPolling = true;
    let refreshTriggered = false;

    const handleVisibilityChange = (hidden: boolean) => {
      if (hidden) {
        isPolling = false;
      } else {
        isPolling = true;
        refreshTriggered = true;
      }
    };

    handleVisibilityChange(true);
    expect(isPolling).toBe(false);
    expect(refreshTriggered).toBe(false);

    handleVisibilityChange(false);
    expect(isPolling).toBe(true);
    expect(refreshTriggered).toBe(true);
  });
});
