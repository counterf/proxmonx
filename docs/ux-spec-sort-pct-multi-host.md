# UX Spec: Column Sorting, pct exec Detection, Multi-Host Support

**Project:** proxmon
**Date:** 2026-03-09
**Scope:** Three related features for the dashboard and settings pages.

---

## Table of Contents

1. [Feature 1 -- Dashboard Column Sorting](#feature-1----dashboard-column-sorting)
2. [Feature 2 -- pct exec Version Discovery](#feature-2----pct-exec-version-discovery)
3. [Feature 3 -- Multiple Proxmox Hosts](#feature-3----multiple-proxmox-hosts)
4. [Shared Accessibility Notes](#shared-accessibility-notes)
5. [Component Hierarchy Changes](#component-hierarchy-changes)
6. [Backend Contract Summary](#backend-contract-summary)

---

## Feature 1 -- Dashboard Column Sorting

### User Story

As a user with many guests, I want to click column headers to sort the table so I can quickly find outdated apps or group by host without scrolling and scanning manually.

### Acceptance Criteria

- Clicking a sortable column header sorts the table by that column ascending.
- Clicking the same header again reverses the sort order (descending).
- Clicking a different header resets to ascending on the new column.
- Default sort on page load: Guest Name ascending.
- Sort state is reflected visually on the active header (arrow indicator).
- Inactive headers show a neutral double-arrow to signal they are sortable.
- Sort state is preserved across filter changes (search, status, type, host).
- Sort is applied after filtering (sort the filtered result set).
- Mobile card view: no column headers exist; cards use the same sorted order as the table.
- Sort state is NOT persisted to the URL or localStorage (resets on navigation). This keeps the implementation minimal; revisit if users request persistence.

### Sortable Columns

| Column         | Sort Key on `GuestSummary`         | Sort Type       |
|----------------|------------------------------------|-----------------|
| Guest Name     | `name`                             | string (locale) |
| Status         | `update_status`                    | enum order      |
| App            | `app_name` (nulls last)            | string (locale) |
| Installed      | `installed_version` (nulls last)   | semver-ish      |
| Latest         | `latest_version` (nulls last)      | semver-ish      |
| Host           | `host_label` (Feature 3)           | string (locale) |
| Type           | `type`                             | string          |

Status enum sort order (ascending): `outdated` > `unknown` > `up-to-date`.
Rationale: surfaces problems first, matching the user's priority.

Version sort: compare version strings by splitting on `.` and comparing numeric segments. Fall back to locale string if parsing fails. Nulls always sort last regardless of direction.

### Wireframe -- Desktop Table Header

```
+--------------------------------------------------------------------------+
| GUEST NAME  [v]  TYPE    APP  [--]  INSTALLED [--]  LATEST [--]  STATUS [--] ... |
+--------------------------------------------------------------------------+
  ^                          ^
  Active sort col            Inactive sortable col
  shows "v" (desc) or        shows "--" (neutral double arrow)
  "^" (asc)
```

Concrete header cell anatomy:

```
+-----------------------------+
| GUEST NAME         [^]      |
|  ^col label         ^icon   |
+-----------------------------+
  cursor: pointer
  hover: bg-gray-800/60
  active: text-white (vs default text-gray-400)
```

Icon states per column:
- Column is inactive sortable: `↕` (text-gray-600, aria-hidden)
- Column sorted ascending: `↑` (text-blue-400, aria-hidden)
- Column sorted descending: `↓` (text-blue-400, aria-hidden)
- Column is not sortable (Last Checked, Actions): no icon, no pointer cursor

### State Shape

Add to `Dashboard` component state:

```typescript
type SortKey = 'name' | 'type' | 'app_name' | 'installed_version' |
               'latest_version' | 'update_status' | 'host_label';
type SortDir = 'asc' | 'desc';

const [sortKey, setSortKey] = useState<SortKey>('name');
const [sortDir, setSortDir] = useState<SortDir>('asc');
```

Handler (replaces direct `filtered` consumption):

```typescript
function handleSort(key: SortKey) {
  if (key === sortKey) {
    setSortDir(d => d === 'asc' ? 'desc' : 'asc');
  } else {
    setSortKey(key);
    setSortDir('asc');
  }
}

const sorted = useMemo(() => sortGuests(filtered, sortKey, sortDir), [filtered, sortKey, sortDir]);
```

The `sortGuests` pure function lives in a new `frontend/src/utils/sort.ts` module.

### Component Changes

**`Dashboard.tsx`**
- Add `sortKey`, `sortDir` state.
- Replace `filtered` with `sorted` when rendering rows and cards.
- Pass `sortKey`, `sortDir`, `onSort` down to a new `GuestTableHeader` component.

**New: `frontend/src/components/GuestTableHeader.tsx`**
- Renders the `<thead>` row.
- Accepts `sortKey`, `sortDir`, `onSort`.
- Each sortable `<th>` is a `<button>` wrapped inside the `<th>` (or the `<th>` itself acts as a button via `role="columnheader"` + `onClick`).
- Use `aria-sort="ascending" | "descending" | "none"` on each `<th>`.

**`GuestRow.tsx`**
- No change to `GuestTableRow`. The row is unaware of sort.
- `GuestCard` renders in whatever order it receives; no change needed.

**New: `frontend/src/utils/sort.ts`**
- `sortGuests(guests: GuestSummary[], key: SortKey, dir: SortDir): GuestSummary[]`

### All States

| State | Appearance |
|-------|------------|
| Default (name asc) | "GUEST NAME" header shows `↑` in blue-400; all others show `↕` in gray-600 |
| Sorted desc | Active header shows `↓` |
| Table empty (no guests) | Empty state message shown; header row not rendered |
| Filtered to zero | "No guests match your filters" shown; sort controls not visible |
| Loading | Spinner shown; header not rendered |

### Accessibility

- Each sortable `<th>` has `aria-sort="ascending" | "descending" | "none"`.
- Non-sortable columns have no `aria-sort` attribute.
- Sort toggle is keyboard-accessible: `<th>` elements that are sortable receive `tabIndex={0}` and respond to `Enter` and `Space`.
- Screen reader announcement: `aria-sort` on the `<th>` is sufficient; no additional live region needed.
- Icon is `aria-hidden="true"` in all cases; the `aria-sort` attribute communicates sort state to AT.

---

## Feature 2 -- pct exec Version Discovery

### Background

`pct exec <vmid> -- <cmd>` runs a command inside an LXC container directly from the Proxmox host, without needing SSH into the guest. This is faster and works even when SSH is not exposed on the guest. It requires the backend to have access to the Proxmox host's shell (typically via SSH to the Proxmox node itself, not the guest).

No new dashboard UI surface is needed. The only user-facing changes are:
1. A per-host toggle in Settings to enable this method.
2. A subtle indicator on version cells showing which detection method was used.

### User Stories

**US-2a.** As an admin, I want to enable `pct exec` for version discovery per host so I can get version data without exposing SSH on every guest.

**US-2b.** As a user, I want to see how a version was detected (pct exec vs SSH vs HTTP) so I can trust the data and debug failures.

### Acceptance Criteria

- Settings: each host entry (Feature 3) has a toggle "Use pct exec for version discovery".
- When enabled, the backend uses `pct exec <vmid>` as the primary version probe for LXC containers on that host.
- VM guests on that host are not affected (pct exec is LXC-only); they fall back to SSH or HTTP.
- Dashboard: version cells optionally show a small badge indicating detection method.
- Badge is tooltip-only on desktop (visible on hover); on mobile it is always visible as a small text label.
- Badge is only shown when `detection_method` is present on the guest data. If absent, show nothing.
- Badge does not appear for guests where version is `null` (unknown).

### Settings Toggle (within each host card -- see Feature 3)

```
+--------------------------------------------+
| PROXMOX HOST                               |
|  ...host fields...                         |
|                                            |
|  VERSION DISCOVERY                         |
|  [toggle] Use pct exec for LXC guests      |
|           Runs commands inside containers  |
|           via the Proxmox host shell.      |
|           SSH must be configured for the  |
|           Proxmox node itself.             |
+--------------------------------------------+
```

Toggle ID: `host-{index}-pct-exec-enabled`
Field name in host config: `pct_exec_enabled: boolean`
Default: `false`

### Version Cell Badge

`GuestSummary` already exposes `detection_method` via `GuestDetail`. For the dashboard table we need `detection_method` surfaced on `GuestSummary` (a backend change -- see Backend Contract section).

Badge rendering rules:

| `detection_method` value | Badge label | Badge color class |
|--------------------------|-------------|-------------------|
| `pct_exec`               | `pct`       | `bg-violet-900 text-violet-400` |
| `ssh`                    | `ssh`       | `bg-gray-800 text-gray-500` |
| `http`                   | (no badge)  | -- |
| `null` / absent          | (no badge)  | -- |

Rationale: HTTP is the default and expected; no badge reduces noise. `pct` and `ssh` are non-obvious and worth surfacing.

Badge anatomy in the Installed/Latest cell:

```
  v1.2.3  [pct]
           ^--- 10px badge, inline after version string
```

On hover (desktop), a tooltip reads: "Version detected via pct exec" or "Version detected via SSH".

### States

| State | Installed cell | Latest cell |
|-------|---------------|-------------|
| HTTP detection, version known | `v1.2.3` (no badge) | `v1.3.0` (no badge) |
| pct exec detection | `v1.2.3 [pct]` | `v1.3.0` (no badge -- latest always from GitHub) |
| SSH detection | `v1.2.3 [ssh]` | `v1.3.0` (no badge) |
| Version unknown | `--` (no badge) | `--` (no badge) |

Note: Latest version always comes from GitHub; it never carries a detection badge.

### Component Changes

- `GuestTableRow`: update the Installed version `<td>` to render the badge inline when `detection_method` is `pct_exec` or `ssh`.
- `GuestCard`: render the badge after the version string in the version row.
- New small inline component: `DetectionBadge` (can live in `GuestRow.tsx` or its own file).

---

## Feature 3 -- Multiple Proxmox Hosts

### User Stories

**US-3a.** As a user with multiple Proxmox nodes, I want to configure them all in proxmon so I see all my guests in one dashboard.

**US-3b.** As a user, I want to filter the dashboard by host so I can focus on one cluster at a time.

**US-3c.** As a user, I want to add and remove hosts without losing existing host configurations.

### Acceptance Criteria

- Settings: "Proxmox Connection" section is replaced by a "Proxmox Hosts" section.
- Each host is a collapsible card with: label, host URL, token ID, token secret, node name, SSL verify, SSH credentials, pct exec toggle.
- At least one host is required. The Save button is disabled and shows an inline error if zero hosts are configured.
- The "Test Connection" button is per-host.
- Adding a host appends a blank card at the bottom, expanded by default.
- Removing a host shows a confirmation inline ("Remove this host?  Yes / Cancel") before deleting.
- Dashboard: "Host" column added to table (after Guest Name, before Type).
- Dashboard: host filter dropdown added to FilterBar.
- "All hosts" is the default filter selection.
- Host column shows the configured `label` for that host (falls back to the host URL if label is blank).
- The existing single-host setup (`proxmox_host`, `proxmox_token_id`, etc.) is migrated automatically on first load of the new settings schema. The migrated host receives the label "Default".

### Settings -- Proxmox Hosts Section Wireframe

```
PROXMOX HOSTS
+----------------------------------------------------------+
|  [+] Add host                                            |
+----------------------------------------------------------+
|  v  Home Lab  [Test] [x Remove]                          |
|  +-------------------------------------------------+     |
|  | Label *       [Home Lab________________]        |     |
|  | Host URL *    [https://192.168.1.10:8006______] |     |
|  | Token ID *    [root@pam!proxmon_______________] |     |
|  | Token Secret  [**************************] [o]  |     |
|  | Node Name *   [pve_____________________]        |     |
|  | [toggle] Verify SSL                             |     |
|  |                                                 |     |
|  | SSH CREDENTIALS                                 |     |
|  | [toggle] Enable SSH                             |     |
|  |   Username    [root___________________]         |     |
|  |   Auth        (o) Key file  ( ) Password        |     |
|  |   Key path    [/root/.ssh/id_ed25519__]         |     |
|  |                                                 |     |
|  | VERSION DISCOVERY                               |     |
|  | [toggle] Use pct exec for LXC guests            |     |
|  +-------------------------------------------------+     |
|                                                          |
|  >  Office Server  [Test] [x Remove]        (collapsed)  |
+----------------------------------------------------------+
```

Legend: `v` = expanded chevron, `>` = collapsed chevron, `[o]` = show/hide toggle, `*` = required.

### Host Card Interaction States

| State | Visual |
|-------|--------|
| Collapsed (valid) | Shows label + [Test] + [x Remove], chevron right |
| Collapsed (has errors) | Red left border on card, label in amber |
| Expanded | Full form visible, chevron down |
| Removing (awaiting confirm) | Inline "Remove this host? [Yes] [Cancel]" below card, Remove button disabled |
| Saving | All inputs in card are `disabled`, Test button disabled |
| Test pending | Test button shows spinner |
| Test success | Green inline text "Connected. Node: pve (version 8.x)" below button |
| Test failure | Red inline text with error message |
| Only one host | Remove button is hidden (cannot remove the last host) |

### Empty State (zero hosts -- should not be reachable normally)

```
+----------------------------------------------------------+
|  No Proxmox hosts configured.                            |
|  [+ Add your first host]                                 |
+----------------------------------------------------------+
```

This state appears only if someone clears all hosts before saving. Save is blocked.

### Dashboard -- Host Column and Filter

#### Table header change (after Feature 1 integration)

```
| GUEST NAME [^] | HOST [--] | TYPE | APP [--] | INSTALLED [--] | LATEST [--] | STATUS [--] | LAST CHECKED | ACTIONS |
```

Host column width: ~12%, same style as existing type/status columns.

#### FilterBar additions

The host filter is a `<select>` added between the type filter and the search input group. When only one host is configured, the select is hidden (not useful).

```
FilterBar (multi-host):

[ Search...                ] [ All statuses v ] [ All types v ] [ All hosts v ]

Active filters:
  Host: Home Lab [x]   Status: outdated [x]   ...
```

Host filter chip label: "Host: {label}".

### State Shape Changes

**`GuestSummary` type** gains:

```typescript
host_id: string;      // opaque ID matching the host config entry
host_label: string;   // display label for the host
```

**New host config type** (in `types/index.ts`):

```typescript
export interface ProxmoxHostConfig {
  id: string;                  // uuid, generated client-side on add
  label: string;
  host: string;                // URL
  token_id: string;
  token_secret: string | null; // null = masked / unchanged
  node: string;
  verify_ssl: boolean;
  ssh_enabled: boolean;
  ssh_username: string;
  ssh_key_path: string | null;
  ssh_password: string | null; // null = masked / unchanged
  pct_exec_enabled: boolean;
}
```

**`FullSettings` / `SettingsSaveRequest`** replace single-host fields with:

```typescript
hosts: ProxmoxHostConfig[];
```

The old top-level `proxmox_host`, `proxmox_token_id`, etc. fields are removed from the type after migration. Backend handles backward compat during migration.

**Dashboard state** gains:

```typescript
const [hostFilter, setHostFilter] = useState<string>('all');
```

`updateFilter('host', value)` syncs to URL as `?host=<id>`.

### Settings Component Changes

**`Settings.tsx`**
- Replace the `FormData` fields `proxmox_host`, `proxmox_token_id`, `proxmox_token_secret`, `proxmox_node`, `verify_ssl`, and the SSH block with a `hosts: ProxmoxHostConfig[]` array in state.
- The SSH block within `Settings.tsx` moves inside each host card.
- `validate()` checks: at least 1 host; each host has label, host URL, token_id, node.
- The existing `changedTokenSecrets` ref becomes a `Set<string>` keyed by host ID.

**New: `frontend/src/components/settings/HostCard.tsx`**
- Props: `host: ProxmoxHostConfig`, `index: number`, `onUpdate`, `onRemove`, `onTest`, `canRemove: boolean`, `disabled: boolean`.
- Internal state: `expanded`, `removing`, `testResult`, `testLoading`, `authMethod`.
- Renders the full host form when expanded.
- Calls `onTest(host)` which returns `Promise<ConnectionTestResult>`.

**New: `frontend/src/components/settings/HostList.tsx`**
- Props: `hosts: ProxmoxHostConfig[]`, `onChange`, `changedSecrets`, `disabled`.
- Renders the "PROXMOX HOSTS" section header, the [+ Add host] button, and a list of `HostCard` components.
- "Add host" generates a new `ProxmoxHostConfig` with a random `id` and all other fields blank, pushes it to the array, and scrolls it into view.

**`FilterBar.tsx`** changes:
- New prop: `hosts: Array<{ id: string; label: string }>`
- New prop: `hostFilter: string`
- New prop: `onHostChange: (value: string) => void`
- Renders the host `<select>` only when `hosts.length > 1`.
- Active filter chip for host uses the host label (not the ID).

**`Dashboard.tsx`** changes:
- Reads available hosts from either the settings API or derives unique hosts from the guest list.
- Passes host filter props to `FilterBar`.
- `filtered` computation gains: `if (hostFilter !== 'all' && g.host_id !== hostFilter) return false`.
- Table header gains the "Host" column (sortable).

**`GuestTableRow`** and **`GuestCard`**:
- `GuestTableRow` adds a `<td>` after the name cell showing `guest.host_label`.
- `GuestCard` adds `host_label` as a small secondary line below the name, shown in `text-gray-500 text-xs` only when more than one host exists. Pass `multiHost: boolean` as a prop.

### Mobile Behavior

On mobile (card layout):
- Host filter is a `<select>` above the card list, same row as status/type filters, visible only when `hosts.length > 1`.
- Each card shows the host label in a small secondary line:
  ```
  +-------------------------------+
  | sonarr-lxc          [outdated]|
  | LXC  .  Sonarr                |
  | Home Lab                      |  <- host label, gray-500 xs
  | v4.0.1 -> v4.0.2    5 min ago |
  +-------------------------------+
  ```

---

## Shared Accessibility Notes

### Column Sorting (Feature 1)

- `<th scope="col">` with `aria-sort="ascending" | "descending" | "none"` on every column in the thead.
- Sortable headers have `tabIndex={0}`, respond to `keydown` Enter and Space.
- Sorting does not move focus; the header retains focus so the user can press again to reverse.
- Screen reader reads: "Guest Name, column header, ascending" (from `aria-sort` + `scope`).

### Host List (Feature 3)

- Each host card is a `<section>` or `<div role="group">` with `aria-labelledby` pointing to the label field's value or a heading.
- The expand/collapse button has `aria-expanded` and `aria-controls`.
- Remove confirmation is inline (not a modal) and receives focus when revealed.
- The "Add host" button has a clear label: "Add Proxmox host".
- Password/secret fields use `PasswordField` (existing component) which handles show/hide toggle with proper aria-labels.

### Detection Badge (Feature 2)

- Badge has `title` attribute for tooltip text on desktop.
- Badge has `aria-label="Detected via pct exec"` or similar for screen readers.
- Do not rely on color alone: badge includes a text label (`pct`, `ssh`).

### General

- All new interactive elements maintain a visible focus ring (`focus-visible:outline`).
- Error states are associated with their inputs via `aria-describedby`.
- `aria-live="polite"` on the FilterBar result count (already present) covers announcements when host filter changes.
- Color contrast: all new badge and label colors meet WCAG AA (4.5:1 for text on dark backgrounds).

---

## Component Hierarchy Changes

### Before

```
Dashboard
  FilterBar
  GuestTableRow (desktop)
  GuestCard (mobile)

Settings
  AppConfigSection
    (per-app rows)
```

### After

```
Dashboard
  FilterBar                        <-- gains hostFilter props
  GuestTableHeader (new)           <-- extracted from Dashboard, owns sort UI
  GuestTableRow (updated)          <-- gains host_label cell, DetectionBadge
  GuestCard (updated)              <-- gains host_label line, DetectionBadge

Settings
  HostList (new)                   <-- replaces single-host block
    HostCard (new, 1 per host)     <-- per-host form + SSH + pct exec toggle
      ConnectionTestButton
      PasswordField
      Toggle
      FormField
  AppConfigSection (unchanged)
  (GitHub token, Discovery, Plugins: unchanged)

utils/sort.ts (new)                <-- sortGuests pure function
```

---

## Backend Contract Summary

These are the frontend-facing API changes implied by this spec. Listed for handoff to the backend implementation.

### `GET /api/guests` response -- `GuestSummary` additions

```json
{
  "id": "102",
  "name": "sonarr-lxc",
  "host_id": "uuid-of-host",
  "host_label": "Home Lab",
  "detection_method": "pct_exec",
  ...
}
```

`detection_method` values: `"http"`, `"ssh"`, `"pct_exec"`, or `null`.
`host_id` / `host_label`: present when multi-host is active; may be omitted or a constant value in single-host mode for backward compat.

### `GET /api/settings` and `POST /api/settings` -- host list

Replace flat host fields with:

```json
{
  "hosts": [
    {
      "id": "uuid",
      "label": "Home Lab",
      "host": "https://192.168.1.10:8006",
      "token_id": "root@pam!proxmon",
      "token_secret": "***",
      "node": "pve",
      "verify_ssl": false,
      "ssh_enabled": true,
      "ssh_username": "root",
      "ssh_key_path": "/root/.ssh/id_ed25519",
      "ssh_password": null,
      "pct_exec_enabled": false
    }
  ],
  "poll_interval_seconds": 300,
  "discover_vms": false,
  "github_token": "***",
  "log_level": "INFO",
  "app_config": {}
}
```

Secret masking rules (same pattern as existing `_keep_or_replace()`):
- `token_secret` and `ssh_password` in GET responses are returned as `"***"` when set.
- POST: `null` value means "keep existing"; any other value (including empty string) replaces the stored value.
- Per-host secrets are keyed by host `id`.

### `POST /api/test-connection` -- per-host

Request body gains optional `host_id` field. If provided, backend tests that specific stored host. If not provided (legacy), uses first host or flat fields.

### Migration

On first backend startup with the new schema:
- If `proxmox_host` exists in the DB and `hosts` does not, create a single-entry `hosts` array from the existing flat fields with `label = "Default"`.
- The old flat fields remain readable but are ignored by the new code path.
