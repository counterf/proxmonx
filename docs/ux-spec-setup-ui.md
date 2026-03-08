# proxmon — Setup & Configuration UI: UX Specification

**Version**: 1.0
**Date**: 2026-03-08
**Audience**: Frontend/backend engineers, homelab community contributors
**Scope**: First-run setup wizard and editable settings page

---

## 1. Design Tokens (existing, reused)

| Token           | Value       | Usage                              |
|-----------------|-------------|------------------------------------|
| `bg-background` | `#0f1117`   | Page background                    |
| `bg-surface`    | `#1a1d27`   | Cards, panels, inputs              |
| `border-gray-800` | `#1f2937` | Card and input borders             |
| `blue-500`      | `#3b82f6`   | Primary action, focus rings, links |
| `red-400/800/900` | —         | Errors, destructive states         |
| `green-500/900` | —           | Success, connected states          |
| `gray-400/500`  | —           | Secondary labels, placeholders     |
| Font            | `ui-monospace` | Global, all text                |

New tokens introduced by this feature:

| Token           | Value       | Usage                              |
|-----------------|-------------|------------------------------------|
| `amber-400`     | `#fbbf24`   | SSL warning text                   |
| `amber-900/30`  | —           | SSL warning background             |

---

## 2. Screen Inventory

| Screen              | Route        | When shown                                                       |
|---------------------|--------------|------------------------------------------------------------------|
| First-Run Wizard    | `/setup`     | Redirected here from `/` when `GET /api/settings` returns `{ configured: false }` or connection fails at app init |
| Editable Settings   | `/settings`  | Replaces existing read-only Settings component                   |
| Transition Screen   | (inline, no route) | Shown after "Save & Start" while discovery runs           |
| Dashboard           | `/`          | Existing; only reachable after wizard completes                  |

**Route guard**: `App.tsx` fetches `GET /health` on mount. If the response includes `configured: false`, redirect to `/setup` and block all other routes until the wizard completes.

---

## 3. New API Endpoints Required

These endpoints do not currently exist and must be added to the backend before this UI can be implemented.

| Method | Path                     | Purpose                                                            |
|--------|--------------------------|--------------------------------------------------------------------|
| `GET`  | `/api/config/status`     | Returns `{ configured: boolean }`. Safe to call before `.env` is valid. |
| `POST` | `/api/config/test`       | Body: proxmox credentials. Returns `{ ok: boolean, error?: string }`. Does not persist. |
| `POST` | `/api/config/save`       | Body: full settings payload. Writes `.env`, restarts discovery. Returns `{ ok: boolean, error?: string }`. |
| `PUT`  | `/api/settings`          | Body: partial or full settings. Updates `.env` in place. Triggers discovery restart. |

---

## 4. First-Run Wizard

### 4.1 Overview

The wizard is a full-page, centered layout that replaces the dashboard. It has 5 steps with a linear progress indicator. The navbar is present but the Settings link is hidden during the wizard.

The wizard must not allow the user to navigate away to `/` or `/guest/:id` while `configured: false`.

### 4.2 Layout (all steps)

```
+----------------------------------------------------------+
| proxmon                                                  |
+----------------------------------------------------------+
|                                                          |
|           Step N of 5   [=====----]   Step Title         |
|                                                          |
|  +----------------------------------------------------+  |
|  |                                                    |  |
|  |   <step content>                                   |  |
|  |                                                    |  |
|  +----------------------------------------------------+  |
|                                                          |
|           [Back]                         [Next ->]       |
|                                                          |
+----------------------------------------------------------+
```

- Card: `max-w-lg`, centered, `bg-surface`, `border border-gray-800`, `rounded`, `p-6`
- Progress bar: thin `h-1` bar above card, filled portion in `blue-500`
- Step counter: `"Step 2 of 5"` in `text-xs text-gray-500`, step title in `text-sm font-medium text-gray-300`
- Back button: ghost style (`text-gray-400 hover:text-white`), hidden on step 1
- Next button: primary style (`bg-blue-600 hover:bg-blue-500 text-white`), label changes to "Review" on step 4 and disabled rules apply on step 5

### 4.3 Progress Indicator

```
  [1] ---- [2] ---- [3] ---- [4] ---- [5]
   *         o        o        o        o
```

- Dots: 5 circles, `w-2 h-2`, connected by `h-px bg-gray-700` lines
- Completed step: `bg-blue-500`
- Current step: `bg-blue-500 ring-2 ring-blue-500/40`
- Upcoming step: `bg-gray-700`
- Entire indicator row: `aria-label="Setup progress, step N of 5"`, `role="progressbar"`, `aria-valuenow={step}`, `aria-valuemin={1}`, `aria-valuemax={5}`

### 4.4 Step 1: Proxmox Connection

**Fields:**

| Field         | Type             | Label              | Required | Placeholder                         |
|---------------|------------------|--------------------|----------|-------------------------------------|
| Host URL      | `text`           | Proxmox Host       | Yes      | `https://192.168.1.10:8006`         |
| Token ID      | `text`           | API Token ID       | Yes      | `root@pam!mytoken`                  |
| Token Secret  | `password`       | API Token Secret   | Yes      | ——                                  |
| Node Name     | `text`           | Node Name          | Yes      | `pve`                               |

Token Secret has a show/hide toggle (eye icon button, `aria-label="Show token secret"` / `"Hide token secret"`).

**Validation (on blur, required):**
- Host URL: must not be empty; must start with `http://` or `https://`
- Token ID: must not be empty; recommended format hint (not enforced): `user@realm!token-name`
- Token Secret: must not be empty
- Node Name: must not be empty

**"Next" enablement:** all 4 fields pass validation.

### 4.5 Step 2: Discovery

**Fields:**

| Field           | Type     | Label            | Default | Notes                                    |
|-----------------|----------|------------------|---------|------------------------------------------|
| Poll Interval   | `number` | Poll Interval (s)| `300`   | Min: 30, Max: 3600                       |
| Include VMs     | toggle   | Include VMs      | off     | Label: "Discover VMs in addition to LXC" |
| Verify SSL      | toggle   | Verify SSL       | off     | Shows warning when toggled off (see below)|

**SSL warning** (shown when Verify SSL is off, which is the default):

```
  [!] SSL verification is disabled. Proxmox uses self-signed
      certificates by default. Enable only if you have a valid cert.
```

Style: `bg-amber-900/30 border border-amber-800 text-amber-400 text-xs p-2 rounded`, with a small warning icon.

**"Next" enablement:** always enabled (all fields have valid defaults).

### 4.6 Step 3: SSH

**Fields:**

| Field           | Type   | Label              | Default  | Notes                             |
|-----------------|--------|--------------------|----------|-----------------------------------|
| Enable SSH      | toggle | Enable SSH         | on       | Collapsing toggle — hides rest of section when off |
| Username        | `text` | SSH Username       | `root`   | Shown only when SSH enabled       |
| Auth Method     | radio  | Authentication     | Key file | Options: "Key file" / "Password". Shown only when SSH enabled |
| Key Path        | `text` | Private Key Path   | —        | Shown when auth = key file        |
| SSH Password    | `password` | SSH Password   | —        | Shown when auth = password, has show/hide toggle |

When SSH is disabled, the card body collapses to show only the toggle row. Use `aria-expanded` on the toggle.

**"Next" enablement:** always enabled if SSH is off; if SSH is on, Username must not be empty, and either Key Path or Password must not be empty.

### 4.7 Step 4: GitHub Token

**Fields:**

| Field         | Type       | Label          | Required | Notes                    |
|---------------|------------|----------------|----------|--------------------------|
| GitHub Token  | `password` | GitHub Token   | No       | Has show/hide toggle     |

**Explanatory copy** (shown above the field):

```
  A personal access token increases the GitHub API rate limit
  from 60 to 5,000 requests/hour, improving version-check
  accuracy for your guests.

  Leave blank to use the unauthenticated limit.
```

Style: `text-xs text-gray-500`, block above the input.

**"Next" enablement:** always enabled (field is optional).

### 4.8 Step 5: Review & Save

**Layout:**

```
+----------------------------------------------------+
|  Review Your Configuration                         |
|                                                    |
|  Proxmox Connection                                |
|  ├ Host         https://192.168.1.10:8006          |
|  ├ Token ID     root@pam!****                      |
|  ├ Token Secret ●●●●●●●●                           |
|  └ Node         pve                                |
|                                                    |
|  Discovery                                         |
|  ├ Poll every   300 s                              |
|  ├ Include VMs  No                                 |
|  └ Verify SSL   No                                 |
|                                                    |
|  SSH                                               |
|  ├ Enabled      Yes                                |
|  ├ Username     root                               |
|  └ Auth method  Key file (/root/.ssh/id_ed25519)   |
|                                                    |
|  GitHub Token   Not set                            |
|                                                    |
|  [Test Connection]                                 |
|                                                    |
|  [Save & Start]                                    |
+----------------------------------------------------+
```

**Summary display rules:**
- Token secret: always shown as `●●●●●●●●` (no reveal option)
- Token ID: masked using the same `user@realm!****` pattern from `config.py`'s `masked_token_id()`
- SSH password (if set): shown as `●●●●●●●●`
- GitHub token: shown as `"Set"` or `"Not set"` (no reveal)
- Boolean fields: `"Yes"` / `"No"`

**Test Connection button:**

- Style: secondary (`border border-gray-700 text-gray-300 hover:border-blue-500 hover:text-white`)
- While testing: spinner inline left of label, button disabled, label `"Testing..."`
- On success: green inline result below button: `"Connected — Proxmox X.X responding on node pve"`
- On failure: red inline result: `"Connection failed: <Proxmox error message>"` with a `"Try again"` link

**Save & Start button:**

- Style: primary (`bg-blue-600 hover:bg-blue-500 text-white`), full-width
- Disabled state: when connection test has not been run OR last test failed
- Opt-out: small `"Skip test and save anyway"` text link below button; clicking it enables Save & Start
- While saving: spinner inline, label `"Saving..."`, button disabled
- On save failure: `ErrorBanner` appears at top of card with message from backend

---

## 5. Transition Screen (Wizard Complete)

Shown immediately after a successful save, before redirecting to the dashboard.

```
+----------------------------------------------------------+
|                                                          |
|                [spinner]                                 |
|           Discovering your guests...                     |
|                                                          |
|        This may take up to 30 seconds.                   |
|                                                          |
+----------------------------------------------------------+
```

- Full viewport height, centered content
- Spinner: existing `LoadingSpinner` component
- After `GET /health` returns `guest_count > 0` OR after 30s timeout, redirect to `/`
- Polling interval for health check during transition: 2s

---

## 6. Editable Settings Page

### 6.1 Layout

```
+----------------------------------------------------------+
| proxmon                                       [Settings] |
+----------------------------------------------------------+
| [!] Save failed: <error>                              X  |  <- conditional, top of content
|                                                          |
| < Dashboard    Settings          [• Unsaved changes]     |
|                                                          |
| [Proxmox Connection card]                                |
| [Discovery card]                                         |
| [SSH card]                                               |
| [GitHub Token card]                                      |
|                                                          |
|                    [sticky bottom bar: Save Changes]     |
+----------------------------------------------------------+
```

- Page title row: breadcrumb left, unsaved indicator right
- Each section is a `bg-surface border border-gray-800 rounded p-4` card
- No tabs — single scrollable page
- Sticky save bar: `sticky bottom-0 py-3 px-4 bg-background border-t border-gray-800`

### 6.2 Unsaved Changes Indicator

- Shown in the page title row when any field value differs from the loaded state
- Style: `text-xs text-amber-400` with a `•` bullet: `• Unsaved changes`
- Hidden when all fields match the saved values
- On navigation away with unsaved changes: browser `beforeunload` confirmation (native dialog, no custom modal)

### 6.3 Section Cards

#### Proxmox Connection

Same 4 fields as Wizard Step 1. Token Secret field shows `●●●●●●●●` by default with an eye icon to reveal (`aria-label="Reveal token secret"`). When revealed, field type switches to `text`.

"Test Connection" button lives inside this card, below the fields, in the same style as the wizard (secondary button, inline result).

#### Discovery

Same 3 fields as Wizard Step 2 (poll interval number input, Include VMs toggle, Verify SSL toggle + SSL warning).

#### SSH

Same collapsible section as Wizard Step 3.

#### GitHub Token

Password field with show/hide toggle. Same explanatory copy as wizard.

### 6.4 Save Changes Button

- Primary style, lives in the sticky bottom bar
- Disabled when: no unsaved changes OR any required field is invalid
- While saving: spinner inline, label `"Saving..."`, button disabled
- On success: success toast (bottom-right, `bg-green-900 border-green-800 text-green-200`, auto-dismiss after 4s), unsaved indicator clears, discovery restarts
- On failure: `ErrorBanner` at top of page content, above breadcrumb

### 6.5 After Save

- Backend restarts discovery (triggered by `PUT /api/settings`)
- Toast message: `"Settings saved. Discovery restarting..."`
- No page redirect; user stays on Settings

---

## 7. Shared Component Breakdown

### 7.1 `FormField`

Wrapper for a label + input + error message row.

Props:
- `label: string`
- `error?: string` — when set, shows red border on input and red helper text below
- `hint?: string` — optional gray helper text (shown when no error)
- `required?: boolean` — adds `*` to label (visually), `aria-required` on input

Markup structure:
```
<div>
  <label for="..." class="block text-xs text-gray-400 mb-1">
    Label <span aria-hidden="true" class="text-red-400">*</span>
  </label>
  <input aria-required="true" aria-describedby="field-error" ... />
  <p id="field-error" role="alert" class="text-xs text-red-400 mt-1">Error message</p>
</div>
```

### 7.2 `PasswordField`

Extends `FormField` with show/hide toggle.

- Eye icon button: `type="button"` (prevents form submit), positioned absolutely inside input container
- Icon toggles between eye-open / eye-closed SVG
- `aria-label` toggles between `"Show <field name>"` and `"Hide <field name>"`
- Input `type` toggles between `"password"` and `"text"`

### 7.3 `Toggle`

Custom accessible toggle switch replacing a checkbox.

- Renders as `<button role="switch" aria-checked={value}>`
- Visual: pill shape, `w-10 h-5`, thumb slides left/right
- Off: `bg-gray-700`, On: `bg-blue-600`
- Receives visible focus ring on keyboard focus: `focus-visible:ring-2 focus-visible:ring-blue-500`

### 7.4 `ConnectionTestResult`

Inline result shown below "Test Connection" button.

Props: `status: 'idle' | 'loading' | 'success' | 'error'`, `message?: string`

| Status    | Display                                                         |
|-----------|-----------------------------------------------------------------|
| `idle`    | Nothing rendered                                                |
| `loading` | Spinner + `"Testing connection..."`                             |
| `success` | Green check icon + message text                                 |
| `error`   | Red X icon + message text + `"Try again"` inline link           |

### 7.5 `SuccessToast`

New component for post-save feedback.

- Fixed position: `bottom-4 right-4`
- `bg-green-900 border border-green-800 text-green-200 text-sm rounded px-4 py-2.5`
- Auto-dismisses after 4000ms via `setTimeout`
- Has a close button (`aria-label="Dismiss"`)
- `role="status"` and `aria-live="polite"` so screen readers announce it

---

## 8. User Flows

### 8.1 First-run happy path

```
App loads
  -> GET /api/config/status returns { configured: false }
  -> Redirect to /setup

/setup, Step 1: Proxmox Connection
  -> User fills all 4 fields
  -> Inline validation on blur (host URL format, required fields)
  -> All valid: "Next" button enabled
  -> Click "Next"

Step 2: Discovery
  -> User reviews defaults (300s, VMs off, SSL off)
  -> SSL warning visible (default)
  -> Click "Next"

Step 3: SSH
  -> SSH enabled by default, username "root" pre-filled
  -> User selects "Key file", enters path
  -> Click "Next"

Step 4: GitHub Token
  -> User skips (optional)
  -> Click "Next" -> "Review"

Step 5: Review & Save
  -> User reads summary
  -> Clicks "Test Connection"
  -> POST /api/config/test -> { ok: true }
  -> Green result appears
  -> "Save & Start" becomes enabled
  -> User clicks "Save & Start"
  -> POST /api/config/save
  -> Transition screen: "Discovering your guests..."
  -> Poll GET /health every 2s
  -> guest_count > 0 -> redirect to /
```

### 8.2 Connection test failure

```
Step 5: Review & Save
  -> Clicks "Test Connection"
  -> POST /api/config/test -> { ok: false, error: "401 Unauthorized - invalid token" }
  -> Red inline result: "Connection failed: 401 Unauthorized - invalid token"
  -> "Save & Start" remains disabled
  -> User clicks "Back" to return to Step 1
  -> Corrects token secret
  -> Advances to Step 5 again
  -> Re-runs test -> success
```

### 8.3 Skip test and save anyway

```
Step 5: Review & Save
  -> User has not run test (or test failed)
  -> Clicks "Skip test and save anyway"
  -> "Save & Start" becomes enabled (border changes to dashed amber to signal caution)
  -> User clicks "Save & Start"
  -> Flow continues as happy path
```

### 8.4 Settings edit happy path

```
User navigates to /settings
  -> GET /api/settings returns current settings
  -> Page renders with all fields populated
  -> Token Secret shows ●●●●●●●● with eye icon

User changes poll interval from 300 to 120
  -> "• Unsaved changes" indicator appears
  -> "Save Changes" button becomes active

User clicks "Test Connection" (optional, within Proxmox card)
  -> POST /api/config/test -> { ok: true }
  -> Green result

User clicks "Save Changes"
  -> PUT /api/settings with updated payload
  -> Spinner in button
  -> Success: toast appears "Settings saved. Discovery restarting..."
  -> Unsaved indicator clears
  -> Discovery restarts on backend
```

### 8.5 Navigate away with unsaved changes

```
User edits a field
  -> "• Unsaved changes" visible
  -> Clicks "< Dashboard" breadcrumb link
  -> Browser fires beforeunload
  -> Native dialog: "Leave page? Changes you made may not be saved."
  -> User confirms -> navigate to /
  -> User cancels -> stays on /settings
```

---

## 9. Validation Rules

### Required fields

| Field              | Rule                                           | Error message                                    |
|--------------------|------------------------------------------------|--------------------------------------------------|
| Proxmox Host       | Non-empty, starts with `http://` or `https://` | "Enter a valid URL starting with http:// or https://" |
| Token ID           | Non-empty                                      | "Token ID is required"                           |
| Token Secret       | Non-empty                                      | "Token Secret is required"                       |
| Node Name          | Non-empty                                      | "Node name is required"                          |
| SSH Username       | Non-empty when SSH enabled                     | "Username is required when SSH is enabled"       |
| SSH Key Path       | Non-empty when auth = key file                 | "Key path is required"                           |
| SSH Password       | Non-empty when auth = password                 | "Password is required"                           |
| Poll Interval      | Integer, 30–3600                               | "Must be between 30 and 3600 seconds"            |

### Validation timing

- **On blur**: validate the field that just lost focus
- **On submit/Next**: validate all fields in the current step
- **While typing**: clear the error for the field being edited (do not show new errors mid-type)
- **No server-side validation on every keystroke** — only on explicit Test Connection or Save

---

## 10. Error States Reference

| Scenario                          | Component          | Message pattern                                                   |
|-----------------------------------|--------------------|-------------------------------------------------------------------|
| Required field empty              | Inline field error | `"<Field name> is required"`                                      |
| Host URL malformed                | Inline field error | `"Enter a valid URL starting with http:// or https://"`           |
| Poll interval out of range        | Inline field error | `"Must be between 30 and 3600 seconds"`                           |
| Connection test failed            | `ConnectionTestResult` | `"Connection failed: <backend error message>"`                |
| Save failed (validation)          | `ErrorBanner` top of page | `"Save failed: <backend error message>"`                   |
| Save failed (backend unreachable) | `ErrorBanner` top of page | `"Could not reach the proxmon backend. Is it running?"`    |
| Settings load failed              | `ErrorBanner` (existing) | `"Failed to load settings. <Retry>"` (existing behavior)   |

---

## 11. ASCII Wireframes

### 11.1 Wizard Step 1: Proxmox Connection

```
+----------------------------------------------------------+
| proxmon                                                  |
+----+---+----------------------------------------------+--+
     |   |                                              |
     | Step 1 of 5     [=====----]  Proxmox Connection |
     |   |                                              |
     |   +----------------------------------------------+
     |   |                                              |
     |   |  Proxmox Host *                              |
     |   |  +----------------------------------------+  |
     |   |  | https://192.168.1.10:8006              |  |
     |   |  +----------------------------------------+  |
     |   |                                              |
     |   |  API Token ID *                              |
     |   |  +----------------------------------------+  |
     |   |  | root@pam!mytoken                       |  |
     |   |  +----------------------------------------+  |
     |   |                                              |
     |   |  API Token Secret *                          |
     |   |  +-------------------------------------+[eye] |
     |   |  | ••••••••••••••••••••••••••••••••    |     |
     |   |  +-------------------------------------+----+ |
     |   |                                              |
     |   |  Node Name *                                 |
     |   |  +----------------------------------------+  |
     |   |  | pve                     [red: required] |  |
     |   |  +----------------------------------------+  |
     |   |  ! Node name is required                     |
     |   |                                              |
     |   +----------------------------------------------+
     |                                                  |
     |                              [Next ->]           |
     +--------------------------------------------------+
```

Notes:
- Disabled "Next" button when any required field is empty or invalid
- Error state on "Node Name" shown as example: red border on input, red helper text below

### 11.2 Editable Settings Page

```
+----------------------------------------------------------+
| proxmon                                       [Settings] |
+----------------------------------------------------------+
| [!] Save failed: Connection refused                   X  |
|                                                          |
| < Dashboard    Settings          [• Unsaved changes]     |
|                                                          |
| +------------------------------------------------------+ |
| | PROXMOX CONNECTION                                   | |
| |                                                      | |
| |  Proxmox Host *                                      | |
| |  [https://192.168.1.10:8006                       ]  | |
| |                                                      | |
| |  API Token ID *                                      | |
| |  [root@pam!mytoken                                ]  | |
| |                                                      | |
| |  API Token Secret *                                  | |
| |  [••••••••••••••••••••••••••••           ] [eye]     | |
| |                                                      | |
| |  Node Name *                                         | |
| |  [pve                                             ]  | |
| |                                                      | |
| |  [Test Connection]                                   | |
| |  v Connected — Proxmox 8.1 responding on node pve    | |
| +------------------------------------------------------+ |
|                                                          |
| +------------------------------------------------------+ |
| | DISCOVERY                                            | |
| |                                                      | |
| |  Poll Interval (s) *                                 | |
| |  [120                                             ]  | |
| |                                                      | |
| |  Include VMs   [  OFF  ]                             | |
| |                                                      | |
| |  Verify SSL    [  OFF  ]                             | |
| |  [!] SSL verification is disabled. Proxmox uses     | |
| |      self-signed certificates by default.            | |
| +------------------------------------------------------+ |
|                                                          |
| +------------------------------------------------------+ |
| | SSH                                                  | |
| |                                                      | |
| |  Enable SSH    [  ON   ]                             | |
| |                                                      | |
| |  Username *                                          | |
| |  [root                                            ]  | |
| |                                                      | |
| |  Authentication                                      | |
| |  (o) Key file   ( ) Password                         | |
| |                                                      | |
| |  Private Key Path                                    | |
| |  [/root/.ssh/id_ed25519                           ]  | |
| +------------------------------------------------------+ |
|                                                          |
| +------------------------------------------------------+ |
| | GITHUB TOKEN                                         | |
| |                                                      | |
| |  A personal access token increases the GitHub API    | |
| |  rate limit from 60 to 5,000 req/hr.                 | |
| |  Leave blank for unauthenticated access.             | |
| |                                                      | |
| |  GitHub Token                                        | |
| |  [                                        ] [eye]    | |
| +------------------------------------------------------+ |
|                                                          |
+----------------------------------------------------------+
| [sticky]                   [Save Changes]                |
+----------------------------------------------------------+
```

---

## 12. Accessibility Notes

### Keyboard Navigation

- Tab order follows DOM order: nav -> page header -> card 1 fields -> card 2 fields -> ... -> sticky save button
- All interactive elements (inputs, toggles, buttons, eye icons) are reachable by Tab
- Toggle component uses `role="switch"` and responds to Space and Enter keys
- Radio buttons in SSH auth method: arrow keys navigate between options (standard radio behavior)
- Wizard Back/Next buttons: keyboard accessible, Next is last in tab order within step card
- "Skip test and save anyway" link: included in tab order after Save & Start button

### ARIA Labels

| Element                     | ARIA attribute                                          |
|-----------------------------|---------------------------------------------------------|
| Wizard progress indicator   | `role="progressbar"`, `aria-valuenow`, `aria-valuemin`, `aria-valuemax`, `aria-label="Setup progress, step N of 5"` |
| Password show/hide toggle   | `aria-label="Show API Token Secret"` / `"Hide API Token Secret"` |
| SSH enable toggle           | `aria-label="Enable SSH"`, `aria-expanded={sshEnabled}` |
| Connection result area      | `role="status"` on success, `role="alert"` on error     |
| Error banner                | `role="alert"`, `aria-live="assertive"` (existing)      |
| Success toast               | `role="status"`, `aria-live="polite"`                   |
| Required field asterisk     | Wrapped in `<span aria-hidden="true">` (spoken via `aria-required`) |
| Inline field error          | `id="<field>-error"`, referenced by input `aria-describedby` |
| Save Changes button         | `aria-disabled="true"` when no unsaved changes          |

### Focus Management

- On wizard step change: focus moves to the step card heading (`<h2>`, `tabIndex={-1}`)
- On connection test result: focus stays on the button; result announced via `role="alert"`
- On save success: focus stays on save button; toast announced via `aria-live="polite"`
- On save failure: focus moves to `ErrorBanner` heading

### Color and Contrast

- All text meets WCAG AA: `text-gray-200` on `bg-surface` (#1a1d27) >= 4.5:1
- Error red (`text-red-400`) on `bg-surface`: >= 3:1 (acceptable for UI components per WCAG 1.4.11)
- Blue-500 on dark background: >= 3:1 for interactive elements
- Do not use color alone to convey state: all error states include icon or text label in addition to red color

### Reduced Motion

- Spinner animation: wrap in `@media (prefers-reduced-motion: reduce)` to pause or remove
- Toggle transition: controlled via `transition-colors` utility; will respect `prefers-reduced-motion` via Tailwind's `motion-safe` variant if applied

---

## 13. Acceptance Criteria

### Wizard

- [ ] Dashboard and guest routes are inaccessible when `configured: false`; browser redirects to `/setup`
- [ ] Step indicator correctly reflects current step and marks completed steps
- [ ] "Next" on Step 1 is disabled until all 4 required fields have values and Host URL format is valid
- [ ] Validation errors appear on blur, not on keystroke
- [ ] SSH section collapses fully when "Enable SSH" is toggled off
- [ ] Auth method radio change swaps the key path / password field without clearing the other
- [ ] Token Secret and SSH Password fields default to `type="password"` and toggle correctly
- [ ] Step 5 summary masks secrets per the rules in section 4.8
- [ ] "Test Connection" fires `POST /api/config/test` with current form values (not yet saved)
- [ ] "Save & Start" is disabled until connection test passes OR user explicitly clicks "Skip test"
- [ ] After successful save, transition screen appears and polls `/health` every 2s
- [ ] Redirect to `/` occurs when `guest_count > 0` or after 30s timeout

### Settings Page

- [ ] All fields are editable (no read-only display)
- [ ] Token Secret loads masked; eye icon reveals/hides plaintext
- [ ] "Unsaved changes" indicator appears on first edit, disappears after save
- [ ] "Save Changes" is disabled when there are no changes or required fields are invalid
- [ ] Navigating away with unsaved changes triggers `beforeunload` browser dialog
- [ ] Save triggers `PUT /api/settings` and shows success toast on `200 OK`
- [ ] Backend error on save shows `ErrorBanner` at top of page (not a modal)
- [ ] SSL warning is visible when Verify SSL is toggled off

---

## 14. Out of Scope

- Log level configuration (existing env-only setting, not exposed in UI)
- Plugin/detector enable-disable toggles (all detectors run automatically)
- User authentication / login screen (proxmon has no multi-user concept)
- Dark/light mode toggle (dark mode only)
- Mobile layout below 375px viewport width
