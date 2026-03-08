# proxmon UX Specification

**Version**: 1.0
**Date**: 2026-03-08
**Audience**: Frontend/backend engineers, homelab community contributors

---

## 1. Design Principles

| Principle | Implication |
|---|---|
| Dense information display | Compact table rows, no excessive padding, data-first layout |
| Fast to scan | Status badges leftmost in row, color-coded, no icon-only states |
| No unnecessary chrome | No sidebars, no modals for reads, no skeleton loaders beyond a single spinner |
| Accessible | Full keyboard navigation, ARIA roles/labels, sufficient contrast ratios |
| Dark mode first | Background: `#0f1117`, surface: `#1a1d27`, accent: `#3b82f6` (blue-500) |

---

## 2. Screen Inventory

| Screen | Route | Description |
|---|---|---|
| Dashboard | `/` | Main table of all guests and their app/version status |
| Per-App Detail | `/guest/:id` | Detail view for a single guest's detected app and version history |
| Settings | `/settings` | Read-only display of Proxmox connection and plugin config |
| Error / Empty States | (inline) | Shown within Dashboard and Detail page contexts |

---

## 3. Global Shell

### Components (present on all screens)

- **Top navigation bar** (fixed, `48px` tall)
  - Left: `proxmon` wordmark (plain text, monospace font)
  - Right: Settings link (gear icon + label "Settings"), no other nav items
- **No sidebar**: full-width content area
- **No footer**

### Global states

| State | Behavior |
|---|---|
| Proxmox unreachable | Full-width error banner below navbar, dismissible, persists until resolved |
| Loading (initial) | Centered spinner with text "Connecting to Proxmox..." |
| JS error boundary | Fallback panel with error message and "Reload" button |

---

## 4. Screen 1: Dashboard

### 4.1 Layout

```
+----------------------------------------------------------+
| proxmon                                       [Settings] |
+----------------------------------------------------------+
| [!] Proxmox unreachable: <endpoint> — <error detail>  X |  <- conditional error banner
+----------------------------------------------------------+
| Last refreshed: 2026-03-08 14:32:01   [Refresh]  [OK 42]|  <- header row
+----------------------------------------------------------+
| [Search apps...]  [Status v]  [Type v]                   |  <- filter bar
+----------------------------------------------------------+
| Guest Name  | Type | App       | Installed | Latest | Status  | Last Checked | Actions |
|-------------|------|-----------|-----------|--------|---------|--------------|---------|
| web-01      | LXC  | nginx     | 1.24.0    | 1.27.0 | OUTDATED| 14:31:58     | [View]  |
| db-01       | LXC  | postgres  | 16.2      | 16.2   | OK      | 14:31:59     | [View]  |
| monitor-vm  | VM   | —         | —         | —      | UNKNOWN | 14:32:00     | [View]  |
| ...         |      |           |           |        |         |              |         |
+----------------------------------------------------------+
| Showing 12 of 42 guests                                  |  <- pagination/count
+----------------------------------------------------------+
```

### 4.2 Component Breakdown

#### Header Row

| Element | Detail |
|---|---|
| "Last refreshed" timestamp | ISO-like local time, updated after each successful poll or manual refresh |
| Refresh button | Label: "Refresh". On click: disables button, shows inline spinner inside button, re-enables on completion. Keyboard: `Space`/`Enter` |
| Health badge | Pill badge. States: `All OK` (green), `N outdated` (red), `N unknown` (gray), or combinations |

#### Filter Bar

| Element | Detail |
|---|---|
| Search input | Placeholder: "Search apps or guests...". Filters `Guest Name` and `App Detected` columns client-side. Debounced 200ms. ARIA label: "Filter guests" |
| Status dropdown | Options: All / Outdated / Up to date / Unknown. Default: All |
| Type dropdown | Options: All / LXC / VM. Default: All |
| Active filter chips | When filters are active, show dismissible chips below the bar (e.g., "Status: Outdated x") |

#### Guest Table

| Column | Width | Notes |
|---|---|---|
| Guest Name | 20% | Truncate with ellipsis if overflow. Full name on hover (native title attr) |
| Type | 6% | Badge: `LXC` (blue outline), `VM` (purple outline) |
| App Detected | 16% | App name string, or em-dash (`—`) if none detected |
| Installed Version | 12% | Semver string or `—` |
| Latest Version | 12% | Semver string or `—` |
| Status | 10% | Badge: see Status Badges below |
| Last Checked | 14% | Relative time (e.g., "2 min ago") with absolute on hover |
| Actions | 10% | Single "View" link button |

Full row is clickable (links to detail page). "View" button is redundant affordance for discoverability.

**Row keyboard navigation**: rows are `<tr tabindex="0">`. `Enter` on a row navigates to detail. `Tab` moves to next row.

#### Status Badges

| Status | Label | Color | Background |
|---|---|---|---|
| Up to date | `OK` | `#22c55e` (green-500) | `#14532d` (green-900) |
| Outdated | `OUTDATED` | `#ef4444` (red-400) | `#7f1d1d` (red-900) |
| Unknown | `UNKNOWN` | `#9ca3af` (gray-400) | `#1f2937` (gray-800) |
| Error | `ERROR` | `#f97316` (orange-400) | `#431407` (orange-950) |

All badges: `font-size: 11px`, `font-weight: 600`, `border-radius: 4px`, `padding: 2px 6px`.

#### Empty State

Displayed when:
- No guests discovered yet
- All guests filtered out

```
+------------------------------------------+
|                                          |
|   No guests found.                       |
|                                          |
|   proxmon has not discovered any         |
|   Proxmox guests yet.                    |
|                                          |
|   Check your Proxmox connection in       |
|   Settings, then click Refresh.          |
|                                          |
|   [Go to Settings]   [Refresh]           |
|                                          |
+------------------------------------------+
```

For filtered empty state: "No guests match your filters. [Clear filters]"

#### Loading State (initial load)

- Table area replaced with centered spinner + text: "Loading guests..."
- Header row (refresh button) disabled until load completes

#### Refresh In-Progress State

- Table rows remain visible (no flicker)
- Refresh button: spinner inside, label changes to "Refreshing...", disabled
- Rows that complete update in-place; no full table re-render flash

### 4.3 Interaction Flow

```
User lands on Dashboard
  -> Initial load spinner shown
  -> Proxmox reachable?
       YES -> Fetch guest list -> Render table -> Show health badge
       NO  -> Show error banner + empty state with Settings CTA

User clicks row / "View" button
  -> Navigate to /guest/:id

User changes Status filter
  -> Client-side filter applied immediately
  -> URL query param updated (?status=outdated) for shareability

User clicks Refresh
  -> Polls Proxmox API
  -> Updates rows in-place
  -> Updates "Last refreshed" timestamp
```

---

## 5. Screen 2: Per-App Detail Page

### 5.1 Layout

```
+----------------------------------------------------------+
| proxmon                                       [Settings] |
+----------------------------------------------------------+
| < Dashboard > web-01                                     |  <- breadcrumb
+----------------------------------------------------------+
| web-01                                    [OUTDATED]     |  <- title + status
| LXC  |  ID: 101  |  Running  |  Tags: web, prod         |
+----------------------------------------------------------+
| APP DETECTION                                            |
| App: nginx                                               |
| Detection method: name match                             |
| Plugin: nginx-detector v1.2                              |
+----------------------------------------------------------+
| VERSION STATUS                                           |
| Installed:  1.24.0                                       |
| Latest:     1.27.0   [View release notes ->]             |
| Checked:    2026-03-08 14:31:58                          |
+----------------------------------------------------------+
| VERSION HISTORY                            (last 10)     |
| Timestamp           | Installed | Latest | Status        |
|---------------------|-----------|--------|---------------|
| 2026-03-08 14:31:58 | 1.24.0    | 1.27.0 | OUTDATED      |
| 2026-03-07 14:31:02 | 1.24.0    | 1.26.3 | OUTDATED      |
| 2026-03-06 14:30:58 | 1.24.0    | 1.24.0 | OK            |
+----------------------------------------------------------+
| RAW DETECTION OUTPUT               [Expand v]            |
| (collapsed by default)                                   |
+----------------------------------------------------------+
| [< Back to Dashboard]                                    |
+----------------------------------------------------------+
```

### 5.2 Component Breakdown

#### Breadcrumb

- `Dashboard` is a link back to `/`
- Current guest name is plain text (not a link)
- ARIA: `<nav aria-label="Breadcrumb">`, current item has `aria-current="page"`

#### Guest Metadata Row

| Field | Source |
|---|---|
| Guest Name | Proxmox display name |
| Type | LXC or VM badge (same as table) |
| ID | Proxmox VMID |
| Running status | `Running` (green dot) / `Stopped` (gray dot) |
| Tags | Proxmox tags rendered as gray chips |

#### App Detection Panel

| Field | Notes |
|---|---|
| App name | Plain string |
| Detection method | One of: `name match`, `tag match`, `docker inspect`, `command probe` |
| Plugin | Plugin name + version |
| Detection note | Optional: shown when detection was ambiguous or partial |

When no app detected, panel shows: "No app detected for this guest." with muted text explaining possible reasons (guest stopped, no supported apps, detection error).

#### Version Status Panel

| Element | Notes |
|---|---|
| Installed version | Semver, large text |
| Latest version | Semver, large text. If outdated: latest shown in green, diff highlighted |
| Release link | External link to GitHub releases (or upstream). Opens in new tab. ARIA label: "View release notes for [app] [version] (opens in new tab)" |
| Last checked | Absolute datetime |

When versions are equal: "Up to date" confirmation text in green.

When latest version unknown: "Unable to fetch latest version" in muted text with reason if available.

#### Version History Table

- Last 10 entries, newest first
- Columns: Timestamp | Installed | Latest | Status
- Status badges same as dashboard
- No pagination in MVP; truncated to 10 rows

#### Raw Detection Output

- Collapsed by default
- Toggle button: "Show raw output" / "Hide raw output"
- Content: `<pre>` block, monospace, scrollable (max-height: 300px, overflow-y: auto)
- ARIA: `aria-expanded` on toggle button, associated `id` on content panel

#### Back Button

- Label: "Back to Dashboard"
- Keyboard: focusable, `Enter`/`Space` navigates
- Position: bottom of page AND breadcrumb provides equivalent navigation

### 5.3 Interaction Flow

```
User arrives from Dashboard row click
  -> Breadcrumb shows Dashboard > [Guest Name]
  -> Page loads guest detail from /api/guests/:id
  -> All panels render; raw output collapsed

User clicks "View release notes"
  -> Opens GitHub release URL in new tab

User toggles "Raw Detection Output"
  -> Panel expands/collapses
  -> Button label and aria-expanded update

User clicks "Back to Dashboard" or breadcrumb "Dashboard"
  -> Navigates to /
  -> Filter state preserved via URL params (browser back also works)
```

---

## 6. Screen 3: Settings Page

### 6.1 Layout

```
+----------------------------------------------------------+
| proxmon                                       [Settings] |
+----------------------------------------------------------+
| Settings                                                 |
| (read-only in this version)                              |
+----------------------------------------------------------+
| PROXMOX CONNECTION                                       |
| Endpoint:    https://192.168.1.10:8006                   |
| Token name:  proxmon@pve!****                (masked)    |
| Status:      [Connected] / [Unreachable]                 |
+----------------------------------------------------------+
| DISCOVERY                                                |
| Poll interval:  5 minutes                                |
| Guest types:    LXC, VM                                  |
| Scan scope:     All nodes                                |
+----------------------------------------------------------+
| PLUGINS (DETECTORS)                                      |
| nginx-detector       v1.2    [Enabled]                   |
| postgres-detector    v1.0    [Enabled]                   |
| docker-detector      v0.8    [Enabled]                   |
| apt-probe            v1.1    [Disabled]                  |
+----------------------------------------------------------+
| Config file: /etc/proxmon/config.yaml                    |
+----------------------------------------------------------+
```

### 6.2 Component Breakdown

#### Proxmox Connection Section

| Field | Notes |
|---|---|
| Endpoint | Full URL string |
| Token name | Show prefix up to `!`, then mask remainder with `****`. Never show token secret |
| Status | Badge: `Connected` (green) or `Unreachable` (red) with last-tested time |

#### Discovery Section

Display-only. Fields match backend config keys. No controls.

#### Plugin List

Each row: plugin name | version | enabled/disabled badge.

Disabled plugins shown with muted text. No toggle controls in MVP.

Note at bottom: "To change settings, edit `config.yaml` and restart proxmon."

---

## 7. Error and Empty States

### 7.1 Proxmox Unreachable Banner

Shown globally (below navbar) when backend cannot reach Proxmox.

```
[!] Cannot connect to Proxmox at https://192.168.1.10:8006 — Connection refused. Check your config in Settings.  [x]
```

- Color: red background `#7f1d1d`, white text
- Dismissible with `x` button (dismissed until next page load or successful connection)
- ARIA: `role="alert"`, `aria-live="assertive"`

### 7.2 Guest with Unknown App

- Table row: App Detected column shows `—` (em-dash), Status badge shows `UNKNOWN` (gray)
- Detail page: "No app detected for this guest." panel with explanation

### 7.3 Detection Failure

- Status badge: `ERROR` (orange)
- Table row: tooltip on status badge (on hover and focus) with short error string
- Detail page: error message in App Detection panel, raw output available for debugging

### 7.4 Version Fetch Failure

- Latest Version column shows `—` with orange dot indicator
- Tooltip: "Could not fetch latest version: [reason]"
- Detail page: "Unable to fetch latest version" with reason text

### 7.5 Filtered Empty State

- Shown when filter/search returns no rows
- Message: "No guests match your filters."
- CTA: "Clear all filters" button (resets all filter controls and URL params)

### 7.6 Network Error (Frontend to Backend)

- Inline error inside the table area: "Failed to load data. [Retry]"
- Does not replace the navbar
- ARIA: `role="alert"`

---

## 8. User Stories and Acceptance Criteria

### US-01: View all guests at a glance
**As a** homelab user,
**I want** to see all my Proxmox guests in a table with version status,
**So that** I can quickly identify what needs updating.

**Acceptance criteria:**
- [ ] Table loads within 3 seconds on local network
- [ ] Each row shows guest name, type, detected app, installed/latest version, status badge, and last checked time
- [ ] Status badges are color-coded and use accessible contrast ratios
- [ ] Table is keyboard navigable (Tab to move rows, Enter to open detail)

### US-02: Filter guests by status
**As a** homelab user,
**I want** to filter by status (outdated/ok/unknown),
**So that** I can focus on guests that need attention.

**Acceptance criteria:**
- [ ] Status dropdown filters table immediately (no server round-trip)
- [ ] Active filter is reflected in URL query param
- [ ] Empty state shown when no rows match with clear-filters CTA
- [ ] Filter state is preserved on browser back navigation

### US-03: View detail for a guest
**As a** homelab user,
**I want** to click a guest and see version comparison and detection details,
**So that** I can understand why it's flagged and where to get the update.

**Acceptance criteria:**
- [ ] Breadcrumb shows Dashboard > [Guest Name]
- [ ] Installed vs latest version displayed prominently
- [ ] Link to GitHub release opens in new tab
- [ ] Version history table shows last 10 checks
- [ ] Raw detection output is collapsible

### US-04: Manually refresh data
**As a** homelab user,
**I want** to trigger a manual refresh,
**So that** I can get current data without waiting for the next poll.

**Acceptance criteria:**
- [ ] Refresh button is always visible in dashboard header
- [ ] Button shows loading state during refresh
- [ ] "Last refreshed" timestamp updates after completion
- [ ] Rows update in-place (no full table flash)

### US-05: Understand connection errors
**As a** homelab user,
**I want** to see a clear error when Proxmox is unreachable,
**So that** I can diagnose the issue quickly.

**Acceptance criteria:**
- [ ] Error banner shows endpoint and error reason
- [ ] Banner links to Settings page
- [ ] Banner is dismissible
- [ ] Banner uses `role="alert"` for screen readers

---

## 9. Accessibility Notes

### Keyboard Navigation

| Interaction | Key |
|---|---|
| Move between table rows | `Tab` / `Shift+Tab` |
| Open guest detail | `Enter` on focused row |
| Activate buttons | `Enter` or `Space` |
| Close/dismiss banner | `Enter` or `Space` on X button |
| Toggle raw output | `Enter` or `Space` on toggle button |
| Navigate dropdowns | Arrow keys, `Enter` to select, `Escape` to close |

### ARIA Requirements

| Element | ARIA |
|---|---|
| Error banner | `role="alert"` `aria-live="assertive"` |
| Refresh button (loading) | `aria-disabled="true"` `aria-label="Refreshing..."` |
| Status badges | `aria-label="Status: Outdated"` (not color-only) |
| Collapsible raw output | `aria-expanded="true/false"` on button, `aria-controls="[panel-id]"` |
| Breadcrumb nav | `<nav aria-label="Breadcrumb">`, current: `aria-current="page"` |
| Guest table | `<table>` with `<caption>` "Proxmox guests", proper `<th scope="col">` |
| External links | `aria-label="View release notes for nginx 1.27.0 (opens in new tab)"` |
| Type badges | `aria-label="Type: LXC"` |
| Filter inputs | `aria-label` on each control, announce filter result count with `aria-live="polite"` |

### Color Contrast

All text/background combinations must meet WCAG AA (4.5:1 for normal text, 3:1 for large text). Status badge text on dark backgrounds must be verified with tooling before implementation.

### Focus Management

- On navigation to detail page, focus moves to page `<h1>` (guest name)
- On navigation back to dashboard, focus returns to the row that was activated (use scroll restoration + `focus()`)
- Dismissing error banner returns focus to the element that was focused before the banner appeared, or to the next logical element

---

## 10. Component Reuse Summary

| Component | Used In |
|---|---|
| `StatusBadge` | Dashboard table, Detail page header, Version history table |
| `TypeBadge` (LXC/VM) | Dashboard table, Detail page metadata |
| `ErrorBanner` | Global (all pages) |
| `FilterBar` | Dashboard only |
| `GuestTable` | Dashboard only |
| `Breadcrumb` | Detail page, Settings page |
| `CollapsiblePanel` | Detail page (raw output) |
| `VersionCompare` | Detail page |
| `PluginBadge` | Settings page, Detail page (detection method) |

---

## 11. Out of Scope (MVP)

- User authentication / login
- Settings editing via UI (config is file-based)
- Push notifications or alerts
- Multi-node overview differentiation
- Pagination (assume 50 guests max renders acceptably)
- Light mode
- Mobile-optimized layout (desktop-first, tablet acceptable)
