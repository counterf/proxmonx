# proxmon -- Claude Code Context

## What this is
Proxmox monitoring dashboard. Discovers LXC/VM guests across multiple Proxmox hosts, detects the app running inside each guest, compares installed vs latest GitHub release version, and supports remote actions (OS update, app update, snapshot, backup, start/stop/restart).

## Stack
- Backend: Python 3.12, FastAPI, httpx, sqlite3 (stdlib), uv
- Frontend: React 18, TypeScript, Vite, Tailwind CSS
- Infra: Docker Compose, GitHub Actions (ghcr.io)

---

## Key files

### Core
- `backend/app/config.py` -- Settings (pydantic-settings); AppConfig (per-app/guest overrides); CustomAppDef; ProxmoxHostConfig
- `backend/app/core/config_store.py` -- SQLite config persistence (single settings row, JSON blob for complex fields)
- `backend/app/core/discovery.py` -- main orchestration: guest discovery → app detection → version check → community-script check; handles `forced_detector` and `version_host` overrides
- `backend/app/core/scheduler.py` -- asyncio background polling; `trigger_guest_refresh(guest_id)` (fire-and-forget); `refresh_single_guest_awaitable(guest_id)` (awaitable, returns bool, used by post-update retry loop); `trigger_refresh()` (full cycle)
- `backend/app/core/proxmox.py` -- ProxmoxClient: `list_guests()`, `guest_action()`, `get_task_status()`, `create_backup()`, `list_backup_storages()`, `get_guest_network()`
- `backend/app/core/ssh.py` -- SSHClient; `OS_UPDATE_COMMANDS` dict maps Proxmox ostype → package manager command; `run_os_update()`, `run_app_update()`, `run_pending_updates_list()`, `run_reboot_required_check()`, `run_community_script_check()`; `_strip_ansi()` strips ANSI escape codes from command output; `_extract_ssh_host()` strips scheme/port from Proxmox host URL before SSH
- `backend/app/core/github.py` -- GitHub releases API client with 1h TTL cache; `parse_github_repo()` normalizes URLs; `test_repo()` for UI validation
- `backend/app/core/task_store.py` -- TaskRecord (id, guest_id, guest_name, host_id, action, status, started_at, finished_at, output, detail, batch_id); retains last 500 records; auto-reconciles stale running tasks on restart
- `backend/app/core/session_store.py` -- in-memory session management (24h TTL)
- `backend/app/core/auth.py` -- password hashing (scrypt) and verification; login rate limiting (10 attempts / 60s / IP)
- `backend/app/core/notifier.py` -- NtfyNotifier (HTTP POST); AlertManager evaluates disk threshold + outdated-app alerts after each discovery cycle

### API routes
- `backend/app/api/routes/guests.py` -- guest endpoints; snapshot name resolved here before calling `guest_action()` (auto-generates `proxmon-YYYYMMDD-HHMMSS` if not provided); `_poll_upid()` background task polls Proxmox UPID for completion; `POST /api/guests/{id}/os-update` and `/app-update` fire background tasks via `run_os_update_bg` / `run_app_update_bg`
- `backend/app/api/routes/settings.py` -- settings endpoints; `_keep_or_replace()` prevents `"***"` mask from overwriting real secrets
- `backend/app/api/routes/bulk_jobs.py` -- bulk os_update / app_update across multiple guests; sequential per-guest execution
- `backend/app/api/routes/tasks.py` -- task history endpoints (list, get, clear)
- `backend/app/api/auth_routes.py` -- login/logout/status/change-password endpoints
- `backend/app/api/helpers.py` -- `run_os_update_bg()`, `run_app_update_bg()`; `_last_lines(text, n=3)` extracts last N non-empty lines for task detail; `_APP_UPDATE_PROBE_INTERVAL=5`, `_APP_UPDATE_RETRY_BUDGET=60` control post-update version probe retry
- `backend/app/middleware/auth_middleware.py` -- session cookie + API key auth; exempts /health, /api/auth/*, /api/setup/status; loopback-only setup endpoints

### Detectors
- `backend/app/detectors/http_json.py` -- config-driven `DetectorConfig` entries for 13 apps (Sonarr, Radarr, Bazarr, Prowlarr, Lidarr, Readarr, Whisparr, Immich, Overseerr, Seerr, Gitea, Traefik, ntfy); add new simple apps here
- `backend/app/detectors/registry.py` -- `ALL_DETECTORS` list, `DETECTOR_MAP`; `load_custom_detectors()` for runtime injection of user-defined apps; called at startup and after every custom-app CRUD save
- `backend/app/detectors/truenas.py` -- TrueNAS; JSON-RPC 2.0 over WebSocket (`wss://{host}/api/current`); auth via `auth.login_with_api_key`; installed from `system.info`, latest from `update.status`; **latest is cached in `_cached_latest` during `get_installed_version()`** — no separate `get_latest_version()` call
- Specialized: `plex.py`, `caddy.py`, `qbittorrent.py`, `sabnzbd.py`, `jackett.py`, `librespeed_rust.py`, `docker_generic.py`

### Frontend
- `frontend/src/components/GuestActions.tsx` -- guest action dropdown; handles start/stop/shutdown/restart/snapshot/refresh/os_update/app_update/backup; snapshot has optional name input; os_update and app_update have confirm dialogs with in-progress state
- `frontend/src/components/Tasks.tsx` -- task history; `InfoCell` shows "View output" toggle (unified for success + failed); exception-only failures show plain red detail; running tasks show UPID
- `frontend/src/components/Settings.tsx` -- delegates to section components
- `frontend/src/components/settings/AppConfigSection.tsx` -- per-app config (port, api_key, scheme, github_repo, ssh_version_cmd, ssh_username, ssh_key_path, ssh_password)
- `frontend/src/components/settings/CustomAppsSection.tsx` -- CRUD UI for user-defined custom app definitions

---

## Architecture

```
Proxmox API
  → list LXC/VM guests (namespaced {host_id}:{vmid} for multi-host)
  → detect app (name/tag/docker image/forced_detector)
  → probe installed version (HTTP JSON or SSH pct exec, order per version_detect_method)
  → fetch latest version (GitHub releases API, 1h TTL)
  → compute update_status (up-to-date / outdated / unknown)
  → alert if disk > threshold or app newly outdated (ntfy)
```

After successful `app_update`: probes version every 5s for up to 60s (container needs startup time).

---

## Detector pattern

**Config-driven (most apps):** Add a `DetectorConfig` entry to `SIMPLE_DETECTOR_CONFIGS` in `backend/app/detectors/http_json.py`. Fields: `name`, `display_name`, `github_repo`, `default_port`, `path`, `docker_images`, `version_keys`, `accepts_api_key`, `auth_header`, `strip_v`, `aliases`.

**Specialized (non-JSON or custom auth):** Subclass `BaseDetector` and implement:
- Attributes: `name`, `display_name`, `github_repo`, `aliases`, `default_port`, `docker_images`
- `get_installed_version(host, port, api_key, scheme) -> str | None`

Register in `backend/app/detectors/registry.py` via `make_detector("name")` (config-driven) or direct instantiation (specialized).

---

## Config storage
SQLite at `/app/data/proxmon.db`. Single `settings` table, one row. Scalar fields are stored as columns; complex fields (`proxmox_hosts`, `app_config`, `guest_config`, `custom_app_defs`) as JSON blobs. Only two env vars are recognized at runtime: `CONFIG_DB_PATH` (default `/app/data/proxmon.db`) and `PORT` (default `3000`).

---

## OS update support (by Proxmox ostype)
`alpine`, `debian`, `ubuntu`, `devuan`, `fedora`, `centos`, `archlinux`, `opensuse`.
Note: `rocky` and `alma` containers are configured as `centos` in Proxmox — they are not separate ostypes.

---

## Tests
`cd backend && pytest tests/` -- tests across test_detectors.py, test_discovery.py, test_github.py, test_config_store.py, test_ssh_version_cmd.py, test_notifier.py, test_alerting.py, test_routes_helpers.py, test_auth_routes.py, test_custom_app_defs.py

---

## Deploy
Single container serves both API and frontend on port 3000.
```bash
docker compose build && docker compose up -d
```
CI auto-builds to `ghcr.io/counterf/proxmon:latest` on push to main.

**After any code changes, always rebuild and restart Docker:**
```bash
docker compose build && docker compose up -d
```

---

## Common pitfalls

**Secrets & masking**
- GitHub token, SSH password, and api_key must NOT be pre-populated with `"***"` when saving settings — `_keep_or_replace()` in settings route handles this; verify any new secret fields follow the same pattern.

**Detectors**
- All detectors default to `http://`; use per-app `scheme=https` for HTTPS-only apps.
- `HttpJsonDetector.get_installed_version` raises `ProbeError` on HTTP/connection failures; `_check_version` in discovery.py catches it and stores the message in `guest.probe_error`; surfaced in guest detail UI.
- Custom app detectors are injected into `ALL_DETECTORS`/`DETECTOR_MAP` at runtime via `load_custom_detectors()`; called at startup (main.py lifespan) and after every CRUD save.
- User-defined app names must not collide with built-in detector names; collisions are logged and skipped.
- TrueNAS `get_latest_version()` has no host/api_key params — latest version is cached in `self._cached_latest` during `get_installed_version()` and returned from there; don't refactor to decouple them.

**Per-guest config**
- `forced_detector` and `version_host` live on `AppConfig` (shared model) but are semantically guest-only; only the guest config save path uses them.
- `version_host` overrides both the version probe IP **and** the clickable web URL link for a guest.

**SSH**
- `_extract_ssh_host()` is required before any SSH call — `ProxmoxHostConfig.host` may contain a full URL (`https://192.168.1.10:8006`), not a bare hostname.
- SSH command whitelist allows: `docker ps`, `docker inspect`, `cat`, `which`, `dpkg -l`, `rpm -q`.
- User-configured `ssh_version_cmd` is validated with `_is_version_cmd_safe()` — no `;`, `&&`, `||`, `$()`, backticks; pipes only to safe filters (`awk grep cut head tail sed tr xargs`).
- `_strip_ansi()` is applied to `run_app_update()` output — community scripts emit terminal control sequences that render as garbage without stripping.

**Multi-host**
- Guest IDs are namespaced as `{host_id}:{vmid}` to prevent collisions across hosts.
- `ProxmoxHostConfig.host` is a full URL; always pass through `_extract_ssh_host()` before SSH.

**Disk usage**
- LXC disk comes from Proxmox list endpoint directly.
- VM disk is fetched via `agent/get-fsinfo` (QEMU guest agent); VMs without the agent show blank disk.

**Guest actions**
- `guest_action()` returns a Proxmox UPID (async task ID); `_poll_upid()` polls every 10s up to 10 min for completion.
- Snapshot name is resolved in `guests.py` before calling `guest_action()` — auto-generates `proxmon-YYYYMMDD-HHMMSS` if blank; this ensures the resolved name is always available for the task `detail` field.

**Post-update refresh**
- After `run_app_update_bg` succeeds, the version probe retries every 5s for up to 60s (`_APP_UPDATE_PROBE_INTERVAL`, `_APP_UPDATE_RETRY_BUDGET`). `refresh_single_guest_awaitable()` bypasses `_in_flight_refreshes` intentionally — the retry loop is sequential.
- `run_os_update_bg` keeps the old fire-and-forget `trigger_guest_refresh()` — OS package updates don't restart the app.

**Task history**
- `detail` field = short human summary; `output` field = full raw stdout/stderr.
- For `app_update`, `detail` is set to the last 3 non-empty output lines via `_last_lines()` for both success and failure.
- Tasks marked `running` for `os_update` or `app_update` are reconciled to `failed` on app restart (stale guard).

**Settings payload**
- `Settings.tsx` AppConfig payload builder must include ALL per-app fields when posting — easy to miss new fields when adding them.
- `proxmox_hosts` list is merged (not replaced) on save to preserve per-host fields not sent by the UI.

**Shell metacharacters**
- `SHELL_METACHARACTERS` regex blocks: `; & | \` $ < > ( ) ! \n \\ #`
- Docker `{{.Image}}` Go template syntax uses `{}` braces — do NOT add `{` or `}` to the metacharacter set.
