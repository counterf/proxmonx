# UX Spec: Bulk Guest Updates

## Overview

Add a non-destructive multi-select capability to the guest list that lets users select N guests and run OS Update or App Update across all of them in a single action, with per-guest progress and results.

The feature must not change the existing per-row actions dropdown (`GuestActions.tsx`) and must not add visual noise when bulk mode is inactive.

---

## Interaction Model

### Entry / Exit

- Bulk mode is **off by default**. The table looks identical to today.
- Entry: user clicks a "Select" toggle button in the Dashboard header row (sits next to the existing Refresh button). Label reads "Select" when inactive, becomes "Done" when active.
- Exit: clicking "Done", pressing `Escape`, or clearing all selections (last checkbox unchecked) exits bulk mode and dismisses the action bar.
- Navigation away (e.g. clicking a guest row to open the detail page) is **blocked** when bulk mode is active. Clicking a row instead toggles the checkbox for that row. The cursor changes to `default` instead of `pointer` on `tr` elements during bulk mode to signal this.

### Selection Mechanics

- Each visible row gets a checkbox in a prepended column when bulk mode is active.
- The table header gets a "select all visible" checkbox in the same prepended column. Its state follows the standard tri-state pattern:
  - Unchecked: 0 of N visible selected
  - Indeterminate: 1 to N-1 selected
  - Checked: all N visible selected
- Clicking the header checkbox when unchecked or indeterminate selects all visible (filtered) rows. Clicking when checked deselects all.
- Individual row checkboxes toggle their guest in/out of the selection set.
- Selections survive filter changes: if guest A is selected then filtered out of view, it remains in the selection set. A status line reads "3 selected (1 not visible in current filter)". When the filter is cleared, the hidden guest reappears still selected.
- "Select all" only applies to the current filtered view, supporting scenario 3 from the requirements.

### Selection Persistence

Selection state lives in `Dashboard` component state (`Set<string>` of guest IDs). It is reset when bulk mode is exited or when a bulk action completes successfully.

---

## Component Breakdown

### 1. `SelectToggleButton` (inline in `Dashboard`)

A simple button in the header row. Not a separate component; it sits in the existing `flex items-center gap-3` header cluster alongside Refresh and ColumnToggle.

```
[ Refresh ] [ Columns v ] [ Select ]
```

When bulk mode is active:
```
[ Refresh ] [ Columns v ] [ Done ]  <- "Done" in gray-600 style to feel dismissive
```

Props it would need: `active: boolean`, `onToggle: () => void`.

### 2. Checkbox column in `GuestTableRow`

When bulk mode is active, a `<td>` with `width: 36px` is prepended before the name column. Contains a styled `<input type="checkbox">` with an `aria-label` of `"Select {guest.name}"`.

The row's `onClick` handler is replaced during bulk mode: instead of `navigate(/guest/{id})`, it calls `onToggleSelect(guest.id)`. The `tabIndex` and `onKeyDown` handlers still work but now toggle selection instead of navigating (Space key toggles, Enter key navigates because Enter-to-navigate is conventional and lower risk for accidental bulk inclusion).

The row receives a subtle highlight when selected: `bg-blue-950/40 border-l-2 border-blue-600` replacing the standard hover background.

### 3. Header checkbox in `<thead>`

Replaces the empty `<th>` prepended cell. Contains a tri-state checkbox. `aria-label="Select all visible guests"`. The indeterminate state is set via a `ref` on the `<input>` element setting `.indeterminate = true`.

### 4. `BulkActionBar` (new component: `frontend/src/components/BulkActionBar.tsx`)

A sticky bar that appears at the bottom of the viewport when bulk mode is active and at least 1 guest is selected. Disappears (but bulk mode stays active with 0 selected) when selection is empty.

Layout:
```
[ 3 guests selected ]   [ OS Update ]   [ App Update ]   [ Clear ]
```

- "3 guests selected" is plain text (`text-sm text-gray-300`).
- If any selected guests are not running LXC containers, a warning chip appears inline: `! 2 guests will be skipped (not LXC or not running)`.
- "OS Update" button: `bg-cyan-700 hover:bg-cyan-600 text-white text-sm px-4 py-1.5 rounded`.
- "App Update" button: only enabled (not disabled) when at least one selected guest has `has_community_script === true`. Always visible, grayed when no eligible guests. Tooltip on hover when disabled: "None of the selected guests support app updates".
- "Clear" button: `text-gray-400 hover:text-white text-sm`.
- The bar itself: `fixed bottom-0 left-0 right-0 z-50 bg-gray-900 border-t border-gray-700 px-4 py-3 flex items-center gap-4 flex-wrap`.
- On mobile the bar stacks vertically and takes full width.

### 5. `BulkProgressModal` (new component: `frontend/src/components/BulkProgressModal.tsx`)

A modal overlay that appears after the user confirms the bulk action. It renders a scrollable list of per-guest status rows.

Modal structure:
```
+----------------------------------------------+
| Bulk OS Update — 3 guests           [X close] |
+----------------------------------------------+
| pve-jellyfin   [ running... ]                 |
| pve-nextcloud  [ done ]                       |
| pve-pihole     [ failed: exit code 1 ]        |
+----------------------------------------------+
| 1 / 3 complete           [ Close ] (disabled  |
|                            until all done)    |
+----------------------------------------------+
```

Each row:
- Guest name (`text-sm text-gray-200`)
- Status indicator (right-aligned):
  - Queued: `text-gray-500` — "waiting..."
  - Running: cyan spinner + "running..." (`text-cyan-400`)
  - Done: green checkmark + "done" (`text-green-400`)
  - Failed: red X + error message truncated to 60 chars with full text on `title` tooltip (`text-red-400`)
  - Skipped: gray dash + "skipped — not eligible" (`text-gray-500`)

Progress counter at the bottom: "2 / 3 complete" updates as each guest finishes. "1 failed" appears in red when failures exist.

Close button:
- Disabled (with `disabled:opacity-50 cursor-not-allowed`) until all guests reach a terminal state (done, failed, or skipped).
- After close, bulk mode exits and selections are cleared.

The modal blocks the background with a `bg-black/60` overlay. It does not close on outside click while operations are in progress to prevent accidental dismissal. After all operations complete, outside click dismisses.

---

## All States

### Idle (bulk mode off)

No visual change to the guest list. "Select" button is present but understated (matches the ColumnToggle button style: `px-3 py-1.5 text-sm rounded bg-gray-800 border border-gray-700 text-gray-400 hover:text-gray-200`).

### Selecting (bulk mode on, 0 selected)

- Checkbox column appears.
- Row click behavior changed.
- "Done" button visible in header.
- `BulkActionBar` not shown (no selection yet).

### Selecting (bulk mode on, N > 0 selected)

- N rows highlighted.
- `BulkActionBar` visible at bottom.
- Selected rows have `bg-blue-950/40 border-l-2 border-blue-600`.
- Header checkbox is indeterminate if N < total visible, checked if N equals total visible.

### Confirming

Clicking OS Update or App Update in `BulkActionBar` opens a confirm dialog (not the modal — just an inline `window`-style dialog or a small `div` within the bar):

```
Update OS on 3 guests? Running services may restart.
[ Cancel ]  [ Confirm Update ]
```

This is consistent with the existing per-guest confirm dialog pattern in `GuestActions.tsx`.

### Running

`BulkProgressModal` opens. Operations run **sequentially** (not in parallel) to avoid overloading the Proxmox SSH connection. The backend `POST /api/guests/{id}/os-update` endpoint is called one guest at a time, in display order. Each call is awaited before the next starts.

The modal status list updates in real time as each call resolves or rejects.

### Results (all complete)

- "Close" button in modal becomes enabled.
- Summary line shows: "3 done" or "2 done, 1 failed".
- User closes the modal.
- Bulk mode exits.
- Selections are cleared.
- The guest list refreshes (same 4-second delayed refresh used by the single-guest action in `GuestActions.tsx`).

### Error (network failure mid-run)

If a guest's API call throws (network error, 500, etc.), that guest row shows "failed: {message}". The operation continues to the next guest. The close button becomes enabled once all guests are terminal.

---

## Eligibility Rules

These rules determine which selected guests are skippable or should warn the user:

| Action     | Eligible condition                                       |
|------------|----------------------------------------------------------|
| OS Update  | `guest.type === 'lxc'` AND `guest.status === 'running'` |
| App Update | Same as OS Update AND `guest.has_community_script === true` |

Ineligible guests are shown in `BulkProgressModal` as "skipped" without making an API call. The warning chip in `BulkActionBar` counts ineligible guests before the user confirms.

---

## Responsiveness

### Desktop (>= md)

- Checkbox column: 36px fixed, prepended before "Name".
- `BulkActionBar`: single horizontal row at bottom of viewport.
- `BulkProgressModal`: centered, max-width 560px, max-height 70vh with internal scroll.

### Mobile (< md)

- `GuestCard` components (the card list) each get a checkbox in their top-right corner when bulk mode is active. The card's `onClick` toggles selection instead of navigating.
- A "Select all" button appears above the card list (not a header checkbox since there is no table header).
- `BulkActionBar`: full-width, stacks vertically. OS Update and App Update stack on separate rows.
- `BulkProgressModal`: full-screen overlay on mobile (`inset-0`).

---

## Accessibility

### Keyboard Navigation

- "Select" / "Done" button: reachable by Tab, activated by Space or Enter.
- Checkboxes: reachable by Tab, toggled by Space. All checkboxes have explicit `aria-label` ("Select {name}" for rows, "Select all visible guests" for header).
- When bulk mode activates, focus moves to the header checkbox so keyboard-only users can immediately begin selecting.
- When bulk mode exits, focus returns to the "Select" button.
- `BulkActionBar` buttons are reachable by Tab. The bar uses `role="toolbar"` with `aria-label="Bulk actions"`.
- `BulkProgressModal` uses `role="dialog"` with `aria-modal="true"` and `aria-labelledby` pointing to the modal heading. Focus is trapped inside the modal while it is open (standard modal trap: Tab cycles through Close and any focusable elements inside, Escape is blocked while operations are running, enabled after all complete).

### Screen Reader Announcements

- When bulk mode activates: `aria-live="polite"` region announces "Bulk select mode active. Use checkboxes to select guests."
- When selection count changes: the count text in `BulkActionBar` is in an `aria-live="polite"` region so screen readers announce "3 guests selected" on change.
- When a guest's operation status changes in the modal: each status cell uses `aria-live="polite"` so readers announce "pve-jellyfin: done" without interrupting the user.
- When all operations complete: an `aria-live="assertive"` region announces "Bulk update complete. 2 done, 1 failed."

### Color Independence

Status in `BulkProgressModal` is never communicated by color alone:
- Queued: "waiting..." text
- Running: spinner icon + "running..." text
- Done: checkmark character (U+2713) + "done" text
- Failed: X character (U+2717) + error text
- Skipped: dash character + "skipped" text

---

## User Stories and Acceptance Criteria

### Story 1: Select specific guests and run OS Update

**As a** homelab operator
**I want to** select 3 specific LXC containers and update their OS packages in one action
**So that** I do not have to open three separate action menus

**Acceptance criteria:**
- [ ] "Select" button appears in the Dashboard header.
- [ ] Clicking "Select" adds a checkbox column to the table without any other visible change.
- [ ] Checking 3 rows shows "3 guests selected" in the bottom action bar.
- [ ] Clicking "OS Update" in the action bar shows a confirmation dialog.
- [ ] Confirming opens the `BulkProgressModal` and runs `POST /api/guests/{id}/os-update` for each eligible guest sequentially.
- [ ] Each guest's row in the modal updates from "waiting" -> "running..." -> "done" or "failed".
- [ ] Close button is disabled until all 3 guests are terminal.
- [ ] Closing the modal exits bulk mode and refreshes the guest list.

### Story 2: Select all then deselect two

**As a** homelab operator
**I want to** select all guests and then deselect two before running an update
**So that** I can quickly exclude known-problematic guests

**Acceptance criteria:**
- [ ] Clicking the header checkbox when unchecked selects all visible guests.
- [ ] Unchecking two individual row checkboxes changes header checkbox to indeterminate.
- [ ] Action bar count updates in real time: "N guests selected".
- [ ] Running the action only targets the still-selected guests.

### Story 3: Bulk update all guests in a filtered view

**As a** homelab operator
**I want to** filter to "outdated" guests and update all of them
**So that** I can maintain consistency across a subset without manual row-by-row action

**Acceptance criteria:**
- [ ] Applying a status filter to "Outdated" shows only outdated guests.
- [ ] Clicking the header checkbox selects all currently visible (filtered) guests.
- [ ] The action bar shows the correct count matching the filtered result.
- [ ] Ineligible guests (not LXC or not running) within the selection are shown as "skipped" in the modal with no API call made.
- [ ] Previously selected guests that are outside the current filter are tracked separately and shown in the count as "(N not visible in current filter)".

### Story 4: App Update for eligible guests

**As a** homelab operator
**I want to** bulk-run the community updater script on all guests that support it
**So that** I do not have to open each one individually

**Acceptance criteria:**
- [ ] "App Update" button in the action bar is enabled when at least one selected guest has `has_community_script === true`.
- [ ] Guests with `has_community_script !== true` are shown as "skipped" in the progress modal.
- [ ] Button shows tooltip "None of the selected guests support app updates" when disabled.

---

## State Machine Summary

```
IDLE
  -> [click Select]  -> SELECTING_EMPTY

SELECTING_EMPTY
  -> [check a row]   -> SELECTING_WITH_ITEMS
  -> [click Done]    -> IDLE
  -> [Escape]        -> IDLE

SELECTING_WITH_ITEMS
  -> [uncheck last]  -> SELECTING_EMPTY
  -> [click Done]    -> IDLE
  -> [Escape]        -> IDLE
  -> [click OS Update or App Update] -> CONFIRMING

CONFIRMING
  -> [Cancel]        -> SELECTING_WITH_ITEMS
  -> [Confirm]       -> RUNNING

RUNNING
  -> [all terminal]  -> RESULTS

RESULTS
  -> [Close modal]   -> IDLE
```

---

## Files to Create or Modify

| File | Change |
|------|--------|
| `frontend/src/components/BulkActionBar.tsx` | New component |
| `frontend/src/components/BulkProgressModal.tsx` | New component |
| `frontend/src/components/Dashboard.tsx` | Add `bulkMode` state, selection set, SelectToggle button, pass selection props down |
| `frontend/src/components/GuestRow.tsx` | Accept `bulkMode`, `selected`, `onToggleSelect` props; render checkbox cell; change row click behavior |
| `frontend/src/components/FilterBar.tsx` | No change required |
| `frontend/src/components/GuestActions.tsx` | No change required |
| `frontend/src/api/client.ts` | No change required (reuses existing `osUpdateGuest` / `appUpdateGuest`) |
