# PRD: Per-App API Key and Port Override

| Field        | Value                                     |
|--------------|-------------------------------------------|
| Author       | Alysson Silva                             |
| Status       | Draft                                     |
| Created      | 2026-03-08                                |
| Last updated | 2026-03-08                                |
| Version      | 0.1                                       |
| Parent PRD   | `docs/prd.md` (proxmon MVP)               |
| Depends on   | `docs/prd-setup-ui.md` (Settings UI)      |

---

## 1. Context & Why Now

- proxmon discovers apps on Proxmox guests and checks installed versions against GitHub releases. Today, version detection silently fails for a significant subset of supported apps because the detectors cannot authenticate or reach apps on non-default ports.
- **Sonarr, Radarr, Prowlarr** require an API key header (`X-Api-Key`) on every request -- without it, their `/api/v3/system/status` endpoint returns `401`. Currently the detectors make unauthenticated requests, so installed version is always `null` for these apps.
- **Bazarr** similarly requires an API key via the `X-API-KEY` header on its `/api/bazarr/api/v1/system/status` endpoint.
- **SABnzbd** requires an `apikey` query parameter on its `/api?mode=version` endpoint, and many users run it on a non-default port (e.g., 7777 instead of 8085).
- Other apps (Plex, qBittorrent, Overseerr) may also run on custom ports depending on user configuration.
- The Settings UI (`docs/prd-setup-ui.md`) already provides the infrastructure: `ConfigStore` for persistence, `POST /api/settings` for save-and-reload, and a React form with dirty-state tracking. This feature extends that foundation with per-app overrides.
- Without this feature, the dashboard shows "unknown" version status for the most popular *arr stack apps, undermining the core value proposition.

Source -- Sonarr API docs: all v3 endpoints require `X-Api-Key` header or `apikey` query param.
Source -- SABnzbd API docs: `apikey` query parameter is mandatory for all API calls.
Source -- Bazarr API docs: `X-API-KEY` header required for v1 endpoints.

---

## 2. Users & JTBD

| User | Job To Be Done |
|------|---------------|
| Homelab operator running *arr stack | Enter my Sonarr/Radarr/Prowlarr API keys so proxmon shows installed versions and update status. |
| Operator with non-default ports | Override the default port for SABnzbd (or any app) so version detection reaches the correct endpoint. |
| Operator adding a new app | Configure API key and port before the next discovery cycle without restarting the container. |
| Operator rotating API keys | Update a single app's API key via the Settings UI without affecting other apps. |

---

## 3. Business Goals & Success Metrics

### Goals
- Unlock installed version detection for all 13 supported apps.
- Maintain zero-config defaults: apps that do not require API keys or use default ports continue to work without any per-app configuration.
- Fit naturally into the existing Settings UI -- no new pages or navigation.

### Leading Metrics

| Metric | Target |
|--------|--------|
| Installed version detection success rate for *arr apps (with API key configured) | > 95% |
| Time to configure one app (port + API key) in the Settings UI | < 15 s |
| Settings save-to-effect latency (detector uses new config on next poll) | < 5 s |

### Lagging Metrics

| Metric | Target |
|--------|--------|
| Percentage of detected apps with a non-null `installed_version` (across all deployments) | > 80% (up from ~50%) |
| Support issues related to "version unknown" for *arr apps | Reduced by > 70% |

---

## 4. Functional Requirements

### FR-1: Per-App Configuration Data Model

| # | Requirement | Acceptance Criteria |
|---|------------|---------------------|
| 1.1 | Add an `app_config` field to the `Settings` model: `dict[str, AppConfig]` where key is detector name (e.g., `"sonarr"`). | `AppConfig` is a Pydantic model with two optional fields: `api_key: str | None = None`, `port: int | None = None`. |
| 1.2 | `app_config` defaults to an empty dict. Detectors with no entry use existing behavior (no API key, default port). | Omitting `app_config` from config.json is equivalent to `{}`. |
| 1.3 | Only known detector names are accepted as keys. | Validation rejects keys not in `DETECTOR_MAP`. Returns `422` with the invalid key name. |
| 1.4 | Port values must be in range 1--65535. | Validation rejects out-of-range ports with a descriptive error. |

### FR-2: Config Persistence

| # | Requirement | Acceptance Criteria |
|---|------------|---------------------|
| 2.1 | `app_config` is persisted inside `/app/data/config.json` under the `"app_config"` key. | Atomic write via existing `ConfigStore.save()`. |
| 2.2 | API keys are stored in plaintext (consistent with existing token secret storage). | `config.json` permissions remain `0600`. |
| 2.3 | `ConfigStore.merge_into_settings()` merges `app_config` from file into the `Settings` object. | File values override defaults; missing keys are ignored. |
| 2.4 | Existing config files without `app_config` load without error. | Backward compatible -- treated as empty `app_config`. |

### FR-3: Detector Integration

| # | Requirement | Acceptance Criteria |
|---|------------|---------------------|
| 3.1 | `BaseDetector.get_installed_version()` signature adds an optional `api_key: str | None = None` parameter. | Existing subclass implementations that ignore it continue to work. |
| 3.2 | Sonarr, Radarr, and Prowlarr detectors pass the API key as `X-Api-Key` header when provided. | Returns version on `200`; logs warning and returns `None` on `401` (missing/bad key). |
| 3.3 | Bazarr detector passes the API key as `X-API-KEY` header when provided. | Same behavior as 3.2. |
| 3.4 | SABnzbd detector appends `&apikey={key}` to the query string when an API key is provided. | Returns version on `200`; returns `None` on auth failure. |
| 3.5 | `BaseDetector._http_get()` accepts an optional `headers: dict` parameter for per-request headers. | Merges with any existing default headers. |
| 3.6 | `DiscoveryEngine._check_version()` reads `app_config` from `Settings` and passes `port` and `api_key` to `detector.get_installed_version()`. | If no override exists, passes `None` (detector uses its default). |

### FR-4: API Endpoints

| # | Requirement | Acceptance Criteria |
|---|------------|---------------------|
| 4.1 | `GET /api/settings/full` includes `app_config` in the response. API keys are masked (e.g., `"sonarr": {"api_key": "***", "port": 8989}`). | Keys with no overrides are omitted or shown with `null` values. |
| 4.2 | `POST /api/settings` accepts an optional `app_config` field in the request body. | Validated per FR-1.3 and FR-1.4. Omitting `app_config` preserves existing values. |
| 4.3 | `GET /api/app-config/defaults` returns the list of supported apps with their default ports. | Response: `[{"name": "sonarr", "display_name": "Sonarr", "default_port": 8989, "accepts_api_key": true}, ...]`. |
| 4.4 | Sending `app_config: {}` (empty object) clears all per-app overrides. | After save, detectors revert to default behavior. |
| 4.5 | Sending a partial `app_config` (only some apps) merges with existing config. | Unmentioned apps retain their previously saved overrides. Only apps explicitly included are updated. |

### FR-5: Settings UI -- App Configuration Section

| # | Requirement | Acceptance Criteria |
|---|------------|---------------------|
| 5.1 | Add an "App Configuration" card to the Settings page, positioned after the "GitHub Token" card and before the existing "Plugins (Detectors)" card. | Card uses the same visual style (dark surface, gray-800 border). |
| 5.2 | The card displays a row per supported app. Each row shows: app display name, port input (number, placeholder = default port), API key input (password field with show/hide toggle). | Port field shows the default port as placeholder when no override is set. |
| 5.3 | Only apps that accept API keys show the API key field. Apps that do not (e.g., Plex `/identity` is unauthenticated) show the port field only. | The `accepts_api_key` flag from `GET /api/app-config/defaults` controls visibility. |
| 5.4 | Empty fields mean "use default." Clearing a port or API key field removes the override. | Saving with an empty port field does not persist `port: null` -- it omits the key entirely. |
| 5.5 | Changes to app config fields are tracked by the existing dirty-state mechanism. | The "Unsaved changes" indicator and `beforeunload` warning include app config changes. |
| 5.6 | App config is included in the `POST /api/settings` payload on save. | Existing save flow handles it; no separate save action. |
| 5.7 | API key fields display masked values (`***`) when loaded from saved config. Typing a new value replaces the mask. Leaving the mask untouched sends `null` (keep current). | Same pattern as `proxmox_token_secret`. |

---

## 5. API Contract

### `GET /api/app-config/defaults`

**Response** `200`
```json
[
  { "name": "sonarr", "display_name": "Sonarr", "default_port": 8989, "accepts_api_key": true },
  { "name": "radarr", "display_name": "Radarr", "default_port": 7878, "accepts_api_key": true },
  { "name": "prowlarr", "display_name": "Prowlarr", "default_port": 9696, "accepts_api_key": true },
  { "name": "bazarr", "display_name": "Bazarr", "default_port": 6767, "accepts_api_key": true },
  { "name": "sabnzbd", "display_name": "SABnzbd", "default_port": 8085, "accepts_api_key": true },
  { "name": "qbittorrent", "display_name": "qBittorrent", "default_port": 8080, "accepts_api_key": false },
  { "name": "plex", "display_name": "Plex", "default_port": 32400, "accepts_api_key": false },
  { "name": "immich", "display_name": "Immich", "default_port": 2283, "accepts_api_key": false },
  { "name": "gitea", "display_name": "Gitea", "default_port": 3000, "accepts_api_key": false },
  { "name": "overseerr", "display_name": "Overseerr", "default_port": 5055, "accepts_api_key": false },
  { "name": "traefik", "display_name": "Traefik", "default_port": 8080, "accepts_api_key": false },
  { "name": "caddy", "display_name": "Caddy", "default_port": 2019, "accepts_api_key": false },
  { "name": "ntfy", "display_name": "ntfy", "default_port": 80, "accepts_api_key": false }
]
```

### `POST /api/settings` (extended payload)

**Request** (only new field shown; existing fields unchanged)
```json
{
  "...existing fields...",
  "app_config": {
    "sonarr": { "api_key": "abc123def456", "port": null },
    "sabnzbd": { "api_key": "xyz789", "port": 7777 },
    "plex": { "port": 32401 }
  }
}
```

Semantics:
- `api_key: null` or omitted = keep current saved value.
- `api_key: ""` (empty string) = clear the saved API key.
- `port: null` or omitted = use detector default.
- `port: <number>` = override the default port.

### `GET /api/settings/full` (extended response)

**Response** (only new field shown)
```json
{
  "...existing fields...",
  "app_config": {
    "sonarr": { "api_key": "***", "port": null },
    "sabnzbd": { "api_key": "***", "port": 7777 }
  }
}
```

### Config File Example

`/app/data/config.json` (relevant section):
```json
{
  "proxmox_host": "https://192.168.1.10:8006",
  "...other settings...",
  "app_config": {
    "sonarr": { "api_key": "abc123def456", "port": null },
    "sabnzbd": { "api_key": "xyz789", "port": 7777 }
  }
}
```

---

## 6. Non-Functional Requirements

### Performance
- Reading `app_config` from the in-memory `Settings` object during version checks: negligible overhead (dict lookup).
- No additional HTTP calls introduced. API key is added to the existing version-check request.
- `GET /api/app-config/defaults`: < 10 ms (static data from detector registry).

### Scale
- Maximum 13 app entries in `app_config`. Fixed upper bound, no scaling concern.

### SLOs / SLAs
- Version detection latency per app (with API key): unchanged from current timeout (5 s per detector).
- Settings save with `app_config`: same < 1 s target as existing settings save.

### Privacy
- API keys are user-provided credentials for local services on the user's own network. No external transmission.
- API keys are never sent to GitHub or any external service.

### Security
- API keys stored in plaintext in `config.json` (same as `proxmox_token_secret`). File permissions `0600`.
- API keys are masked in all API responses (`GET /api/settings/full`).
- API keys are never logged. Existing log scrubbing applies.
- API keys are transmitted from frontend to backend over the local network (same trust model as Proxmox token secret).

### Observability
- `INFO` log on settings save: `"App config updated for: sonarr, sabnzbd"` (names only, no keys).
- `WARNING` log when a detector receives `401` despite having an API key configured: `"Auth failed for sonarr on 10.0.0.5:8989 -- check API key"`.
- `DEBUG` log for each version check showing whether an API key and/or port override was used.

---

## 7. Scope

### In Scope
- `AppConfig` Pydantic model and `app_config` field on `Settings`
- Persistence in `config.json` via existing `ConfigStore`
- `BaseDetector` signature change: add `api_key` parameter
- Updated detectors: Sonarr, Radarr, Prowlarr, Bazarr, SABnzbd (API key support)
- All detectors: honor `port` override from `app_config`
- `DiscoveryEngine._check_version()` reads overrides and passes them to detectors
- `GET /api/app-config/defaults` endpoint
- Extended `POST /api/settings` and `GET /api/settings/full`
- Settings UI: "App Configuration" card with per-app port and API key fields
- Frontend type updates and API client changes

### Out of Scope
- Per-app base URL override (e.g., reverse proxy path prefix) -- future enhancement
- Per-app SSL/TLS toggle -- future enhancement
- API key auto-discovery (e.g., reading from app config files on the guest via SSH)
- "Test App Connection" button per app (validates API key works) -- future enhancement
- Per-app enable/disable toggle (already noted as future in `prd-setup-ui.md`)
- Plex token authentication (Plex `/identity` works without auth)
- Bulk import/export of app config

---

## 8. Rollout Plan

### Phase A: Backend -- Data Model & Detectors (2-3 days)
- Add `AppConfig` model and `app_config` field to `Settings`.
- Update `ConfigStore.merge_into_settings()` to handle nested `app_config` dict.
- Add `api_key` parameter to `BaseDetector.get_installed_version()`.
- Add `headers` parameter to `BaseDetector._http_get()`.
- Update Sonarr, Radarr, Prowlarr, Bazarr, SABnzbd detectors to use API key.
- Update `DiscoveryEngine._check_version()` to pass overrides.
- Unit tests for each updated detector with and without API key.
- Unit tests for config merge with `app_config`.

### Phase B: Backend -- API Endpoints (1 day)
- Add `GET /api/app-config/defaults`.
- Extend `SettingsSaveRequest` with optional `app_config` field.
- Extend `GET /api/settings/full` response.
- Update `POST /api/settings` handler to merge `app_config`.
- API tests for save/load round-trip, partial updates, validation.

### Phase C: Frontend -- Settings UI (2 days)
- Add `AppConfigDefaults` and `AppConfigEntry` types.
- Add `fetchAppConfigDefaults()` to API client.
- Build "App Configuration" card in `Settings.tsx`.
- Wire into existing form state, dirty tracking, and save flow.
- Mask API key fields on load; track changes per the `proxmox_token_secret` pattern.

### Phase D: Integration Testing (1 day)
- End-to-end: set API key for Sonarr in UI, save, trigger refresh, verify installed version appears.
- Backward compatibility: existing `config.json` without `app_config` loads cleanly.
- Empty `app_config` clears overrides; detectors revert to defaults.

### Guardrails
- **Invalid API key:** Detector logs a warning and returns `None` for installed version. Dashboard shows "unknown" -- same as today without the key. No crash.
- **Invalid port:** Pydantic validation rejects on save (1--65535 range). Detector timeout (5 s) handles unreachable ports gracefully.
- **Config file migration:** Missing `app_config` key in existing files is treated as `{}`. No migration script needed.

### Kill Switch
- If per-app config causes issues, the feature is inert by default: removing `app_config` from `config.json` (or never setting it) reverts all detectors to their current unauthenticated, default-port behavior.
- No env var kill switch needed -- the feature is entirely opt-in per app.

---

## 9. Risks & Open Questions

### Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| User enters wrong API key; version shows "unknown" with no clear error in dashboard | High | Medium | Log a warning with the app name. Future: add a "Test App Connection" button per app. |
| API key rotation in the app but not in proxmon; version checks start failing | Medium | Low | Logs surface `401` errors. User re-enters key in Settings. |
| `BaseDetector` signature change breaks third-party detector plugins | Low | Low | proxmon has no third-party plugin ecosystem today. Change is backward-compatible (`api_key` defaults to `None`). |
| `ConfigStore.save()` type signature currently accepts `dict[str, str | int | bool | None]`; needs to accept nested `app_config` dict | Low | Medium | Widen type to `dict[str, Any]` or use a typed `ConfigData` model. `json.dumps` already handles nested dicts. |

### Open Questions

1. **Should `app_config` support per-guest overrides (same app on different ports per guest)?**
   Recommendation: No. Per-app (not per-guest) is sufficient for MVP. All instances of the same app typically use the same port and API key. Defer per-guest overrides to a future enhancement if requested.

2. **Should the "App Configuration" card only show apps that have been detected, or all supported apps?**
   Recommendation: Show all supported apps. Users may want to pre-configure API keys before the first discovery cycle, and it avoids a chicken-and-egg problem (can't detect version without key, can't know to configure key without detection).

3. **Should Plex token authentication be supported?**
   Recommendation: Defer. Plex `/identity` returns version without authentication. If users request Plex library access in the future, add `X-Plex-Token` support then.

4. **Should the `accepts_api_key` flag be a detector-level class attribute or derived from a registry?**
   Recommendation: Add `accepts_api_key: bool = False` as a class attribute on `BaseDetector`. Override to `True` in Sonarr, Radarr, Prowlarr, Bazarr, SABnzbd. Keeps it co-located with each detector's logic.
