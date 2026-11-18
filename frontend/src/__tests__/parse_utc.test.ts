import { describe, it, expect } from "vitest";
import { parseUtc, formatDate, formatRelativeTime } from "@/lib/utils";

describe("parseUtc timezone helper", () => {
  it("treats naive ISO datetime strings without timezone designator as UTC", () => {
    const naive = "2026-11-18T10:07:03.094405";
    const parsed = parseUtc(naive);
    expect(parsed).not.toBeNull();
    // Milliseconds precision in JS Date keeps 3 digits .094
    expect(parsed!.getUTCFullYear()).toBe(2026);
    expect(parsed!.getUTCMonth()).toBe(10); // November (0-indexed)
    expect(parsed!.getUTCDate()).toBe(18);
    expect(parsed!.getUTCHours()).toBe(10);
    expect(parsed!.getUTCMinutes()).toBe(7);
    expect(parsed!.getUTCSeconds()).toBe(3);
    expect(parsed!.getUTCMilliseconds()).toBe(94);
  });

  it("handles ISO strings with explicit 'Z' correctly", () => {
    const withZ = "2026-11-18T10:07:03.094Z";
    const parsed = parseUtc(withZ);
    expect(parsed).not.toBeNull();
    expect(parsed!.getUTCHours()).toBe(10);
    expect(parsed!.getUTCMinutes()).toBe(7);
    expect(parsed!.toISOString()).toBe("2026-11-18T10:07:03.094Z");
  });

  it("handles ISO strings with timezone offsets like '+05:30' correctly", () => {
    // 15:37:03.094 in IST (+05:30) is exactly 10:07:03.094 UTC
    const withOffset = "2026-11-18T15:37:03.094+05:30";
    const parsed = parseUtc(withOffset);
    expect(parsed).not.toBeNull();
    expect(parsed!.getUTCHours()).toBe(10);
    expect(parsed!.getUTCMinutes()).toBe(7);
    expect(parsed!.toISOString()).toBe("2026-11-18T10:07:03.094Z");
  });

  it("handles naive space-separated datetime strings as UTC", () => {
    const spaceSeparated = "2026-11-18 10:07:03";
    const parsed = parseUtc(spaceSeparated);
    expect(parsed).not.toBeNull();
    expect(parsed!.getUTCHours()).toBe(10);
    expect(parsed!.getUTCMinutes()).toBe(7);
    expect(parsed!.getUTCSeconds()).toBe(3);
  });

  it("gracefully returns null for null, undefined, or empty inputs", () => {
    expect(parseUtc(null)).toBeNull();
    expect(parseUtc(undefined)).toBeNull();
    expect(parseUtc("")).toBeNull();
    expect(parseUtc("   ")).toBeNull();
  });

  it("gracefully returns null for unparseable invalid dates", () => {
    expect(parseUtc("not-a-real-date")).toBeNull();
  });

  it("formatDate formats valid dates with timezone abbreviation and fallback for invalid", () => {
    const naive = "2026-11-18T10:07:03.094405";
    const formatted = formatDate(naive);
    expect(formatted).not.toBe("—");
    expect(formatted).toContain("2026");
    // Formatted string should include hour and minute
    expect(formatted).toMatch(/\d{1,2}:\d{2}/);

    expect(formatDate(null)).toBe("—");
    expect(formatDate("invalid-date")).toBe("invalid-date");
  });

  it("formatRelativeTime formats relative durations accurately", () => {
    const recent = new Date(Date.now() - 5000).toISOString();
    expect(formatRelativeTime(recent)).toBe("just now");
    expect(formatRelativeTime(null)).toBe("—");
  });
});
