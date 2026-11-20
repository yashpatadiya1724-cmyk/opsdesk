# OpsDesk Functional QA - Feature Gaps & Inventory

This document tracks items evaluated during Functional Browser QA that are identified as **NOT-BUILT** or **BY-DESIGN**, along with architectural rationale and recommended priorities.

---

## 1. Summary of Identified Gaps

| ID | Category | Feature / Requirement | State | Severity / Priority | Description |
|---|---|---|---|---|---|
| **GAP-B6-1** | Queue UI | Queue Toolbar Explicit Refresh Button | **NOT-BUILT** | P3 (Low / Enhancement) | The Operations Queue header and toolbar do not provide a dedicated manual "Refresh" or reload icon button. Live data updates rely on tab-switching, filter adjustments, and 30s polling. |
| **GAP-B6-2** | Queue UI | "Last Updated X minutes ago" Indicator | **NOT-BUILT** | P3 (Low / Enhancement) | While the Top Departure Board and row flight paths provide real-time countdown clocks, there is no global text indicator displaying the exact timestamp of the last queue fetch. |
| **GAP-A4-1** | Auth / Shell | Explicit "Log Out" Button in Demo Mode | **BY-DESIGN** | N/A (By Design) | In demo authentication mode, user sessions are managed entirely via the active persona switcher in TopNav (`x-user-id` header). Explicit logout is only active in production JWT mode (`/login`). |

---

## 2. Details & Recommendations

### GAP-B6-1: Queue Toolbar Refresh Button
- **Observed Behavior**: Queue header displays `Operations Queue (460 cases)`, subtitle, `Work next` CTA, `Export CSV`, and `New ticket`. No manual refresh trigger exists.
- **Impact**: Operators seeking immediate feedback after off-screen actions must toggle tabs or filters.
- **Recommended Fix (Future)**: Add an icon button with `RotateCw` from `lucide-react` adjacent to the CSV export action that triggers `mutate()` on the active queue query.

### GAP-B6-2: Queue Last-Updated Relative Timestamp
- **Observed Behavior**: Queue displays real-time countdowns (`1h 46m`, `1d 5h`), but no "Updated just now" status label.
- **Impact**: Minor UX clarity improvement for dispatchers monitoring slow-moving queues.
- **Recommended Fix (Future)**: Display an auto-updating relative time pill next to the case count.

### GAP-A4-1: Demo Mode Session Clearing
- **Observed Behavior**: Navigating to `?user=unknown` or unauthenticated query parameters falls back securely to the default Lead/Agent persona (Aisha Khan `USR-101`).
- **Impact**: None; secure and compliant with demo mode specifications.
