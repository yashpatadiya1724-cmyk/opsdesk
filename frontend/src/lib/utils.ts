import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Shared helper to parse API datetime strings safely as UTC.
 * If the string lacks a timezone designator (Z or +hh:mm), 'Z' is appended
 * so that naive UTC strings from backend SQLite/FastAPI are never mistakenly
 * parsed as local client time.
 */
export function parseUtc(dateInput: string | Date | number | null | undefined): Date | null {
  if (dateInput === null || dateInput === undefined || dateInput === "") {
    return null;
  }
  if (dateInput instanceof Date) {
    return isNaN(dateInput.getTime()) ? null : new Date(dateInput.getTime());
  }
  if (typeof dateInput === "number") {
    const d = new Date(dateInput);
    return isNaN(d.getTime()) ? null : d;
  }
  if (typeof dateInput === "string") {
    const trimmed = dateInput.trim();
    if (!trimmed) return null;
    // If already has timezone indicator (Z or +/-offset), parse directly
    if (/[zZ]|[+-]\d{2}(?::?\d{2})?$/.test(trimmed)) {
      const d = new Date(trimmed);
      return isNaN(d.getTime()) ? null : d;
    }
    // Naive string: normalize space to 'T' if present, append 'Z'
    const normalized = trimmed.includes(" ") && !trimmed.includes("T") ? trimmed.replace(" ", "T") : trimmed;
    const d = new Date(normalized + "Z");
    return isNaN(d.getTime()) ? null : d;
  }
  return null;
}

export function formatDate(
  dateInput: string | Date | number | null | undefined,
  options?: Intl.DateTimeFormatOptions
): string {
  if (!dateInput) return "—";
  try {
    const d = parseUtc(dateInput);
    if (!d || isNaN(d.getTime())) return typeof dateInput === "string" ? dateInput : "—";
    return d.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: true,
      timeZoneName: "short",
      ...options,
    });
  } catch {
    return typeof dateInput === "string" ? dateInput : "—";
  }
}

export function formatRelativeTime(dateInput: string | Date | number | null | undefined): string {
  if (!dateInput) return "—";
  try {
    const d = parseUtc(dateInput);
    if (!d || isNaN(d.getTime())) return typeof dateInput === "string" ? dateInput : "—";
    const now = new Date();
    const diffSec = Math.floor((now.getTime() - d.getTime()) / 1000);

    if (diffSec < 60) return "just now";
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHrs = Math.floor(diffMin / 60);
    if (diffHrs < 24) return `${diffHrs}h ago`;
    const diffDays = Math.floor(diffHrs / 24);
    if (diffDays < 7) return `${diffDays}d ago`;
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZoneName: "short" });
  } catch {
    return typeof dateInput === "string" ? dateInput : "—";
  }
}
