# proxmon -- Claude Code Context

## What this is
Proxmox monitoring dashboard. Discovers LXC/VM guests, detects running apps, compares installed vs latest GitHub release version.

## Stack
- Backend: Python 3.12, FastAPI, httpx, sqlite3 (stdlib), uv
- Frontend: React 18, TypeScript, Vite, Tailwind CSS
- Infra: Docker Compose, GitHub Actions (ghcr.io)

## Key files
- `backend/app/core/config_store.py` -- SQLite config persistence (single settings row, JSON blob)
- `backend/app/core/discovery.py` -- main orchestration: guest discovery -> app detection -> version check
- `backend/app/detectors/http_json.py` -- config-driven detector for JSON version endpoints; add `DetectorConfig` entries here for new simple apps
- `backend/app/detectors/registry.py` -- ALL_DETECTORS list, DETECTOR_MAP; specialized detectors (Plex, qBittorrent, SABnzbd, Caddy) live in separate files
- `backend/app/core/github.py` -- GitHub releases API client with 1h TTL cache
- `backend/app/api/routes.py` -- all API endpoints; `_keep_or_replace()` guards masked secrets
- `backend/app/api/auth_routes.py` -- login/logout/session endpoints
- `backend/app/middleware/auth_middleware.py` -- session cookie auth middleware
- `backend/app/core/session_store.py` -- in-memory session management
- `backend/app/core/auth.py` -- password hashing and verification
- `backend/app/config.py` -- Settings (pydantic-settings); AppConfig (per-app port/api_key/scheme/github_repo)
- `frontend/src/components/Settings.tsx` -- settings form (delegates to section components)
- `frontend/src/components/settings/AppConfigSection.tsx` -- per-app config (port, api_key, scheme, github_repo)

## Architecture
```
Proxmox API -> list guests -> detect app (name/tag/docker) -> probe version HTTP endpoint -> compare vs GitHub latest
```

## Detector pattern
Most detectors are config-driven: add a `DetectorConfig` entry to `SIMPLE_DETECTOR_CONFIGS` in `backend/app/detectors/http_json.py`. Fields: `name`, `display_name`, `github_repo`, `default_port`, `path`, `docker_images`, `version_keys`, `accepts_api_key`, `auth_header`.

Specialized detectors (non-JSON responses, custom auth) subclass `BaseDetector` directly and implement:
- `name`, `display_name`, `github_repo`, `aliases`, `default_port`, `docker_images`
- `get_installed_version(host, port, api_key, scheme)` -- HTTP probe returning version string or None

Register all detectors in `backend/app/detectors/registry.py` via `make_detector("name")` (config-driven) or `SpecialDetector()` (custom class).

## Config storage
SQLite at `/app/data/proxmon.db`. Single `settings` table, one row, JSON blob. All config lives in SQLite (only `CONFIG_DB_PATH` env var is recognized, defaults to `/app/data/proxmon.db`).

## Tests
`cd backend && pytest tests/` -- 169 tests across test_detectors.py, test_discovery.py, test_github.py, test_config_store.py, test_ssh_version_cmd.py, test_notifier.py, test_alerting.py, test_routes_helpers.py, test_auth_routes.py

## Deploy
Single container serves both API and frontend on port 3000 (configurable via `PORT` env var).
```bash
docker compose build && docker compose up -d
```
CI auto-builds to `ghcr.io/counterf/proxmon:latest` on push to main.

**After any code changes, always rebuild and restart Docker** so the running stack reflects the changes: `docker compose build --no-cache && docker compose up -d`.

## Common pitfalls
- GitHub token and SSH password must NOT be pre-populated with `"***"` -- `_keep_or_replace()` in routes.py handles this
- All detectors default to `http://`; use per-app `scheme=https` for HTTPS-only apps
- Version probes fail silently (WARNING log) if API key is missing for *arr apps
