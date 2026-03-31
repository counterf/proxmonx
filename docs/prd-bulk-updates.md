# PRD: Bulk Guest Updates

| Field        | Value                                     |
|--------------|-------------------------------------------|
| Author       | Alysson Silva                             |
| Status       | Draft                                     |
| Created      | 2026-03-30                                |
| Last updated | 2026-03-30                                |
| Version      | 0.1                                       |
| Parent PRD   | `docs/prd.md` (proxmon MVP)               |
| Depends on   | Existing per-guest action endpoints        |

---

## 1. Context & Why Now

- proxmon manages fleets of LXC containers and VMs across one or more Proxmox hosts. Today, every action (OS update, app update, backup, restart, etc.) must be triggered one guest at a time through the per-row actions dropdown.
- Users with 10-50+ guests report that applying OS updates across their fleet is tedious and error-prone -- they must click into each guest individually, confirm, wait, and repeat.
- The task history system (`task_store.py`) and background polling infrastructure (`_poll_upid`) already exist, meaning the backend can track many concurrent operations without new persistence work.
- OS update concurrency guards (`_os_update_in_progress` set) already prevent duplicate runs per-guest, so bulk dispatch is safe against double-execution.
- Community feedback from Proxmox homelab operators consistently cites "batch operations" as a top-requested feature for monitoring dashboards.

Source -- Proxmox forum threads: batch management is the most-requested feature gap in lightweight Proxmox dashboards.

---

## 2. Users & JTBD

| User | Job To Be Done |
|------|---------------|
| Homelab operator (10-30 guests) | Select 5 specific LXC containers and trigger OS updates on all of them in one action, then monitor progress from a single view. |
| Operator with tagged environments | Filter by tag (e.g., `production`) and update all matching guests, excluding one or two that need manual handling. |
| Operator doing maintenance window | Select all running LXC containers, trigger OS update, then see which succeeded and which failed -- without babysitting each one. |
| Operator with mixed fleet | Bulk-select only the guests that show pending OS updates, skip the rest. |

---

## 3. Business Goals & Success Metrics

### Goals
- Reduce time-to-complete fleet-wide OS updates from O(n * manual-clicks) to a single bulk action.
- Maintain the same safety guarantees as single-guest actions (confirmation, concurrency guards, task tracking).
- Lay the groundwork for future bulk actions (bulk restart, bulk backup, bulk app update).

### Success Metrics

| Metric | Type | Target |
|--------|------|--------|
| Time to update 10 guests (OS) | Leading | < 30 seconds of user interaction (down from ~5 min) |
| Bulk action completion visibility | Leading | 100% of dispatched tasks visible in task history within 2s |
| Error rate per bulk operation | Lagging | No increase vs. single-guest error rate |
| Feature adoption | Lagging | > 50% of OS update actions use bulk mode within 4 weeks |

---

## 4. Functional Requirements

### FR-1: Guest selection UI (checkbox column)

Add a checkbox column to the guest table.

- **FR-1.1**: Each row gets a checkbox. A header checkbox toggles select-all / deselect-all for the current filtered view.
- **FR-1.2**: Selection state persists across table sorting and filtering within the same page session. Navigating away clears selection.
- **FR-1.3**: Selected count is displayed in a sticky action bar that appears when >= 1 guest is selected (e.g., "3 guests selected").

**Acceptance criteria**: User can select individual rows, shift-click to select a range, and use the header checkbox to toggle all. Selected count badge is accurate.

### FR-2: Bulk action bar

A floating/sticky bar appears at the bottom (or top) of the guest table when selection is non-empty.

- **FR-2.1**: Bar displays: selected count, "Update OS" button, "Clear selection" button.
- **FR-2.2**: "Update OS" button is enabled only if at least one selected guest is eligible (LXC, running, has a supported `os_type`, host has `pct_exec_enabled`).
- **FR-2.3**: Ineligible guests are visually indicated (e.g., grayed checkbox or warning icon) but remain selectable -- they are silently skipped during execution.
- **FR-2.4**: Clicking "Update OS" opens a confirmation dialog listing the guests that will be updated and the count that will be skipped (with reasons).

**Acceptance criteria**: Bar appears/disappears reactively. Disabled state is correct for all edge cases. Confirmation dialog accurately partitions eligible vs. skipped guests.

### FR-3: Bulk action confirmation dialog

- **FR-3.1**: Dialog shows two sections: "Will update (N)" listing eligible guest names, and "Will skip (M)" listing ineligible guests with reason (e.g., "stopped", "VM -- not supported", "OS update already in progress").
- **FR-3.2**: User can remove individual guests from the "Will update" list before confirming.
- **FR-3.3**: "Confirm" button dispatches the bulk request. "Cancel" returns to table with selection intact.

**Acceptance criteria**: Dialog is accurate. Removing a guest from the list reduces the count. Canceling preserves selection.

### FR-4: Backend bulk endpoint

`POST /api/bulk/os-update`

- **FR-4.1**: Request body: `{ "guest_ids": ["host1:100", "host1:101", ...] }`.
- **FR-4.2**: Backend validates each guest independently (same checks as single `POST /api/guests/{id}/os-update`). Returns a response with `dispatched: [...]` and `skipped: [{ id, reason }]`.
- **FR-4.3**: Each dispatched guest creates its own `TaskRecord` in `task_store`. A parent `batch_id` (UUID) links them.
- **FR-4.4**: Concurrent OS updates per guest are still prevented by `_os_update_in_progress`. If a guest is already updating, it appears in `skipped`.
- **FR-4.5**: Bulk dispatch executes updates with a concurrency limit (default: 3 simultaneous SSH sessions per host) to avoid overloading Proxmox hosts.
- **FR-4.6**: Endpoint requires `_require_api_key` auth dependency, same as existing action endpoints.

**Acceptance criteria**: Dispatching 10 guests returns immediately with the dispatched/skipped partition. Task records are created for each dispatched guest. Concurrency limit is respected -- no more than 3 guests per host update simultaneously.

### FR-5: Bulk progress tracking

- **FR-5.1**: The existing Tasks panel (`/api/tasks`) shows individual task records for each guest in the batch.
- **FR-5.2**: Add `batch_id` field to `TaskRecord`. Tasks panel can optionally group by batch.
- **FR-5.3**: The bulk action bar (or a toast notification) shows aggregate progress: "Updating 5/8 -- 2 complete, 1 failed".
- **FR-5.4**: When all tasks in a batch complete, trigger a guest refresh for all affected guests.

**Acceptance criteria**: User can see per-guest and aggregate progress. Batch grouping in task history works. Final state is reflected in guest table after refresh.

### FR-6: Tag-based quick-select

- **FR-6.1**: Existing tag filter in the guest table integrates with selection -- filtering by tag then "select all" selects only the filtered guests.
- **FR-6.2**: No separate tag-selection UI is needed; the existing filter + select-all flow covers the "update all guests tagged X" use case.

**Acceptance criteria**: Filtering by tag "production", then clicking select-all, selects only production-tagged guests.

---

## 5. Non-Functional Requirements

### Performance
- Bulk endpoint must return the dispatched/skipped response within 500ms regardless of batch size (actual updates run async).
- Frontend must handle selection state for up to 200 guests without perceptible lag.

### Scale
- Maximum batch size: 50 guests per request. Backend rejects larger batches with 400.
- SSH concurrency limit: 3 per host (configurable via settings in a future iteration).

### SLOs
- Bulk dispatch availability: same as existing API (no separate SLO -- self-hosted).
- Task record creation: 100% of dispatched guests get a task record before any SSH work begins.

### Privacy & Security
- Bulk endpoint uses the same auth middleware as all other endpoints.
- No new secrets or credentials are introduced.
- Guest IDs in request/response are opaque identifiers already used in single-guest endpoints.

### Observability
- Backend logs: `INFO` log line per bulk dispatch with batch_id, guest count, and host distribution.
- Backend logs: `WARNING` for any skipped guest with reason.
- Task history: all individual tasks are persisted and queryable.
- Structured log fields: `batch_id`, `action`, `guest_count`, `skipped_count`.

---

## 6. Scope

### In scope
- Bulk OS update (LXC only, same as single-guest)
- Guest table checkbox selection with select-all
- Bulk action bar with confirmation dialog
- Backend bulk dispatch endpoint with concurrency limiting
- Batch tracking via `batch_id` on `TaskRecord`
- Aggregate progress display

### Out of scope (future iterations)
- Bulk app update, bulk restart, bulk backup, bulk snapshot (same pattern, different endpoint -- add after OS update is validated)
- Scheduled bulk updates (cron-style)
- Bulk actions for VMs (QEMU guest agent commands)
- Drag-to-select or advanced selection UIs
- Persistent selection across page reloads
- Per-host concurrency limit configuration in Settings UI
- Bulk action via external API (webhook/CLI) -- existing single-guest API can be scripted

---

## 7. Rollout Plan

### Phase 1: Backend (1-2 days)
1. Add `batch_id` column to `task_history` table (nullable, backwards-compatible).
2. Implement `POST /api/bulk/os-update` with validation, concurrency control, and task creation.
3. Add tests: batch dispatch, skip logic, concurrency guard, max batch size.

### Phase 2: Frontend -- selection (1 day)
1. Add checkbox column to guest table.
2. Implement selection state management (individual, shift-click range, select-all).
3. Add sticky bulk action bar with selected count.

### Phase 3: Frontend -- confirmation and progress (1 day)
1. Build confirmation dialog with eligible/skipped partitioning.
2. Wire up bulk dispatch API call.
3. Add aggregate progress indicator (poll `/api/tasks` filtered by `batch_id`).

### Guardrails
- **Max batch size**: 50 guests. Rejects with 400 if exceeded.
- **Concurrency limit**: 3 simultaneous SSH sessions per Proxmox host.
- **Existing concurrency guard**: `_os_update_in_progress` set prevents double-dispatch per guest.
- **Confirmation required**: No bulk action fires without explicit user confirmation showing the exact guest list.

### Kill switch
- Feature is behind no flag -- it is always available once deployed. However:
  - The bulk endpoint can be disabled by removing its router registration in `main.py` (single line change, instant rollback).
  - The frontend checkbox column and action bar are isolated components -- removing the import reverts to the current single-action UI.

---

## 8. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Overloading Proxmox host with concurrent SSH sessions | Medium | High -- host becomes unresponsive | Concurrency limit of 3 per host; asyncio semaphore in backend |
| Partial batch failure confuses users | Medium | Medium | Clear per-guest status in confirmation dialog and task history; aggregate progress shows success/fail counts |
| Long-running batch blocks user from other actions | Low | Medium | Bulk dispatch is fire-and-forget; user can navigate away and check Tasks panel later |
| `_os_update_in_progress` set grows unbounded on crash | Low | Low | Existing risk (not new); mitigated by process restart clearing the in-memory set |
| Schema migration breaks existing task history | Low | Medium | `batch_id` column is nullable with no default; `ALTER TABLE ADD COLUMN` is safe on SQLite |

---

## 9. Open Questions

1. **Concurrency limit value**: Is 3 per host the right default, or should it be configurable from day one?
2. **Notification integration**: Should bulk completion trigger an ntfy notification? (Current single-guest updates do not.)
3. **Batch retry**: If 2 of 8 guests fail, should there be a "retry failed" button on the batch? Or does the user re-select and re-dispatch?
4. **Future bulk actions**: Should the bulk action bar include a dropdown for action type (OS update / restart / backup), or should each action get its own button? Dropdown scales better but adds complexity.
5. **Selection persistence**: Should selection survive a guest table auto-refresh (poll cycle), or reset? Auto-refresh changes the guest list, which may invalidate selections.
