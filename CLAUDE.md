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
- `backend/app/detectors/` -- one file per app detector (sonarr, radarr, plex, etc.)
- `backend/app/detectors/registry.py` -- ALL_DETECTORS list, DETECTOR_MAP
- `backend/app/core/github.py` -- GitHub releases API client with 1h TTL cache
- `backend/app/api/routes.py` -- all API endpoints; `_keep_or_replace()` guards masked secrets
- `backend/app/config.py` -- Settings (pydantic-settings); AppConfig (per-app port/api_key/scheme/github_repo)
- `frontend/src/components/Settings.tsx` -- settings form
- `frontend/src/components/settings/AppConfigSection.tsx` -- per-app config (port, api_key, scheme, github_repo)

## Architecture
```
Proxmox API -> list guests -> detect app (name/tag/docker) -> probe version HTTP endpoint -> compare vs GitHub latest
```

## Detector pattern
Each detector in `backend/app/detectors/` extends `BaseDetector` and implements:
- `name`, `display_name`, `github_repo`, `aliases`, `default_port`, `docker_images`
- `get_installed_version(host, port, api_key, scheme)` -- HTTP probe returning version string or None

## Config storage
SQLite at `/app/data/proxmon.db`. Single `settings` table, one row, JSON blob. Auto-migrates `config.json` on first start.

## Tests
`cd backend && pytest tests/` -- 70 tests across test_detectors.py, test_discovery.py, test_github.py, test_config_store.py

## Deploy
```bash
docker compose build && docker compose up -d
```
CI auto-builds to `ghcr.io/counterf/proxmonx-{backend,frontend}:latest` on push to main.

## Common pitfalls
- GitHub token and SSH password must NOT be pre-populated with `"***"` -- `_keep_or_replace()` in routes.py handles this
- All detectors default to `http://`; use per-app `scheme=https` for HTTPS-only apps
- Version probes fail silently (WARNING log) if API key is missing for *arr apps
