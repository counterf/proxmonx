# UX Spec: Logo, Clickable App Name, and Responsive Design

**Version**: 1.0
**Date**: 2026-03-08
**Feature**: Logo placement, guest app name as clickable link, full responsive layout
**Audience**: Frontend engineers

---

## 1. Scope

Three interconnected changes:

1. **Logo** — add an SVG icon next to the "proxmon" wordmark in the navbar.
2. **Clickable app name** — make the `app_name` column/field in Dashboard and GuestDetail open the guest's auto-detected web address in a new browser tab.
3. **Responsive design** — all pages must adapt gracefully from 320px (small phone) to 1440px+ (desktop).

---

## 2. Design Tokens (unchanged from existing system)

| Token | Value | Usage |
|---|---|---|
| `background` | `#0f1117` | Page background |
| `surface` | `#1a1d27` | Cards, navbar |
| `blue-500` | `#3b82f6` | Primary accent, links |
| `blue-400` | `#60a5fa` | Interactive link text |
| `gray-400` | `#9ca3af` | Secondary text |
| `gray-800` | `#1f2937` | Borders, hover bg |
| `gray-500` | `#6b7280` | Muted/disabled text |
| Font family | `ui-monospace` stack | Body (existing) |

**Breakpoints** (Tailwind defaults, adopted throughout):

| Name | Min width | Usage |
|---|---|---|
| `sm` | 640px | Filter bar layout change |
| `md` | 768px | Table re-appears, card view off |
| `lg` | 1024px | Full table columns |
| `xl` | 1280px | Max content width (`max-w-7xl`) |

---

## 3. Change 1 — App Logo in Navbar

### 3.1 Behavior

- The logo is an SVG icon rendered inline (no external image request).
- Logo + wordmark form a single clickable unit (`<Link to="/">`).
- Clicking navigates to `/` (existing behavior of the wordmark link).
- The logo does NOT independently link anywhere — it is part of the same anchor as the wordmark.

### 3.2 Logo Design

Proxmon monitors Proxmox guests, so the icon should suggest a server/monitor in the project's accent color palette. A simple server-rack or terminal-screen SVG at 20x20px fits within the 48px navbar without crowding.

Recommended: a monochrome SVG using `currentColor` so it inherits text color from the parent link state.

```
Default:  text-white    -> logo + wordmark in white
Hover:    text-blue-400 -> logo + wordmark shift to blue-400 together
```

Since the logo and wordmark share a single `<Link>`, a single `hover:text-blue-400` class on the link covers both.

### 3.3 Navbar Wireframe

```
Desktop (>=640px):
+------------------------------------------------------------------+
| [logo] proxmon                                     [gear] Settings|
+------------------------------------------------------------------+
  ^      ^                                                ^
  20px   text-lg / font-bold / tracking-tight            text-sm / gap-1.5

Mobile (<640px) — identical layout, "Settings" label hidden, icon remains:
+-------------------------------+
| [logo] proxmon          [gear]|
+-------------------------------+
```

- Logo size: `20x20px` (`w-5 h-5`).
- Gap between logo and wordmark: `8px` (`gap-2`).
- The existing navbar height of `h-12` (48px) is preserved.
- "Settings" text label: hidden below `sm` (`hidden sm:inline`), gear icon always visible.

### 3.4 Accessibility

- The `<Link>` wrapping logo + wordmark must have `aria-label="proxmon — go to dashboard"` so screen readers announce both purpose and destination.
- The SVG must have `aria-hidden="true"` and `focusable="false"` because the parent link carries the label.

### 3.5 Component Sketch

```tsx
// App.tsx — navbar brand area (both configured and unconfigured states)
<Link
  to="/"
  className="flex items-center gap-2 text-white hover:text-blue-400 transition-colors"
  aria-label="proxmon — go to dashboard"
>
  <ProxmonIcon className="w-5 h-5" aria-hidden="true" focusable="false" />
  <span className="text-lg font-bold tracking-tight">proxmon</span>
</Link>
```

`ProxmonIcon` is a new `src/components/icons/ProxmonIcon.tsx` that exports a single SVG component.

---

## 4. Change 2 — Clickable Guest App Name

### 4.1 Data Model Dependency

The backend must supply a `web_url` field on the guest summary and guest detail types. This field is the auto-detected web address (e.g., `http://192.168.1.50:8989` for Sonarr). The frontend renders the link when `web_url` is present; falls back gracefully when absent.

```ts
// Assumed addition to GuestSummary and GuestDetail types
web_url: string | null;
```

If `web_url` is not yet available from the backend, this feature is gated behind its presence (no link rendered).

### 4.2 Dashboard Table — App Column (GuestRow)

**Current behavior**: `app_name` is plain text or `—`.
**New behavior**: if `web_url` is present, wrap `app_name` in an `<a>` that opens the URL in a new tab.

**Visual states:**

| State | Appearance |
|---|---|
| URL present (default) | `text-blue-400 underline` decoration on hover only (`hover:underline`), `cursor-pointer` |
| URL present (hover) | `text-blue-300`, underline visible |
| URL present (focus-visible) | `outline-2 outline-blue-500 outline-offset-2 rounded` |
| URL absent, app detected | Plain `text-gray-300`, no link affordance |
| No app detected | `—` (em dash), `text-gray-500` |

Do NOT underline by default — underline only on hover. This keeps the table scannable and avoids visual noise across rows.

**Stop-propagation requirement**: the row `<tr>` has an `onClick` that navigates to `/guest/:id`. The app name `<a>` must call `e.stopPropagation()` so clicking the link does not simultaneously navigate to the detail page.

**Touch target**: the `<a>` must be at least `44x44px` effective touch area. Achieve this with `py-2` (existing row padding contributes) and `px-1` on the link itself, plus a negative margin to avoid shifting layout: `inline-flex items-center py-2 -my-2 px-1 -mx-1`.

### 4.3 Dashboard Table — App Column Wireframe

```
App column cell — URL present:
+--------------------+
|  [Sonarr >]        |   <- blue-400, arrow icon (w-3 h-3) inline
+--------------------+

App column cell — no URL, app detected:
+--------------------+
|  Plex              |   <- gray-300, plain text
+--------------------+

App column cell — no app:
+--------------------+
|  —                 |   <- gray-500 em dash
+--------------------+
```

The `>` arrow is a small inline SVG (`ExternalLinkIcon`, `w-3 h-3`, `ml-1`, `aria-hidden`). It signals "opens externally" without a full external-link icon that would be too large for a table cell.

### 4.4 GuestDetail Page — App Detection Panel

**Current behavior**: `app_name` is plain text inside the App Detection panel.
**New behavior**: if `web_url` is present, render a styled link below the app name row (not inline in the label/value pair, to preserve scannability).

```
App Detection panel — URL present:
+------------------------------------------+
| APP DETECTION                            |
| App:              Sonarr                 |
| Detection method: api                    |
| Plugin:           sonarr                 |
|                                          |
| [Open Sonarr ->]                         |   <- button-style link
+------------------------------------------+

App Detection panel — no URL:
+------------------------------------------+
| APP DETECTION                            |
| App:              Plex                   |
| Detection method: api                    |
| Plugin:           plex                   |
|                                          |
| No web address detected.                 |   <- muted helper text
+------------------------------------------+

App Detection panel — no app detected:
+------------------------------------------+
| APP DETECTION                            |
| No app detected for this guest. ...      |   <- existing copy, unchanged
+------------------------------------------+
```

**"Open [App Name]" link styles:**

```
Default:  inline-flex items-center gap-1.5 px-3 py-1.5 text-sm rounded
          border border-blue-500/50 text-blue-400 hover:bg-blue-500/10
          hover:border-blue-400 transition-colors
Focus:    outline-2 outline-blue-500 outline-offset-2
```

This is a bordered ghost button, consistent with the existing "Go to Settings" and "Back to Dashboard" link styles already in the codebase.

### 4.5 Tooltip / Title Attribute

Both the `<a>` in GuestRow and the "Open [App]" button in GuestDetail must carry `title={web_url}` so the full URL is revealed on hover without cluttering the UI. This aids trust (user can verify the URL before clicking) and is especially useful for IPs.

### 4.6 Accessibility

| Requirement | Implementation |
|---|---|
| Link purpose is clear in isolation | `aria-label="Open Sonarr at http://192.168.1.50:8989 (opens in new tab)"` |
| External target announced | `target="_blank" rel="noopener noreferrer"` — screen readers announce "link, opens in new tab" |
| No link for missing URL | Render `<span>` not `<a>`, never a disabled `<a>` |
| Keyboard | `<a>` is natively focusable; stop-propagation on Enter not needed (anchor default behavior) |

---

## 5. Change 3 — Responsive Design

### 5.1 Responsive Principles

- Mobile-first: base styles target 320–639px. Larger breakpoints add complexity progressively.
- Touch targets: minimum `44x44px` for all interactive elements on touch screens.
- No horizontal scroll on any page at 320px viewport width.
- Typography does not scale below `text-xs` (11px). Minimum readable body size is `text-sm` (14px).

### 5.2 Navbar (all pages)

| Breakpoint | Behavior |
|---|---|
| < 640px | "Settings" text hidden, gear icon only. Logo + wordmark left-aligned. |
| >= 640px | "Settings" text visible. Current layout unchanged. |

The navbar height remains `h-12` at all breakpoints. No hamburger menu — the app has two nav items maximum, so collapsing to an icon is sufficient.

### 5.3 Dashboard — Table to Card Layout

**Problem**: the 8-column table (`Guest Name`, `Type`, `App`, `Installed`, `Latest`, `Status`, `Last Checked`, `Actions`) is unreadable below ~900px.

**Solution**: switch to a card list below `md` (768px).

#### Desktop Table (>= 768px) — unchanged

```
+----------+---------+---------+-----------+---------+--------+----------+--------+
| Guest    | Type    | App     | Installed | Latest  | Status | Checked  | Action |
+----------+---------+---------+-----------+---------+--------+----------+--------+
| pve-001  | LXC     | Sonarr >| 4.0.1     | 4.0.2   | OUTD.  | 2h ago   | View   |
| pve-002  | VM      | Plex    | 1.32.0    | 1.32.0  | OK     | 5m ago   | View   |
+----------+---------+---------+-----------+---------+--------+----------+--------+
```

#### Mobile Card (< 768px)

Each guest becomes a vertical card. The card itself is tappable (navigates to detail). The app name link within the card taps to open the web URL.

```
+------------------------------------------+
| pve-001                      [OUTDATED]  |
| LXC  •  Sonarr [>]                       |
| 4.0.1 -> 4.0.2               2h ago      |
+------------------------------------------+
| pve-002                      [UP TO DATE]|
| VM  •  Plex                              |
| 1.32.0                       5m ago      |
+------------------------------------------+
```

Card anatomy:
- **Row 1**: guest name (`text-sm font-medium text-gray-200`) + status badge (right-aligned).
- **Row 2**: type badge + app name (plain or link, `text-sm text-gray-300`).
- **Row 3**: version string + last-checked time (right-aligned, `text-xs text-gray-500`).
- Padding: `px-4 py-3`.
- Border: `border border-gray-800 rounded`, `mb-2`.
- Hover/focus: `bg-gray-800/50`, matching existing row hover.
- Full card `tabIndex={0}` + keyboard Enter = navigate, same as table row.

#### Version string formatting on mobile

`{installed_version}` if up-to-date, or `{installed_version} -> {latest_version}` if outdated. Uses monospace `font-mono text-xs`. Truncate at 20 chars with `truncate` if version strings are long.

#### Filter bar on mobile

```
Mobile (<640px):
+------------------------------------------+
| [Search input — full width             ] |
| [Status v]  [Type v]       3 / 12 guests |
+------------------------------------------+

Desktop (>=640px):
+------------------------------------------+
| [Search...]  [Status v]  [Type v]  3/12  |
+------------------------------------------+
```

Search input is `w-full` on mobile, wraps below `sm` via `flex-wrap`. Status and type dropdowns are `flex-1` on mobile so they share the row equally.

### 5.4 GuestDetail — Responsive Layout

The GuestDetail page uses vertical stacked panels (`space-y-4`), which is already mobile-friendly. Changes needed:

**Breadcrumb**: truncate guest name with `truncate max-w-[160px] sm:max-w-none` on mobile.

**Title + status row**: current `flex items-center justify-between` works at all widths — no change needed if guest names are short. Add `min-w-0` and `truncate` to the `<h1>` wrapper to prevent overflow on very long names.

**Metadata row** (Type badge, ID, Running/Stopped, Tags): currently `flex items-center gap-3`. On mobile this can overflow. Change to `flex flex-wrap gap-2` — items wrap naturally.

**Version Status panel**: the version numbers use `text-lg font-mono`. On mobile, `text-base font-mono` is sufficient (saves horizontal space). Use `sm:text-lg`.

**Version History table**: already has `overflow-x-auto`. No structural change needed. Column widths are narrow enough that the table is readable at ~400px.

**Raw Detection Output**: `max-h-[300px]` is preserved. On mobile, `max-h-[200px]` reduces vertical scroll depth: `max-h-[200px] sm:max-h-[300px]`.

### 5.5 Settings — Responsive Layout

The Settings page is a single-column form, already vertically stacked. It is inherently mobile-friendly. Targeted fixes:

**Sticky save bar**: currently `fixed bottom-0 left-0 right-0`. On mobile, the "Save Changes" button should be `w-full` instead of right-aligned, so the tap target spans the full bar width.

```
Mobile (<640px) sticky bar:
+------------------------------------------+
| [      Save Changes (full width)       ] |
+------------------------------------------+

Desktop (>=640px) sticky bar:
+------------------------------------------+
|                         [Save Changes]   |
+------------------------------------------+
```

**App Configuration section** (AppConfigSection): if it uses a multi-column grid, ensure it is `grid-cols-1 sm:grid-cols-2`. API key and port fields must be `w-full` at all breakpoints.

**Radio button auth method**: the `flex gap-4` layout of Key / Password radio buttons is fine at all widths — two short labels.

**Plugin list**: the `flex items-center justify-between` rows for each plugin are fine at all widths.

### 5.6 Setup Wizard — Responsive Layout

The SetupWizard is not part of the files provided, but the outer shell is in `App.tsx`. The wrapper `<div className="min-h-screen bg-background text-gray-100">` with the same navbar applies. Requirements for the wizard steps:

- Wizard container: `max-w-lg mx-auto px-4 py-8` on all breakpoints (already a narrow form, does not need to widen).
- Step indicator (if present): horizontal steps should not overflow; hide step labels below `sm`, show only numbers/dots.
- Form fields within wizard steps: `w-full` inputs, same as Settings.
- Navigation buttons ("Back", "Next"): `flex gap-3` on desktop, `flex-col-reverse gap-2 w-full` on mobile so "Next" is on top (primary action closest to thumb).

```
Wizard nav buttons — mobile:
+------------------------------------------+
| [          Continue (full width)       ] |
| [             Back (full width)        ] |
+------------------------------------------+

Wizard nav buttons — desktop (>=640px):
+------------------------------------------+
|                         [Back] [Continue]|
+------------------------------------------+
```

---

## 6. States Reference

### 6.1 App Name Link States (Dashboard Table)

| State | Visual | Notes |
|---|---|---|
| `web_url` present, default | `text-blue-400`, no underline, external link icon (`w-3 h-3`) | Discoverable on hover |
| `web_url` present, hover | `text-blue-300`, underline appears | Underline as hover confirmation |
| `web_url` present, focus-visible | `outline-2 outline-blue-500 rounded outline-offset-2` | Keyboard users |
| `web_url` present, active (click) | `text-blue-200` (brief) | Browser default on `<a>` |
| `web_url` null, app detected | `text-gray-300`, `<span>` (not `<a>`) | No link affordance |
| No app (`app_name` null) | `text-gray-500`, `—` | Em dash, not a link |

### 6.2 "Open App" Button States (GuestDetail)

| State | Visual |
|---|---|
| `web_url` present, default | Ghost button: `border border-blue-500/50 text-blue-400` |
| Hover | `bg-blue-500/10 border-blue-400` |
| Focus-visible | `outline-2 outline-blue-500 outline-offset-2` |
| `web_url` null, app detected | Muted helper: `text-sm text-gray-500` — "No web address detected." |
| No app detected | Existing "No app detected" copy — no web address UI shown |

### 6.3 Loading State (web URL)

The `web_url` is part of the guest data payload. There is no separate loading state for it. If the guest is loading, the existing `<LoadingSpinner>` covers the entire panel. No skeleton needed for the URL specifically.

### 6.4 Error State (web URL unreachable)

proxmon does not verify reachability of `web_url` on the frontend. The link opens in a new tab regardless. If the target is unreachable, the browser's native error page handles it. Do not add a reachability check — it would require CORS-friendly probing and adds complexity with no meaningful UX gain in a homelab context.

---

## 7. Touch Target Sizes

All interactive elements must meet a minimum effective touch target of `44x44px` (Apple HIG / WCAG 2.5.5 AAA guideline).

| Element | Current padding | Mobile fix |
|---|---|---|
| Navbar logo+wordmark link | `h-12` (48px height) | Width auto — sufficient |
| Navbar Settings icon | `h-12` height, icon only | Wrap in `p-2` to ensure 44px wide |
| Guest row (card on mobile) | `py-3 px-4` | Card full-width tap — sufficient |
| App name link in table | `py-2` row padding | Add `-my-2 py-2 inline-flex` on `<a>` |
| App name link in card | `py-3` card padding | Sufficient via row height |
| "Open App" ghost button | `py-1.5 px-3` = ~30px height | Change to `py-2.5 px-4` on mobile: `sm:py-1.5 sm:px-3` |
| Refresh button (Dashboard) | `py-1.5` = ~30px | Add `sm:py-1.5 py-2.5` on mobile |
| Save Changes button | `py-2` | Full-width on mobile — sufficient |
| View button in table | `text-xs`, small | Hidden on mobile (replaced by card tap) |

---

## 8. Typography Scale Across Breakpoints

The app uses a monospace font stack throughout. Established sizes:

| Usage | Mobile | Desktop |
|---|---|---|
| Page heading (`h1`) | `text-xl` (20px) | `text-xl` (20px) — unchanged |
| Section heading (`h2`) | `text-xs uppercase` | `text-xs uppercase` — unchanged |
| Body / table cells | `text-sm` (14px) | `text-sm` (14px) — unchanged |
| Muted / metadata | `text-xs` (12px) | `text-xs` (12px) — unchanged |
| Version numbers | `text-base font-mono` | `text-lg font-mono` (`sm:text-lg`) |
| Navbar wordmark | `text-lg font-bold` | `text-lg font-bold` — unchanged |
| Badge / pill labels | `text-[11px]` | `text-[11px]` — unchanged |

No font sizes shrink below 12px. No font sizes increase above `text-xl` for headings (information-dense design principle from existing spec).

---

## 9. Keyboard Navigation Flow

### Navbar
1. Tab -> Logo+wordmark link (focus: outline on the `<Link>`)
2. Tab -> Settings link / icon

### Dashboard (card view, mobile)
1. Tab -> Refresh button
2. Tab -> Search input
3. Tab -> Status filter
4. Tab -> Type filter
5. Tab -> Guest card 1 (Enter = navigate to detail)
6. (If app name link present) Tab -> App name link within card (Enter = open in new tab)
7. Tab -> Guest card 2 ...

Note: The app name link inside a card must be a natural tab stop between cards. The card itself is `tabIndex={0}`; the app name link is `tabIndex={0}` (default for `<a>`). The tab order (card -> link -> next card) is correct with DOM order.

### Dashboard (table view, desktop)
Row-level navigation: Tab moves through rows (existing `tabIndex={0}` on `<tr>`). Within a row, Tab enters the cell-level links: app name link (if present), then View button. Arrow keys do not navigate rows — this is not a grid widget.

### GuestDetail
Standard tab flow through breadcrumb link, "Open App" button (if present), "View release notes" link (if present), raw output toggle, "Back to Dashboard" link.

### Settings
Standard tab flow through all form inputs. The sticky save bar button is last in tab order (bottom of page, fixed positioning does not affect DOM order — confirm with implementation).

---

## 10. Files Affected

| File | Change |
|---|---|
| `src/App.tsx` | Add logo to both navbar instances (unconfigured + configured). Add `hidden sm:inline` to Settings label text. |
| `src/components/icons/ProxmonIcon.tsx` | New file. SVG icon component. |
| `src/components/GuestRow.tsx` | App name cell: conditional `<a>` with stop-propagation. Add `web_url` from props. Mobile card layout (new conditional render or new `GuestCard` component). |
| `src/components/Dashboard.tsx` | Switch between table and card list below `md`. Pass `web_url` to GuestRow/GuestCard. |
| `src/components/GuestDetail.tsx` | Add "Open App" ghost button or "No web address detected" helper in App Detection panel. Version number responsive size. Metadata row `flex-wrap`. |
| `src/components/Settings.tsx` | Save bar button `w-full sm:w-auto`. |
| `src/types.ts` | Add `web_url: string \| null` to `GuestSummary` and `GuestDetail`. |

---

## 11. Acceptance Criteria

### Logo
- [ ] SVG logo renders inline to the left of "proxmon" in the navbar on all pages and both app states (configured, unconfigured/wizard).
- [ ] Logo and wordmark share a single focusable link element.
- [ ] Clicking logo or wordmark navigates to `/`.
- [ ] Hover changes both logo and wordmark color to `blue-400` simultaneously.
- [ ] `aria-label` on the link reads "proxmon — go to dashboard".
- [ ] SVG has `aria-hidden="true"`.

### Clickable App Name
- [ ] When `web_url` is present, `app_name` in the Dashboard table renders as `<a target="_blank" rel="noopener noreferrer">`.
- [ ] Clicking the app name link does NOT navigate to the guest detail page (stop-propagation).
- [ ] When `web_url` is null and `app_name` is present, `app_name` renders as plain text (no link affordance).
- [ ] When `app_name` is null, `—` (em dash) renders as plain text.
- [ ] GuestDetail App Detection panel shows "Open [App Name]" ghost button when `web_url` is present.
- [ ] GuestDetail shows "No web address detected." helper text when `app_name` is set but `web_url` is null.
- [ ] All link `aria-label` values include the full URL and "(opens in new tab)".
- [ ] `title` attribute on link shows the full `web_url`.
- [ ] Effective touch target on the app name link is >= 44px in height.

### Responsive Design
- [ ] At 320px viewport, no horizontal scrollbar on Dashboard, GuestDetail, Settings, or Setup pages.
- [ ] Below 768px, Dashboard renders card list instead of table.
- [ ] At 768px and above, Dashboard renders the standard table.
- [ ] "Settings" text label in navbar is hidden below 640px; gear icon remains visible.
- [ ] Sticky save bar button is full-width below 640px on Settings page.
- [ ] Wizard navigation buttons stack vertically (primary on top) below 640px.
- [ ] All interactive elements meet 44x44px minimum touch target on mobile.
- [ ] Version numbers in GuestDetail use `text-base` on mobile, `text-lg` on sm+.
- [ ] GuestDetail metadata row wraps correctly without overflow at 320px.
