# Code Review Report — proxmon Full Codebase

**Date:** 2026-03-10
**Reviewer:** Claude Code (principal engineer review)
**Branch:** `claude/feature/sort-pct-exec-multi-host`
**Scope:** Full codebase — backend, frontend, tests, config

---

## Executive Summary

proxmon is a well-structured monitoring application. The code shows clear attention to security (secret masking, SSH injection guards, HMAC-safe API key comparison) and a deliberate architecture (detector plugin pattern, config-store abstraction, multi-host namespacing). The test suite is broad and covers most critical paths.

The review found no critical security vulnerabilities. The most important issues are: a **dead configuration option** (`version_detect_method` is persisted and exposed but never consumed by the engine), a **silent SSRF vector** in the connection-test endpoint, a **SQL injection-safe but unvalidated** host ID field, and a handful of medium-priority issues around type safety, code duplication, and test coverage gaps.

---

## Summary

| Severity | Count |
|---|---|
| BLOCKER | 2 |
| HIGH | 5 |
| MEDIUM | 7 |
| LOW / Nit | 5 |

---

## BLOCKER — Must Fix Before Merge

### B-1: `version_detect_method` setting is a no-op — the engine ignores it

**File:** `backend/app/core/discovery.py:384-432`
**Also:** `backend/app/config.py:67`, `backend/app/api/routes.py:100,457`

The setting `version_detect_method` (values: `pct_first`, `ssh_first`, `ssh_only`, `pct_only`) is saved to the database, returned from the API, and shown in the UI dropdown. However, `_check_version()` in `discovery.py` always runs HTTP probe, then pct exec (if enabled and has a command), then SSH — regardless of what this field is set to. The ordering cannot be changed by the user.

This is a correctness blocker: the feature is documented in the UX spec (`prd-sort-pct-multi-host.md`), shown to users in the settings form, but has zero effect on behaviour. A user who sets `ssh_only` to avoid HTTP probes will still have HTTP probes executed.

**Fix:** Read `self._settings.version_detect_method` inside `_check_version()` and gate the HTTP probe and pct/SSH branches accordingly. Example skeleton:

```python
method = (self._settings.version_detect_method if self._settings else "pct_first")
if method not in ("ssh_only", "pct_only"):
    # attempt HTTP probe
    ...
if method in ("pct_first", "pct_only") and pct_exec_enabled:
    # attempt pct exec
    ...
elif method in ("ssh_first", "ssh_only") and ssh_version_cmd:
    # attempt SSH first
    ...
```

---

### B-2: SSRF via unvalidated `proxmox_host` in the connection-test endpoint

**File:** `backend/app/api/routes.py:342-393`

`POST /api/settings/test-connection` accepts `proxmox_host` as a free-form string and immediately constructs a URL from it:

```python
base_url = f"{body.proxmox_host.rstrip('/')}/api2/json"
```

The `ConnectionTestRequest` model performs no URL validation. Unlike `SettingsSaveRequest`, which has `validate_host()` requiring an `http://` or `https://` prefix, `ConnectionTestRequest` has none. An attacker who can reach this endpoint (or who operates without `PROXMON_API_KEY` configured) can probe internal services at arbitrary URLs, including `file://`, `ftp://`, or `http://169.254.169.254` (cloud metadata).

Note: this endpoint requires `_require_api_key`, so the risk is limited when an API key is configured. But the API key is optional (defaults to unauthenticated access), making this a SSRF that is exploitable by default in a fresh install.

**Fix:** Add the same `validate_host` validator to `ConnectionTestRequest`, or reuse the existing one:

```python
class ConnectionTestRequest(BaseModel):
    proxmox_host: str
    ...

    @field_validator("proxmox_host")
    @classmethod
    def validate_host(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("Host must start with http:// or https://")
        return v.rstrip("/")
```

---

## HIGH — Strongly Recommend Fixing Before Merge

### H-1: `proxmox_hosts[].id` is stored verbatim but never validated — injection / collision risk

**File:** `backend/app/api/routes.py:72-83`, `backend/app/core/discovery.py:141`

`ProxmoxHostSaveEntry.id` is an unvalidated free-form string that is (a) stored directly in the JSON blob without sanitisation, (b) used as a namespace prefix when building guest IDs (`f"{host_config.id}:{guest.id}"`), and (c) used as a lookup key when merging existing hosts.

An operator-supplied id like `"default:100"` would collide with a namespaced guest ID from another host. A colon in the id breaks the `guest.id.split(":")[-1]` vmid extraction used for pct exec, leading to an invalid vmid that passes silently.

**Fix:** Add a field validator that enforces a safe character set:

```python
@field_validator("id")
@classmethod
def validate_id(cls, v: str) -> str:
    if not re.match(r'^[a-zA-Z0-9_-]{1,64}$', v):
        raise ValueError("Host id must be 1-64 alphanumeric/-/_ characters")
    return v
```

---

### H-2: GitHub cache is not thread-safe — shared mutable dict with no lock

**File:** `backend/app/core/github.py:22,37-50`

`GitHubClient._cache` is a plain `dict` mutated by concurrent async tasks during multi-host discovery. Under CPython's GIL this is unlikely to corrupt the dict, but it can produce logical races: two tasks discover a cache miss for the same repo simultaneously, both issue the API request, and the slower one overwrites a potentially fresher timestamp with a stale one. This wastes GitHub rate limit tokens.

**Fix:** Use an `asyncio.Lock` per-repo (or a single lock around cache reads/writes). Alternatively, check-then-fetch using an `asyncio.Event` as a per-key in-flight guard.

---

### H-3: `_execute_sync` and `_execute_sync_with_stderr` are near-identical — SRP violation and maintenance hazard

**File:** `backend/app/core/ssh.py:221-323`

These two methods share the same connection setup, credential resolution, and exception structure, differing only in whether they return `str | None` or `tuple[str, str]`. A future change to connection logic (e.g. adding known-hosts support, changing timeouts) must be applied in both places. This is exactly the kind of non-trivial duplication that causes bugs.

**Fix:** Extract the shared connection + command execution into a private `_raw_execute(host, command, timeout, **creds) -> tuple[str, str]`, then have both callers wrap it:

```python
def _execute_sync(self, host, command, timeout, **kwargs) -> str | None:
    out, _ = self._raw_execute(host, command, timeout, **kwargs)
    return out or None

def _execute_sync_with_stderr(self, host, command, timeout, **kwargs) -> tuple[str, str]:
    return self._raw_execute(host, command, timeout, **kwargs)
```

---

### H-4: `_check_version` always attempts HTTP version probe even when `ssh_only` or `pct_only` is set

This is the runtime manifestation of B-1 at the `_check_version` level. Even setting aside the `version_detect_method` flag, the current code always calls `detector.get_installed_version()` regardless of whether the caller intends to use SSH or pct exec. For apps behind an API key the unauthenticated HTTP probe returns 401, is silently swallowed, and then SSH takes over — producing an unnecessary outbound HTTP connection per poll cycle per guest. Captured as separate high-priority item because it has observable side effects independent of the dead-flag issue.

**Fix:** Same as B-1 — gate HTTP probe on `version_detect_method`.

---

### H-5: Discovery's `_run_single_host_cycle` uses legacy (non-namespaced) guest IDs while `_run_host_cycle` namespaces them — inconsistency breaks multi-host transition

**File:** `backend/app/core/discovery.py:59-66`, `93-121`

When `settings.proxmox_hosts` is empty, `run_full_cycle()` falls through to `_run_single_host_cycle()`, which produces bare guest IDs like `"100"`. When a user later adds `proxmox_hosts`, the same host now goes through `_run_host_cycle()`, producing `"default:100"`. All previously stored `GuestInfo` objects in `scheduler._guests` have bare IDs that no longer match, so version history is lost on the next poll after saving. Guests the user was tracking become "new" guests with empty history.

Additionally, the single-host path never sets `host_id` or `host_label` on guests, so the dashboard "Host" column is always blank until the user saves and has at least one proxmox_hosts entry.

**Fix:** Remove `_run_single_host_cycle()` entirely — the `_migrate_multi_host()` in `ConfigStore` already converts legacy flat config to `proxmox_hosts` at startup, so `get_hosts()` should always return at least one entry. If it does not, return early cleanly. This collapses the two code paths into one.

---

## MEDIUM — Consider for Follow-up

### M-1: `version_detect_method` validator missing — any string is accepted

**File:** `backend/app/api/routes.py:100`

The `SettingsSaveRequest.version_detect_method` field accepts any string. There is no `@field_validator` that restricts it to the four valid values. The UI only shows valid options, but the API is unguarded.

**Fix:**
```python
@field_validator("version_detect_method")
@classmethod
def validate_version_detect_method(cls, v: str) -> str:
    valid = {"pct_first", "ssh_first", "ssh_only", "pct_only"}
    if v not in valid:
        raise ValueError(f"version_detect_method must be one of {valid}")
    return v
```

---

### M-2: `log_level` field is accepted as a free-form string with no validation

**File:** `backend/app/api/routes.py:99`

`log_level` is stored and presumably passed to Python's logging system, but any arbitrary string is accepted. An invalid level would silently fail or produce unexpected logging behaviour.

**Fix:** Add a validator:
```python
@field_validator("log_level")
@classmethod
def validate_log_level(cls, v: str) -> str:
    if v.lower() not in {"debug", "info", "warning", "error", "critical"}:
        raise ValueError("Invalid log level")
    return v.lower()
```

---

### M-3: `pct_exec_tried` variable is computed but never meaningfully used

**File:** `backend/app/core/discovery.py:385-392`

`pct_exec_tried` is set to `True` when the pct exec block runs but is never read after that. The SSH version-cmd block's guard is `guest.version_detection_method != "pct_exec"`, which correctly reflects pct exec success without needing this variable. It is dead code.

**Fix:** Remove `pct_exec_tried`.

---

### M-4: `DETECTORS` list in `Settings.tsx` is a hardcoded duplicate of the backend registry

**File:** `frontend/src/components/Settings.tsx:15-31`

The frontend maintains its own hardcoded list of detector names and display names. The backend already exposes `GET /api/app-config/defaults` specifically for this purpose. If a new detector is added to the registry, a developer must remember to update both places. The same endpoint is used by `AppConfigSection` correctly but the Plugins section in `Settings.tsx` still uses the hardcoded constant.

**Fix:** Fetch from `/api/app-config/defaults` in a `useEffect` and derive the plugin list from the response, or have `AppConfigSection` pass the loaded defaults up. The hardcoded `DETECTORS` const can then be removed.

---

### M-5: `GITHUB_REPOS` in `GuestDetail.tsx` is a stale hardcoded map that does not include `overseerr` or `seer`

**File:** `frontend/src/components/GuestDetail.tsx:10-23`

This map is used to construct the "View release notes" link. It is missing `overseerr` and `seer`, so those apps never show a release link even when a latest version is known. The backend already returns `github_repo_queried` on `GuestDetail`, which is the authoritative source.

**Fix:** Use `guest.github_repo_queried` directly instead of maintaining this map:
```tsx
const releaseUrl = guest.github_repo_queried && guest.latest_version
  ? `https://github.com/${guest.github_repo_queried}/releases`
  : null;
```
Remove the `GITHUB_REPOS` constant.

---

### M-6: `_http_get` in `BaseDetector` creates a new `httpx.AsyncClient` per call when no shared client is provided

**File:** `backend/app/detectors/base.py:85`

```python
ctx = contextlib.nullcontext(client) if client else httpx.AsyncClient(timeout=timeout, verify=False, follow_redirects=True)
```

When `http_client` is `None` (unit tests, or direct instantiation), a fresh `AsyncClient` is created for every `_http_get` call. This creates and tears down a connection pool on each call, increasing latency and resource usage. The discovery engine does pass a shared client, so this only matters in edge cases — but the fallback `verify=False` is also noteworthy: it disables SSL verification unconditionally for all self-created clients regardless of user settings.

**Fix:** Make the fallback client inherit the verify setting, or document that the shared client must always be provided in production paths.

---

### M-7: `initHostsFromSettings` in `Settings.tsx` seeds `ssh_password` from `FullSettings` without masking detection

**File:** `frontend/src/components/Settings.tsx:75-108`

When seeding from flat legacy fields (`s.proxmox_host`), the function copies `s.ssh_password` directly into the host object. If the backend returns `"***"`, that sentinel ends up in `host.ssh_password`. When the user saves without touching that field, `hostsPayload` sends `null` (because `h.ssh_password === '***'` → `null`). This works, but the condition is only checked in `handleSave`'s payload builder, not in the initial state. If the user renders the component, never touches the field, and saves — the round-trip is correct. But if they render the component and inspect the React state, they would see `"***"` as the actual SSH password value, which is misleading.

**Fix:** Strip the sentinel during `initHostsFromSettings`:
```ts
ssh_password: (s.ssh_password && s.ssh_password !== '***') ? s.ssh_password : null,
```

---

## LOW / Nit

### L-1: `useMultiHost = true` is a hardcoded constant that still has a dead legacy branch

**File:** `frontend/src/components/Settings.tsx:130`

`const useMultiHost = true;` is never configurable. The legacy single-host JSX block inside `{useMultiHost ? ... : <legacy block>}` is dead code that will never render. This adds ~50 lines of unmaintained JSX.

**Fix:** Remove the dead legacy `else` branch and the `useMultiHost` constant.

---

### L-2: `compareSemver` in `Dashboard.tsx` silently falls back to string comparison on any NaN segment

**File:** `frontend/src/components/Dashboard.tsx:14-25`

If any segment is `NaN` after `Number()`, the function falls back to `a.localeCompare(b)` on the full original string. Version strings like `"1.40.0.7998-c29d4c0c8"` have a trailing build hash after splitting on `.`, which becomes `NaN`. This causes numeric version sorting to silently degrade to string sorting for Plex-style versions. The backend already normalises these strings before comparison, but the frontend sort is independent.

**Fix:** Pre-strip the build-hash suffix before parsing (mirror `_normalize_version_string` from `discovery.py`), or clamp to the first 4 dot-segments before `Number()`.

---

### L-3: `ProxmoxHostConfig` model stores `token_secret` and `ssh_password` as `str` (not `str | None`) but defaults to empty string

**File:** `backend/app/config.py:29,33`

`token_secret: str = ""` and `ssh_password: str | None = None` — inconsistent optionality. An empty string `token_secret` is falsy in Python but passes `if token_secret:` checks inconsistently. The API returns `"***"` when the secret is set, and the save handler uses `_keep_or_replace()` to guard it. But `get_hosts()` at line 99 passes `self.proxmox_token_secret or ""`, which can produce a host with a non-None but empty secret that the ProxmoxClient will send as `PVEAPIToken=id=` in the Authorization header — resulting in a 401 that surfaces only at poll time, not at startup.

**Fix:** Make `token_secret: str | None = None` and propagate the None sentinel consistently, or add a startup check in `Scheduler.start()` that validates the host config before creating the task.

---

### L-4: `SeerDetector` has incorrect `github_repo` — `seerr-team/seerr` likely should be `seerr-team/overseerr` or the actual Seer repo

**File:** `backend/app/detectors/seer.py:15`

The `github_repo` field is `"seerr-team/seerr"` but no such public repository exists at this slug as of the review date. The detector shares port 5055 with Overseerr, which suggests it may be targeting the Jellyseerr fork or another Seer variant. This will cause GitHub lookups to return `None` for all guests detected as Seer, and `github_lookup_status` will always be `"failed"`.

**Fix:** Verify the correct repository slug and update. If Seer has no GitHub releases, set `github_repo = None`.

---

### L-5: No test for `pct exec` path in `discovery.py`

**File:** `backend/tests/test_discovery.py`

`_check_version`'s pct exec branch (`run_pct_exec`) and the `ssh_version_cmd` SSH branch are untested at the integration level. The only test for `execute_version_cmd` and `run_pct_exec` is at the unit level in `test_ssh_version_cmd.py`, which mocks `_execute_sync`. The full path from `DiscoveryEngine._check_version` through `SSHClient.run_pct_exec` is never exercised in tests.

**Fix:** Add a `TestDiscoveryEngine` test that configures a guest with `pct_exec_enabled=True`, mocks `SSHClient.run_pct_exec`, and asserts that `version_detection_method == "pct_exec"` on the resulting guest.

---

## What Is Done Well

**Security fundamentals are solid.** `hmac.compare_digest` for API key comparison, SSH command whitelist with metacharacter rejection, per-segment pipe validation (`_PIPE_SAFE_COMMANDS`), and the `_keep_or_replace()` sentinel pattern are all implemented correctly and thoroughly. The SSH WarningPolicy fallback with a clear path to `RejectPolicy` is appropriately defensive.

**Secret masking is consistent.** All secrets are masked in `GET /api/settings/full`, the `masked_settings()` helper, and the per-app config response. The `changedApiKeys` ref in the frontend correctly prevents "***" from being written back over stored secrets.

**Detector pattern is clean and extensible.** The `BaseDetector` ABC with its `detect()` / `get_installed_version()` contract makes adding new detectors straightforward. Name-token matching with `re.split` avoids naive substring false positives.

**Multi-host namespacing is correct.** Guest IDs are properly scoped to `{host_id}:{vmid}`, host discovery is parallelised with `asyncio.gather`, and errors from individual hosts are isolated and logged without aborting the full cycle.

**Version comparison is robust.** `_normalize_version_string` strips build-hash suffixes while preserving pre-release labels. The `packaging.Version` fallback to string equality handles edge cases gracefully.

**Test coverage is meaningful.** Tests exercise the happy path, error paths (timeouts, 401s), API key forwarding, port overrides, scheme overrides, GitHub repo overrides, config migration, multi-host migration, and SSH command validation. The `respx` mocking approach tests full HTTP plumbing without hitting the network.

**Frontend UX details.** Dirty-state tracking with `beforeunload` guard, URL-synced filters and sort state, ARIA sort attributes on column headers, and the accordion host panel all reflect production-quality frontend engineering.
