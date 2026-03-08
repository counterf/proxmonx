# UX Spec: Per-App API Key and Port Override

**Version**: 1.0
**Date**: 2026-03-08
**Feature**: Per-App Configuration — port and API key overrides for supported app detectors
**Screen**: Settings (`/settings`) — new "App Configuration" section

---

## 1. Overview

Add a collapsible "App Configuration" section to the existing Settings page. It presents all 13 supported app detectors in a compact table, letting users override the default HTTP port and set an API key for apps that require one for version detection.

All fields are optional. An empty port field means "use the default." An empty API key field means "no authentication." This is a best-effort configuration; misconfigured values degrade detection gracefully (detector falls back to unauthenticated or skips the version check).

---

## 2. App Roster

| App | Default Port | API Key Supported |
|---|---|---|
| Sonarr | 8989 | Yes |
| Radarr | 7878 | Yes |
| Prowlarr | 9696 | Yes |
| Bazarr | 6767 | Yes |
| Overseerr | 5055 | Yes |
| SABnzbd | 8085 | No |
| qBittorrent | 8080 | No |
| Gitea | 3000 | No |
| ntfy | 80 | No |
| Plex | 32400 | No |
| Immich | 2283 | No |
| Traefik | 8080 | No |
| Caddy | 2019 | No |

---

## 3. Component Layout

### 3.1 Section Placement

The "App Configuration" section is inserted in Settings between the "GitHub Token" section and the "Plugins (Detectors)" section. It follows the same card pattern as all other settings sections: `p-4 rounded bg-surface border border-gray-800`.

### 3.2 Section Header (Collapsible Toggle)

The section header doubles as the collapse/expand trigger. It matches the existing `<h2>` style but adds a chevron icon on the right edge.

```
+----------------------------------------------------------+
| APP CONFIGURATION                              [chevron] |
| Per-app port and API key overrides (optional)            |
+----------------------------------------------------------+
```

- `<h2>` text: `"APP CONFIGURATION"` — `text-xs font-medium text-gray-500 uppercase tracking-wider`
- Subtitle: `"Per-app port and API key overrides (optional)"` — `text-xs text-gray-600 mt-0.5`
- Chevron: rotates 180deg when expanded; `transition-transform duration-150`
- The entire header row is a `<button type="button">` wrapping both `<h2>` and chevron
- Default state: **collapsed**

**ARIA on the toggle button:**
```
role="button"
aria-expanded="false | true"
aria-controls="app-config-panel"
```

### 3.3 Collapsed State

Only the header row is visible. The table is hidden via `display: none` (not `visibility: hidden`) so it is excluded from tab order and screen reader traversal.

```
+----------------------------------------------------------+
| APP CONFIGURATION                              [v]       |
| Per-app port and API key overrides (optional)            |
+----------------------------------------------------------+
```

### 3.4 Expanded State — Table Layout

When expanded, the section reveals a table with one row per app. The table uses a fixed column layout for alignment across rows.

```
+----------------------------------------------------------+
| APP CONFIGURATION                              [^]       |
| Per-app port and API key overrides (optional)            |
+----------------------------------------------------------+
| App           | Port override  | API Key                 |
|---------------|----------------|-------------------------|
| Sonarr        | [____8989____] | [password_field    [o]] |
| Radarr        | [____7878____] | [password_field    [o]] |
| Prowlarr      | [____9696____] | [password_field    [o]] |
| Bazarr        | [____6767____] | [password_field    [o]] |
| Overseerr     | [____5055____] | [password_field    [o]] |
| SABnzbd       | [____8085____] |   —                     |
| qBittorrent   | [____8080____] |   —                     |
| Gitea         | [____3000____] |   —                     |
| ntfy          | [______80____] |   —                     |
| Plex          | [___32400____] |   —                     |
| Immich        | [____2283____] |   —                     |
| Traefik       | [____8080____] |   —                     |
| Caddy         | [____2019____] |   —                     |
+----------------------------------------------------------+
```

#### Column widths (desktop, percentage of section width)

| Column | Width | Notes |
|---|---|---|
| App name | 25% | `text-sm text-gray-300`, not truncated (all names are short) |
| Port override | 30% | Number input, see §3.5 |
| API Key | 45% | Password input for apps that support it; em-dash (`—`) in `text-gray-600` for apps that do not |

#### Table ARIA

```html
<table aria-label="Per-app configuration overrides">
  <thead>
    <tr>
      <th scope="col">App</th>
      <th scope="col">Port override</th>
      <th scope="col">API Key</th>
    </tr>
  </thead>
  <tbody> ... </tbody>
</table>
```

- `<thead>` row: `text-xs text-gray-500 uppercase`, `border-b border-gray-800`
- Row height: `py-2` — compact, consistent with the Plugins section row style
- Row separator: `border-b border-gray-800/50` on each `<tr>` except the last
- No zebra striping (maintains visual quiet)

### 3.5 Port Override Input

- Type: `<input type="number">`
- Width: full width of the column
- Placeholder: the default port as a number (e.g., `8989`)
- Min: `1`, Max: `65535`
- Font: `font-mono text-sm`
- Background/border: identical to other Settings inputs — `bg-surface border border-gray-800`
- Focus ring: `focus:ring-1 focus:ring-blue-500`
- When the field has a value different from the default, the value is rendered in `text-white`; when empty (using default), the placeholder text is shown in `text-gray-600`

**Input ID pattern**: `app-port-{app-name}` (e.g., `app-port-sonarr`)

**ARIA**: `aria-label="Port override for Sonarr"` — set on the `<input>` directly (the `<th>` column header alone is insufficient because the input's row context may not be communicated by all screen readers)

### 3.6 API Key Input

Reuses the existing `PasswordField` component with the following adjustments for the table layout:

- `label` prop is omitted (label is provided by the column header `<th>` and the input's own `aria-label`)
- `placeholder`: `"API key (optional)"`
- Show/hide toggle button: preserved — same eye icon from `PasswordField`, `aria-label="Show API key for {AppName}"` / `"Hide API key for {AppName}"`
- Width: full width of its column cell
- Input ID pattern: `app-apikey-{app-name}` (e.g., `app-apikey-sonarr`)

For apps without API key support, the cell renders a centered `—` (`text-gray-600 text-sm`). No input element is rendered; there is nothing to focus in that cell.

---

## 4. States

### 4.1 Default / Empty (no overrides configured)

- Section is collapsed
- All port inputs show their default port as `placeholder` (not as a value — the field is empty, meaning "use default")
- All API key inputs are empty
- No "dirty" indicator in the breadcrumb area
- Save button in the sticky footer is disabled (no changes)

### 4.2 Partially Filled (user is editing)

- The "Unsaved changes" amber indicator in the breadcrumb row appears as soon as any app config field is changed (same mechanism as the rest of the Settings form — `isDirty` flag)
- The sticky "Save Changes" button becomes enabled
- Each modified port field shows `text-white`; unmodified fields show placeholder

### 4.3 Filled / Saved

- Port inputs that have saved overrides display the saved value as the `value` attribute (not placeholder), styled `text-white font-mono`
- API key inputs that have saved keys display `"***"` (masked, same masking pattern as `proxmox_token_secret` in the existing form). Actual key is not sent to the frontend after initial save
- The section can be collapsed after save; values persist across collapse/expand cycles within the same session

### 4.4 Saving (in-progress)

- The sticky "Save Changes" button shows a spinner and "Saving..." label — identical to the existing save behavior
- All inputs in the App Configuration table are `disabled` while saving, preventing mid-save edits
- Table visual: `opacity-50` on the table body during saving

### 4.5 Save Error

- The existing `ErrorBanner` at the top of the Settings page displays the error message
- The App Configuration section remains expanded
- All inputs return to enabled state
- "Unsaved changes" indicator remains visible
- If the error is field-specific (e.g., invalid port value that passes frontend validation but fails backend), an inline `text-xs text-red-400` error message appears below the relevant input (same `role="alert"` pattern as `FormField`)

### 4.6 Validation Error (frontend)

Port field validation fires on blur (not on every keystroke):
- Value `< 1` or `> 65535`: inline error `"Port must be between 1 and 65535"`
- Non-integer (e.g., `80.5`): inline error `"Port must be a whole number"`
- Error styled `text-xs text-red-400 mt-0.5`, displayed below the input
- Input border changes to `border-red-500`
- Save button remains disabled while any field has a validation error

API key fields: no frontend validation (any string is accepted; empty means "no key").

---

## 5. Interaction Design

### 5.1 Expand / Collapse

- Click or `Enter`/`Space` on the header button toggles the panel
- Smooth height transition: `overflow-hidden` with `max-height` CSS transition (`max-h-0` to `max-h-[800px]`, `transition-all duration-200 ease-in-out`) avoids a JavaScript-measured height
- Chevron rotates 180deg using `transition-transform duration-150`
- When expanding: panel content becomes visible and focusable immediately (no delay before Tab can reach the first input)

### 5.2 Editing a Port

1. User clicks into a port input (or Tabs to it)
2. If the field was previously empty (using default), the placeholder disappears and the cursor is positioned
3. User types a new port number
4. On blur: validation runs; error shown inline if invalid
5. `isDirty` becomes `true`; "Unsaved changes" and enabled Save appear
6. User saves via the sticky footer button

### 5.3 Editing an API Key

1. User clicks into the API key input (or Tabs to it)
2. Input is a password field; characters are masked by default
3. User may click the eye icon to toggle visibility
4. Existing saved key is shown as `"***"` — typing any character clears the mask and enters a new key (same behavior as `proxmox_token_secret`)
5. Leaving the field as `"***"` without editing means "keep current key" (same flag pattern as `tokenSecretChanged.current`)
6. Clearing to empty string means "remove the key"

### 5.4 Resetting to Default

There is no explicit "Reset to default" button per row in the MVP. To restore a default port, the user clears the port field (empty = use default). To remove an API key, the user clears the API key field.

### 5.5 Save Flow (end-to-end)

```
User edits any app config field
  -> isDirty = true
  -> "Unsaved changes" indicator appears
  -> "Save Changes" button enables

User clicks "Save Changes"
  -> Frontend validation runs on all port fields
  -> Any error? Abort save, show inline errors
  -> No errors? POST /api/settings with app_configs payload
  -> Button shows spinner + "Saving..."
  -> Table inputs disabled (opacity-50)
  -> Success?
       YES -> savedForm = form, isDirty = false
              "Unsaved changes" disappears
              SuccessToast: "Settings saved. Discovery restarting..."
              Inputs re-enable
       NO  -> ErrorBanner: "Save failed: <reason>"
              Inputs re-enable
              isDirty remains true
```

---

## 6. Data Model

The `app_configs` field is added to the existing `FullSettings` / `SettingsSaveRequest` types.

```ts
interface AppConfig {
  port?: number;      // undefined = use detector default
  api_key?: string;   // undefined or "" = no authentication
}

// Added to FullSettings and SettingsSaveRequest:
app_configs: Record<string, AppConfig>;
// key is the detector name in lowercase, e.g. "sonarr", "radarr"
```

When loading settings, the backend returns masked API keys (`"***"`) for any app that has a saved key. The frontend tracks per-app key change state with a `changedApiKeys: Set<string>` ref (analogous to `tokenSecretChanged`). A key is sent in the save payload only if it was changed; otherwise the field is omitted, and the backend retains the current value.

The payload shape for save:

```ts
// Only changed or newly set keys are included.
// An explicit empty string ("") means "clear this key".
app_configs: {
  sonarr: { port: 8990, api_key: "abc123" },
  radarr: { port: 7878 },   // port only, key unchanged
  prowlarr: { api_key: "" } // clear the key, port unchanged
}
```

---

## 7. Mobile Considerations

The table layout degrades on narrow screens (< 640px):

- Switch from a 3-column table to a stacked card per app
- Each app gets its own mini-card with the app name as a label row, port input below, and (if applicable) API key input below that
- Card: `bg-gray-800/40 rounded p-3 mb-2`
- The collapse/expand behavior is preserved; default remains collapsed

Desktop breakpoint (`sm:` and above): table layout as described in §3.4.

```
Mobile card layout (< 640px):

+------------------------------------------+
| Sonarr                                   |
| Port   [__________]                      |
| API Key [password_____________] [o]      |
+------------------------------------------+
| Radarr                                   |
| Port   [__________]                      |
| API Key [password_____________] [o]      |
+------------------------------------------+
| SABnzbd                                  |
| Port   [__________]                      |
+------------------------------------------+
```

---

## 8. Accessibility

### 8.1 Keyboard Navigation

| Interaction | Key |
|---|---|
| Expand / collapse section | `Enter` or `Space` on section header button |
| Move through port and API key inputs | `Tab` / `Shift+Tab` |
| Increment / decrement port value | `Up` / `Down` arrow keys (native `<input type="number">` behavior) |
| Toggle API key visibility | `Enter` or `Space` on the eye icon button |
| Tab order within a row | App name (non-focusable) -> Port input -> API key input (if present) -> show/hide button (if present) -> next row |

### 8.2 ARIA Requirements

| Element | ARIA |
|---|---|
| Section toggle button | `aria-expanded="false\|true"`, `aria-controls="app-config-panel"` |
| Panel container | `id="app-config-panel"` |
| Table | `aria-label="Per-app configuration overrides"` |
| Column headers | `<th scope="col">` |
| Port input | `aria-label="Port override for {AppName}"`, `aria-describedby="{id}-error"` when error present |
| API key input | `aria-label="API key for {AppName}"`, `aria-describedby="{id}-error"` when error present |
| Show/hide toggle | `aria-label="Show API key for {AppName}"` / `"Hide API key for {AppName}"` |
| Inline error messages | `role="alert"` (consistent with `FormField` component) |
| Disabled table during save | `aria-busy="true"` on the `<tbody>`, individual inputs have `disabled` and `aria-disabled="true"` |
| "No API key" cell | `aria-label="No API key for {AppName}"` on a `<td>` with `role="cell"` — do not leave a screen reader with an empty cell |

### 8.3 Color Contrast

All text must meet WCAG AA (4.5:1 normal text, 3:1 large/bold text):
- `text-gray-300` on `bg-surface` (app names): verify with tooling
- `text-gray-600` for em-dash and placeholder text: intentionally low contrast as non-critical decorative text; the `aria-label` conveys the semantics
- `text-red-400` on `bg-surface` for error messages: verify with tooling
- Input `text-white` on `bg-surface`: passes at all reasonable background values

### 8.4 Focus Management

- On expand: focus does not move automatically (the user triggered expand deliberately; they Tab forward to enter the table)
- On collapse: focus moves to the section toggle button if focus was inside the panel at the time of collapse (prevents focus loss)
- On save error: focus moves to the `ErrorBanner` dismiss button (`role="alert"` handles screen reader announcement; focus management handles sighted keyboard users)

---

## 9. User Stories and Acceptance Criteria

### US-06: Configure a per-app port override

**As a** homelab user who runs Sonarr on a non-default port,
**I want to** set a custom port for Sonarr in Settings,
**So that** proxmon connects to the right endpoint during version checks.

**Acceptance criteria:**
- [ ] App Configuration section is visible in Settings between the GitHub Token and Plugins sections
- [ ] Section is collapsed by default; expand/collapse works with mouse and keyboard
- [ ] All 13 supported apps are listed with their default port as input placeholder
- [ ] Entering a port number marks the form as dirty and enables Save
- [ ] Saving persists the override; port input shows the saved value (not the placeholder) after reload
- [ ] Clearing the port field back to empty reverts to the detector default on next save
- [ ] Port values outside 1–65535 show an inline validation error and block save

### US-07: Set an API key for an app

**As a** homelab user with a Sonarr installation requiring an API key for version checks,
**I want to** store my Sonarr API key in proxmon Settings,
**So that** version detection can authenticate with Sonarr's API.

**Acceptance criteria:**
- [ ] API key field is visible only for the 5 apps that support it (Sonarr, Radarr, Prowlarr, Bazarr, Overseerr)
- [ ] API key field is a password input (masked by default) with a show/hide toggle
- [ ] After saving, the field displays `"***"` — the raw key is not re-sent to the frontend
- [ ] Editing the field (any keystroke after load) marks the key as changed and includes it in the save payload
- [ ] Leaving the field as `"***"` without editing omits the key from the save payload (backend retains existing value)
- [ ] Clearing the field to empty string and saving removes the stored key

### US-08: Navigate the table accessibly

**As a** keyboard-only user,
**I want to** Tab through the app configuration table and edit fields without a mouse,
**So that** the feature is fully accessible to me.

**Acceptance criteria:**
- [ ] Section expand/collapse is triggered with `Enter` or `Space` on the header button
- [ ] Tab order moves: port input -> (API key input -> show/hide button) for each row, in document order
- [ ] Each input has a descriptive `aria-label` including the app name (e.g., "Port override for Sonarr")
- [ ] Inline error messages use `role="alert"` and are announced by screen readers on appearance
- [ ] Collapsing the panel while a field is focused moves focus to the section header button

---

## 10. Component Reuse Summary

| Component | Usage in this feature |
|---|---|
| `FormField` | Wraps port inputs for label + error message pattern |
| `PasswordField` | Used for API key inputs (label suppressed; `aria-label` on `<input>` provides the accessible name) |
| `ErrorBanner` | Displays save errors at page level (existing behavior, no change) |
| `SuccessToast` | Displays save confirmation (existing behavior, no change) |
| `Toggle` | Not used in this feature (no boolean toggles per app in scope) |

New component required:
- `AppConfigSection` — the collapsible section container with the table, managing expand/collapse state, per-row dirty tracking, and validation. Self-contained; receives `appConfigs: Record<string, AppConfig>` and `onChange: (configs: Record<string, AppConfig>) => void` as props.

---

## 11. Out of Scope

- Enabling or disabling individual app detectors from this UI (handled by the existing Plugins section)
- Per-app base URL override (only port, not scheme or path)
- Testing the connection to an individual app from the Settings UI
- Bulk actions (reset all to defaults)
- Import/export of app configuration
