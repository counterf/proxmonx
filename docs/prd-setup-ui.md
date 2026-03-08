# PRD: Setup & Configuration UI

| Field        | Value                              |
|--------------|------------------------------------|
| Author       | Alysson Silva                      |
| Status       | Draft                              |
| Created      | 2026-03-08                         |
| Last updated | 2026-03-08                         |
| Version      | 0.1                                |
| Parent PRD   | `docs/prd.md` (proxmon MVP)        |

---

## 1. Context & Why Now

- proxmon currently requires operators to hand-edit a `.env` file before first startup. Users who misconfigure a token or forget a required field get a cryptic Python `ValidationError` traceback on container launch, with no browser UI at all.
- The existing Settings page (`/settings`) is read-only and tells users: *"To change settings, edit your `.env` file and restart proxmon."* This defeats the goal of a one-command Docker Compose experience.
- First-run friction is the single biggest adoption blocker: a user who runs `docker compose up` and sees a crash before ever reaching the dashboard will likely abandon the tool.
- Proxmox VE API token creation is already a multi-step process in the Proxmox UI. Asking users to then also hand-edit a dotfile adds unnecessary friction.

Source -- proxmon MVP PRD (FR-9) identifies env-only config as the sole mechanism; no UI fallback exists.
Source -- Self-hosted app conventions (Immich, Portainer, Gitea) all provide first-run setup wizards.

---

## 2. Users & JTBD

| User | Job To Be Done |
|------|---------------|
| First-time homelab operator | Configure proxmon through the browser so I never touch a `.env` file. |
| First-time homelab operator | Validate my Proxmox connection before committing config so I know I entered the right values. |
| Returning operator | Change poll interval or toggle VM discovery without restarting the container. |
| Returning operator | Rotate a Proxmox API token without downtime. |
| Operator migrating from `.env` | Keep my existing `.env`-based deployment working without changes. |

---

## 3. Business Goals & Success Metrics

### Goals
- Eliminate `.env` editing as a prerequisite for first-time use.
- Make proxmon launchable with zero pre-configuration: `docker compose up` then configure in-browser.
- Preserve full backward compatibility for existing `.env` deployments.

### Leading Metrics
| Metric | Target |
|--------|--------|
| Time from `docker compose up` to seeing the setup wizard | < 10 s |
| Time from wizard completion to first dashboard data | < 60 s (including first discovery cycle) |
| "Test Connection" round-trip latency | < 3 s |
| Settings save-to-effect latency (discovery restarts with new config) | < 5 s |

### Lagging Metrics
| Metric | Target |
|--------|--------|
| Percentage of new deployments that reach the dashboard without manual `.env` editing | > 90% |
| Settings-related support issues / bug reports | < 5% of total |

---

## 4. Functional Requirements

### FR-1: Setup Status Detection

The backend detects whether the app is configured on startup and exposes this via API.

| # | Requirement | Acceptance Criteria |
|---|------------|-------------------|
| 1.1 | Backend checks for required Proxmox fields (`proxmox_host`, `proxmox_token_id`, `proxmox_token_secret`, `proxmox_node`) on startup. | If any required field is missing/empty, `configured` is `false`. |
| 1.2 | `GET /api/setup/status` returns setup state. | Response: `{ "configured": bool, "missing_fields": ["proxmox_host", ...] }`. Returns `200` always. |
| 1.3 | When unconfigured, the backend starts without crashing. Discovery and polling do not start. | App boots, serves API, but `GET /api/guests` returns `[]` and no background tasks run. |
| 1.4 | Frontend calls `/api/setup/status` on load. If `configured: false`, redirect to `/setup`. | Dashboard is unreachable until setup completes. Direct navigation to `/setup` always works. |

### FR-2: Setup Wizard (First-Run)

A guided multi-step form shown when configuration is missing.

| # | Requirement | Acceptance Criteria |
|---|------------|-------------------|
| 2.1 | **Step 1 -- Proxmox Connection:** Fields for host URL, token ID, token secret, node name. All required. | Form validates: host is a URL (https:// or http://), token ID matches `user@realm!name` pattern, token secret is non-empty, node name is non-empty. |
| 2.2 | **Step 2 -- Discovery Settings:** Poll interval (number input, min 30s), include VMs toggle, verify SSL toggle. | Defaults pre-filled: 300s, VMs off, SSL verification off. |
| 2.3 | **Step 3 -- SSH Settings:** Enable SSH toggle, username text field, key path text field. | Defaults pre-filled: SSH on, username `root`, key path empty. When SSH is disabled, username/key fields are hidden. |
| 2.4 | **Step 4 -- GitHub Token:** Optional text field with helper text explaining rate-limit benefits. | Field can be left empty. Helper text states: "Without a token, GitHub API limits to 60 requests/hour." |
| 2.5 | **Step 5 -- Review & Save:** Summary table showing all entered values (token secret masked). "Test Connection" and "Save" buttons. | "Test Connection" calls `/api/settings/test-connection` with current form values. "Save" calls `POST /api/settings`. |
| 2.6 | Step navigation: back/next buttons, step indicator showing progress. | User can navigate backward to edit previous steps. Cannot skip ahead without completing current step. |
| 2.7 | After successful save: redirect to `/` (dashboard) and backend starts discovery immediately. | First poll cycle begins within 5 s of save. Dashboard shows loading/polling state. |
| 2.8 | Wizard is accessible at `/setup` route. | If already configured, `/setup` redirects to `/settings`. |

### FR-3: Settings Page (Ongoing Configuration)

Replace the current read-only Settings page with an editable form.

| # | Requirement | Acceptance Criteria |
|---|------------|-------------------|
| 3.1 | Same field sections as the wizard, displayed as a single-page form (not multi-step). | All fields from steps 1-4 of the wizard are present and editable. |
| 3.2 | Form loads with current persisted values from `GET /api/settings/full`. | All fields populated. Token secret shows masked (`*` characters) with a show/hide toggle. |
| 3.3 | "Test Connection" button tests Proxmox connectivity with the current form values. | Calls `POST /api/settings/test-connection`. Shows success (green) or failure (red + error message) inline. |
| 3.4 | "Save Changes" button persists all values via `POST /api/settings`. | On success: toast/banner confirms save. Discovery restarts with new values. On failure: error message displayed, form state preserved. |
| 3.5 | Token secret field: if unchanged (still masked), the save payload omits it so the backend preserves the existing value. | Backend does not require token secret in every save request. Sending `null` or omitting means "keep current." |
| 3.6 | Unsaved changes warning: if user navigates away with unsaved edits, show a confirmation prompt. | Browser `beforeunload` event and React Router navigation blocking. |

### FR-4: Test Connection Endpoint

| # | Requirement | Acceptance Criteria |
|---|------------|-------------------|
| 4.1 | `POST /api/settings/test-connection` accepts `{ proxmox_host, proxmox_token_id, proxmox_token_secret, proxmox_node, verify_ssl }`. | All five fields required in request body. |
| 4.2 | Attempts `GET /api2/json/nodes/{node}/status` against the provided Proxmox host using the provided credentials. | Timeout: 10 s. |
| 4.3 | Returns `{ "success": true, "node_status": "online", "pve_version": "8.x.x" }` on success. | Proxmox API version extracted from response. |
| 4.4 | Returns `{ "success": false, "error": "descriptive message" }` on failure. | Covers: DNS resolution failure, connection refused, TLS error, 401 unauthorized, 403 forbidden, timeout, invalid node name. |
| 4.5 | Does not persist any values. Stateless check only. | No side effects. Config file and env vars unchanged. |

### FR-5: Settings Persistence Endpoint

| # | Requirement | Acceptance Criteria |
|---|------------|-------------------|
| 5.1 | `POST /api/settings` accepts the full settings payload (see API Contract below). | Request body validated by Pydantic model. `422` on validation failure with field-level errors. |
| 5.2 | Validates all fields before writing. | Host URL format, token ID pattern, numeric ranges (poll interval >= 30), boolean types. |
| 5.3 | Persists validated settings to `/app/data/config.json`. | File written atomically (write to temp file, then rename). Directory created if absent. |
| 5.4 | After persisting, reloads the in-memory `Settings` object and restarts the discovery scheduler. | New config takes effect without container restart. |
| 5.5 | Returns `{ "status": "saved", "restart_required": false }`. | `restart_required` is always `false` in this implementation (hot reload). |

### FR-6: Full Settings Retrieval

| # | Requirement | Acceptance Criteria |
|---|------------|-------------------|
| 6.1 | `GET /api/settings/full` returns all current settings with token secret masked. | Response includes every field from the Settings model. `proxmox_token_secret` returned as `"********"`. |
| 6.2 | Existing `GET /api/settings` endpoint remains unchanged for backward compatibility. | Returns the same masked subset it returns today. |

---

## 5. API Contract

### `GET /api/setup/status`

**Response** `200`
```json
{
  "configured": false,
  "missing_fields": ["proxmox_host", "proxmox_token_id", "proxmox_token_secret", "proxmox_node"]
}
```

### `POST /api/settings/test-connection`

**Request**
```json
{
  "proxmox_host": "https://192.168.1.10:8006",
  "proxmox_token_id": "proxmon@pve!monitor",
  "proxmox_token_secret": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "proxmox_node": "pve",
  "verify_ssl": false
}
```

**Response** `200`
```json
{
  "success": true,
  "node_status": "online",
  "pve_version": "8.3.2"
}
```

**Response** `200` (failure -- not 4xx, since the endpoint itself succeeded)
```json
{
  "success": false,
  "error": "Connection refused: https://192.168.1.10:8006"
}
```

### `POST /api/settings`

**Request**
```json
{
  "proxmox_host": "https://192.168.1.10:8006",
  "proxmox_token_id": "proxmon@pve!monitor",
  "proxmox_token_secret": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "proxmox_node": "pve",
  "poll_interval_seconds": 300,
  "discover_vms": false,
  "verify_ssl": false,
  "ssh_enabled": true,
  "ssh_username": "root",
  "ssh_key_path": "/app/ssh/id_rsa",
  "ssh_password": null,
  "github_token": null,
  "log_level": "info"
}
```

Fields that are `null` or omitted retain their current value (important for `proxmox_token_secret` which the frontend sends as `null` when unchanged).

**Response** `200`
```json
{
  "status": "saved",
  "restart_required": false
}
```

**Response** `422` (validation error)
```json
{
  "detail": [
    {
      "loc": ["body", "proxmox_host"],
      "msg": "Invalid URL format",
      "type": "value_error"
    }
  ]
}
```

### `GET /api/settings/full`

**Response** `200`
```json
{
  "proxmox_host": "https://192.168.1.10:8006",
  "proxmox_token_id": "proxmon@pve!monitor",
  "proxmox_token_secret": "********",
  "proxmox_node": "pve",
  "poll_interval_seconds": 300,
  "discover_vms": false,
  "verify_ssl": false,
  "ssh_enabled": true,
  "ssh_username": "root",
  "ssh_key_path": "/app/ssh/id_rsa",
  "ssh_password": null,
  "github_token_set": true,
  "log_level": "info",
  "proxmon_enabled": true
}
```

---

## 6. Persistence Strategy

### Config File
- **Path:** `/app/data/config.json`
- **Format:** JSON object with the same keys as the `Settings` model (snake_case).
- **Atomicity:** Write to `/app/data/config.json.tmp`, then `os.replace()` to final path.
- **Permissions:** File readable/writable by the container process only (`0600`).

### Priority Order (highest to lowest)
1. Config file (`/app/data/config.json`) -- values set via UI
2. Environment variables (`.env` file or Docker env) -- values set by operator
3. Defaults (hardcoded in `Settings` model)

### Implementation
- On startup, `Settings.__init__` checks for config file existence. If present, loads and merges with env vars (config file wins for any key present in both).
- Pydantic `model_validator` or custom `settings_customise_sources` to insert config file as highest-priority source.
- Required fields (`proxmox_host`, etc.) no longer raise on missing -- instead, `Settings` initializes with empty strings, and the setup status endpoint reports them as missing.

### Docker Volume
- `docker-compose.yml` updated to mount `./data:/app/data`.
- The `data/` directory added to `.gitignore`.

### Secret Storage Note
- Token secret and SSH password are stored in plaintext in `config.json`. This is acceptable for a self-hosted homelab tool where the config volume is local to the host.
- The PRD does not introduce encryption at rest. If needed in the future, a `PROXMON_CONFIG_KEY` env var could enable AES encryption of the config file.

---

## 7. Migration & Backward Compatibility

| Scenario | Behavior |
|----------|----------|
| Existing `.env` deployment, no config file | App starts normally using env vars. Settings page shows current values. User can optionally save to config file via the Settings page. |
| New deployment, no `.env`, no config file | App starts in unconfigured mode. Frontend redirects to `/setup` wizard. |
| Config file exists AND `.env` has values | Config file values take precedence. Env vars used only for keys absent from config file. |
| User saves via UI while `.env` exists | Config file created/updated. `.env` is not modified. Config file values override `.env` for overlapping keys. |
| User deletes config file | App falls back to `.env` values on next restart. |

### Breaking Changes
- None. All existing API endpoints retain their current behavior.
- The `Settings` class changes from raising on missing required fields to accepting empty/missing values. This is backward-compatible because env-var deployments still provide required fields.

---

## 8. Non-Functional Requirements

### Performance
- Setup wizard initial render: < 500 ms (no backend data needed for form rendering).
- `POST /api/settings` write + reload: < 1 s.
- `POST /api/settings/test-connection`: < 10 s (bounded by Proxmox connection timeout).

### Scale
- Single config file, single concurrent writer. No locking needed (single-process backend).

### Security
- `POST /api/settings` and `POST /api/settings/test-connection` are unauthenticated (consistent with the no-auth homelab stance in the MVP PRD).
- Token secret is never logged. `structlog` processors must scrub `proxmox_token_secret` and `ssh_password` from log output.
- Config file permissions set to `0600` on write.

### Privacy
- No new external calls introduced. Settings data stays on the local host.

### Observability
- `INFO` log on settings save: `"Settings saved via UI"` (no secret values).
- `WARNING` log on test-connection failure with error detail.
- `GET /health` unchanged; continues to reflect current operational state.

### SLOs
- Setup wizard availability matches backend availability (container up = wizard available).

---

## 9. Scope

### In Scope
- Setup wizard (multi-step, first-run)
- Editable Settings page (replace read-only)
- Three new API endpoints (`/api/setup/status`, `POST /api/settings`, `POST /api/settings/test-connection`)
- One new API endpoint (`GET /api/settings/full`)
- Config file persistence (`/app/data/config.json`)
- Backend graceful startup when unconfigured
- Docker Compose volume mount for `./data`
- Hot reload of settings (no container restart)

### Out of Scope
- Authentication / authorization for settings endpoints
- Encryption at rest for config file
- Multi-user concurrent config editing
- Import/export of settings
- Proxmox cluster auto-discovery (user must know their node name)
- SSH key upload via UI (user provides path to a volume-mounted key)
- Per-detector enable/disable toggles in UI (future enhancement)
- Undo / version history for settings changes
- Mobile-optimized wizard layout

---

## 10. Rollout Plan

### Phase A: Backend (Week 1)
- Refactor `Settings` to support optional required fields and config file source.
- Implement `/api/setup/status`, `POST /api/settings`, `POST /api/settings/test-connection`, `GET /api/settings/full`.
- Config file read/write with atomic save.
- Hot-reload: settings change triggers scheduler restart.
- Unit tests for config merging (file > env > defaults), validation, and test-connection.
- Update `docker-compose.yml` with `./data:/app/data` volume.

### Phase B: Frontend (Week 2)
- Setup wizard component (`/setup` route) with 5 steps.
- Refactor `Settings.tsx` from read-only to editable form.
- Frontend routing guard: redirect to `/setup` when unconfigured.
- "Test Connection" button with inline success/failure feedback.
- "Save Changes" with loading state and success toast.
- Token secret masking with show/hide toggle.

### Phase C: Integration & Polish (Week 3)
- End-to-end test: fresh container, wizard flow, first discovery.
- Backward-compat test: existing `.env` deployment continues working.
- Update `.env.example` to mark required fields as optional when using UI.
- Update `README.md` with setup wizard screenshots and new quick-start instructions.

### Guardrails
- **Config file corruption:** If `config.json` is invalid JSON on load, log an error and fall back to env vars entirely. Do not crash.
- **Partial save prevention:** Validate entire payload before writing. Never write a partial config file.
- **Concurrent writes:** Single-process backend; no concurrent write risk in MVP. If future multi-process, add file locking.

### Kill Switch
- If the setup UI causes issues, users can bypass it entirely by providing a complete `.env` file. The backend starts normally and the wizard is never shown.
- `PROXMON_SKIP_SETUP_UI=true` env var suppresses the unconfigured state and forces the backend to behave as it does today (crash on missing required fields).

---

## 11. Risks & Open Questions

### Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Config file left world-readable with secrets | Medium | Medium | Set `0600` permissions on write. Document in README. |
| User saves invalid Proxmox URL, discovery fails silently | Medium | High | "Test Connection" in wizard + validation. Backend logs connection errors clearly. |
| Config file and env vars conflict confuses operator | Medium | Low | Document priority order. Settings page shows effective values with source annotation (future). |
| Hot reload breaks mid-discovery-cycle | Low | Medium | Finish current cycle before applying new settings. Queue reload, don't interrupt. |
| Docker volume not mounted, config lost on container recreate | Medium | High | Warn in docs. Backend logs a warning if `/app/data` is not a mount point. |

### Open Questions

1. **Should `POST /api/settings` require re-entering the token secret every time, or accept `null` to mean "keep current"?**
   Recommendation: Accept `null` to keep current. Reflected in this PRD.

2. **Should the wizard allow skipping optional steps (SSH, GitHub)?**
   Recommendation: Yes, steps 2-4 should have a "Skip" button that applies defaults.

3. **Should we support SSH password entry in the wizard, or key-path only?**
   Recommendation: Support both (the `Settings` model already has `ssh_password`), but recommend key-based in the UI helper text.

4. **Should the config file path be configurable via env var?**
   Recommendation: Yes, via `PROXMON_CONFIG_PATH` (default `/app/data/config.json`). Low effort, high flexibility.

5. **Should the backend expose which source each setting value came from (config file vs env var vs default)?**
   Recommendation: Defer to a future enhancement. Not needed for MVP of this feature.
