# UX Spec: Version Detection Provenance Panel

**Feature:** Version Detection section in `GuestDetail` view
**Status:** Draft
**Component:** `frontend/src/components/GuestDetail.tsx`

---

## Problem Statement

Users see an installed version and a latest version on the guest detail page but have no way to understand how either value was obtained. This matters for debugging — if a version is missing or wrong, the user needs to know whether the problem is in the HTTP probe, the SSH fallback, the `pct exec` path, or the GitHub release lookup.

---

## User Stories

| # | As a... | I want to... | So that... |
|---|---------|-------------|------------|
| 1 | dashboard user | see how the installed version was detected | I know whether to check the app's HTTP API, SSH access, or container exec |
| 2 | dashboard user | see which GitHub repository was queried for the latest version | I can verify the release data is coming from the right place |
| 3 | dashboard user | understand why version data is missing | I can take a corrective action rather than assume it is a bug |
| 4 | power user | get a quick diagnostic summary without reading raw JSON output | I can triage version detection issues at a glance |

---

## Acceptance Criteria

- [ ] A "Version Detection" panel is rendered on the guest detail page whenever an app is detected (`guest.app_name !== null`)
- [ ] The panel is not rendered when no app has been detected (no orphan section for guests with no app)
- [ ] The installed version detection method is displayed with a human-readable label for each valid value (`http`, `ssh`, `pct_exec`) and a clearly marked unknown state
- [ ] The latest version source shows the GitHub repository slug when it can be derived from `GITHUB_REPOS[guest.detector_used]` (already present in the component), or a "not available" marker when it cannot
- [ ] All states — data present, data missing, null method — are handled without crashing or rendering empty rows
- [ ] No new API calls are made; all data comes from the existing `GuestDetail` response
- [ ] The panel style matches the existing `App Detection` and `Version Status` panels exactly: `p-4 rounded bg-surface border border-gray-800`, `text-xs font-medium text-gray-500 uppercase tracking-wider` heading, `space-y-1 text-sm` row list
- [ ] Screen readers can navigate the panel and every row label/value pair is announced correctly
- [ ] Color is never the only signal; method badges include a text label alongside any color

---

## Data Available in `GuestDetail` Response

| Field | Type | Notes |
|-------|------|-------|
| `version_detection_method` | `"http" \| "ssh" \| "pct_exec" \| null` | How installed version was obtained |
| `installed_version` | `string \| null` | The version string found |
| `latest_version` | `string \| null` | From GitHub releases cache |
| `detector_used` | `string \| null` | Plugin key, e.g. `"sonarr"` |
| `app_name` | `string \| null` | Display name |

The GitHub repo is NOT in the API response. It must be derived client-side from the existing `GITHUB_REPOS` map already in `GuestDetail.tsx`. This is the same map used to build `releaseUrl` today, so no new client-side logic is required beyond reading `githubRepo` (already computed at line 45).

---

## Layout and Visual Design

### Position

Place the panel **between "Version Status" and "Version History"** — it is a diagnostic detail that belongs after the primary version values are shown but before the historical log.

```
[App Detection]
[Version Status]
[Version Detection]   <-- NEW
[Version History]
[Raw Detection Output]
```

### Panel Structure

```
┌─────────────────────────────────────────────────────────────┐
│  VERSION DETECTION                                          │
│                                                             │
│  Installed version source   HTTP API                        │
│  Endpoint probed            http://10.0.0.5:8989/api/v3/…  │ (future)
│                                                             │
│  Latest version source      GitHub Releases                 │
│  Repository                 Sonarr/Sonarr                   │
└─────────────────────────────────────────────────────────────┘
```

The endpoint row is marked as **future scope** — the backend does not currently return the exact URL probed. The spec documents it so the row can be added without redesign when backend support is added.

### Row Definitions

#### Row 1: Installed version source

Label: `Installed version source`

| `version_detection_method` value | Displayed value | Accessible description |
|----------------------------------|-----------------|------------------------|
| `"http"` | `HTTP API` | Method: HTTP API probe |
| `"ssh"` | `SSH command` | Method: SSH command |
| `"pct_exec"` | `Container exec (pct)` | Method: Proxmox container exec |
| `null` and `installed_version` is non-null | `Unknown` | Method: unknown |
| `null` and `installed_version` is null | `Not detected` | Method: not detected |

The value is rendered as a small inline badge using `font-mono text-xs px-1.5 py-0.5 rounded`. Badge colors:

| Method | Background | Text | Note |
|--------|-----------|------|------|
| `http` | `bg-blue-900/40` | `text-blue-300` | Always paired with text label |
| `ssh` | `bg-yellow-900/40` | `text-yellow-300` | Always paired with text label |
| `pct_exec` | `bg-purple-900/40` | `text-purple-300` | Always paired with text label |
| Unknown / not detected | `bg-gray-800` | `text-gray-500` | Muted; no strong color |

Color is decorative only — the text label is always present.

#### Row 2: Latest version source

Label: `Latest version source`

Always displays: `GitHub Releases` (this is the only mechanism used today).

If `latest_version` is null, add a muted qualifier: `GitHub Releases (not found)`.

#### Row 3: Repository

Label: `Repository`

| Condition | Displayed value |
|-----------|-----------------|
| `githubRepo` is non-null | The repo slug as a link to `https://github.com/{repo}/releases`, e.g. `Sonarr/Sonarr →` |
| `githubRepo` is null | `— (unknown)` in `text-gray-500` |

The link uses the same style as the existing release notes link: `text-xs text-blue-400 hover:text-blue-300`. `aria-label` must read `"GitHub releases for {repo} (opens in new tab)"`.

---

## All States

### State 1: All data present

```
VERSION DETECTION

Installed version source    [HTTP API]
Latest version source       GitHub Releases
Repository                  Sonarr/Sonarr →
```

### State 2: Installed via SSH, no GitHub repo mapped

```
VERSION DETECTION

Installed version source    [SSH command]
Latest version source       GitHub Releases (not found)
Repository                  — (unknown)
```

### State 3: version_detection_method is null, version was found

```
VERSION DETECTION

Installed version source    [Unknown]
Latest version source       GitHub Releases
Repository                  Sonarr/Sonarr →
```

### State 4: No version found at all

```
VERSION DETECTION

Installed version source    [Not detected]
Latest version source       GitHub Releases (not found)
Repository                  Sonarr/Sonarr →
```

### State 5: No app detected (panel suppressed)

Panel is not rendered. No empty section.

---

## Accessibility Notes

- Panel `<div>` has no role override; `<h2>` provides landmark structure (consistent with other panels).
- Each row is a `<div>` with a `<span>` label and a `<span>` value — not a `<dl>` to remain consistent with the existing App Detection and Version Status panels.
- The method badge `<span>` uses `aria-label` to provide a description that does not rely on color: e.g. `aria-label="Installed version source: HTTP API"`.
- The repository link includes `target="_blank" rel="noopener noreferrer"` and an explicit `aria-label`.
- The panel is keyboard-reachable via natural tab order (only interactive element is the optional repo link).

---

## Component Pseudocode

This is not production code. It describes the rendering logic to guide implementation.

```
function versionMethodLabel(method, installedVersion):
  if method == "http"     → { label: "HTTP API",              badge: "blue"   }
  if method == "ssh"      → { label: "SSH command",           badge: "yellow" }
  if method == "pct_exec" → { label: "Container exec (pct)",  badge: "purple" }
  if installedVersion != null → { label: "Unknown",           badge: "gray"   }
  else                        → { label: "Not detected",      badge: "gray"   }

render panel only if guest.app_name != null

rows:
  "Installed version source" → versionMethodLabel(guest.version_detection_method, guest.installed_version)
  "Latest version source"    → guest.latest_version ? "GitHub Releases" : "GitHub Releases (not found)"
  "Repository"               → githubRepo ? <link>{githubRepo}</link> : "— (unknown)"
```

---

## Out of Scope (Future)

- Showing the exact HTTP endpoint probed (requires backend change to expose it in `raw_detection_output` or a dedicated field).
- Showing SSH connection details (host, username, port) — sensitive, requires deliberate design.
- Adding "Retry detection" action — belongs in a separate operations spec.
- Persisting version detection method in `VersionCheck` history rows (would require a DB schema change).

---

## Implementation Notes for Engineer

- `githubRepo` is already computed at line 45 of `GuestDetail.tsx` — reuse it directly.
- `GITHUB_REPOS` map at line 10 covers the current detector set. When new detectors are added, both the map and `registry.py` must be updated together.
- The panel should be a small inline section, not a new component file, to match the existing pattern in `GuestDetail.tsx`.
- No new props, no new API fields, no new hooks required.
