# proxmon

Self-hosted Proxmox monitoring dashboard that continuously discovers LXC containers and VMs, identifies the application running inside each guest, compares the installed version against the latest upstream release on GitHub, and shows a live update-status dashboard — with a built-in setup wizard so you never have to touch a config file.

![build: passing](https://img.shields.io/badge/build-passing-brightgreen) ![tests: 84 passing](https://img.shields.io/badge/tests-84%20passing-brightgreen) ![license: MIT](https://img.shields.io/badge/license-MIT-blue)

<!-- screenshot: dashboard showing guests table with version status badges -->

---

## Table of Contents

1. [What is proxmon?](#1-what-is-proxmon)
2. [Architecture Overview](#2-architecture-overview)
3. [Features](#3-features)
4. [Supported Applications](#4-supported-applications)
5. [Quick Start](#5-quick-start)
6. [Proxmox API Token Setup](#6-proxmox-api-token-setup)
7. [Configuration Reference](#7-configuration-reference)
8. [Setup Wizard & Settings UI](#8-setup-wizard--settings-ui)
9. [App Detection Logic](#9-app-detection-logic)
10. [Version Checking Details](#10-version-checking-details)
11. [SSH Integration](#11-ssh-integration)
12. [API Reference](#12-api-reference)
13. [Development Setup](#13-development-setup)
14. [Writing a Custom Detector](#14-writing-a-custom-detector)
15. [Project Structure](#15-project-structure)
16. [Security Considerations](#16-security-considerations)
17. [Troubleshooting](#17-troubleshooting)
18. [Roadmap](#18-roadmap)
19. [License](#19-license)

---

## 1. What is proxmon?

Homelabs tend to accumulate services. A Proxmox node with 20 LXC containers running Sonarr, Radarr, Immich, Gitea, Traefik, and a dozen other apps quickly becomes a maintenance burden — not because updates are hard to apply, but because knowing which apps *need* updating requires visiting each one individually.

**proxmon** solves this by connecting directly to the Proxmox API, enumerating every LXC container and VM, fingerprinting the application inside each one (by guest name, Proxmox tag, or Docker image), querying the app's own API for its installed version, and comparing that against the latest GitHub release. The result is a single dashboard showing every guest, what's running inside it, and whether it's up to date.

No agents are installed on guests. No configuration is required on the guest side. proxmon connects to Proxmox read-only, optionally SSHs into guests to inspect Docker containers, and makes outbound HTTPS calls to GitHub. It runs entirely as a Docker Compose stack.

### How it works at a glance

```
Proxmox API → discover guests → detect app → query local API → compare to GitHub → dashboard
```

Every N seconds (default: 5 minutes), a background scheduler runs a full discovery cycle. Results are cached in memory and served to the React frontend via a REST API. The frontend polls every 60 seconds and renders the current state. A manual refresh button is also available.

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│  Browser                                                      │
│  React 18 + TypeScript + Tailwind (dark mode)                │
└─────────────────────┬───────────────────────────────────────┘
                      │ HTTP  :3000
┌─────────────────────▼───────────────────────────────────────┐
│  nginx (frontend container)                                   │
│  • serves compiled React SPA                                  │
│  • proxies /api/* and /health → backend:8000                 │
└─────────────────────┬───────────────────────────────────────┘
                      │ HTTP (internal Docker network)
┌─────────────────────▼───────────────────────────────────────┐
│  FastAPI backend (Python 3.12)                               │
│                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │  Scheduler   │  │  API routes  │  │  ConfigStore     │  │
│  │  asyncio bg  │  │  REST + DI   │  │  /app/data/      │  │
│  └──────┬───────┘  └──────────────┘  └──────────────────┘  │
│         │                                                     │
│  ┌──────▼──────────────────────────────────────────────┐    │
│  │  DiscoveryEngine                                      │    │
│  │  • ProxmoxClient (async httpx, GET-only)             │    │
│  │  • 14 Detector plugins (BaseDetector ABC)            │    │
│  │  • GitHubClient (releases API + 1h cache)            │    │
│  │  • SSHClient (paramiko, command whitelist)           │    │
│  └──────┬──────────────────┬────────────────────┬──────┘    │
└─────────┼──────────────────┼────────────────────┼───────────┘
          │                  │                    │
   ┌──────▼──────┐  ┌────────▼───────┐  ┌────────▼──────────┐
   │ Proxmox VE  │  │  GitHub API    │  │  LXC / VM guests  │
   │ REST API    │  │  releases/     │  │  (SSH, port 22)   │
   │ :8006       │  │  latest        │  │                   │
   └─────────────┘  └────────────────┘  └───────────────────┘
```

### Component responsibilities

| Component | Responsibility |
|---|---|
| **Scheduler** | asyncio background task; runs full discovery cycle every `POLL_INTERVAL_SECONDS`; supports manual trigger via `asyncio.Event` |
| **ProxmoxClient** | Async HTTP client for the Proxmox VE API; lists LXC containers and optionally VMs; resolves guest IPs from network config; enforces GET-only |
| **DiscoveryEngine** | Orchestrates the full cycle: list guests → detect app → get installed version → get latest version → compute status |
| **Detector plugins** | One class per app; matches guests by name/tag/Docker image; queries the app's local HTTP API for its version |
| **GitHubClient** | Fetches the latest release tag from GitHub Releases API; caches results for 1 hour; handles rate limits gracefully |
| **SSHClient** | Connects to guests via paramiko; runs `docker ps` to identify running containers; enforces a command whitelist and metacharacter guard |
| **ConfigStore** | Reads/writes `/app/data/proxmon.db` (SQLite); single-row settings table with JSON blob; auto-migrates from `config.json`; database takes priority over environment variables |
| **FastAPI routes** | REST API serving guests, settings, setup status, and connection test; dependency injection via `app.dependency_overrides` |
| **React frontend** | Dashboard, per-guest detail, editable settings, 5-step setup wizard; polls `/api/guests` every 60 s |

### Full poll cycle (step by step)

```
1. Scheduler fires (interval elapsed or manual trigger)
2. ProxmoxClient.list_guests()
   └── GET /nodes/{node}/lxc  →  list of LXC containers
   └── GET /nodes/{node}/qemu  →  list of VMs (if DISCOVER_VMS=true)
3. For each running guest (asyncio.gather, max 10 concurrent):
   a. Resolve guest IP
      └── GET /nodes/{node}/lxc/{vmid}/config  →  parse net0 ip= field
   b. Run detector pipeline:
      i.  Tag match: check Proxmox tags for "sonarr", "app:sonarr", etc.
      ii. Name match: tokenize guest name on [-_.\s], check each token
      iii. Docker match: SSH → "docker ps" → match image names
      iv. Fallback: mark as unknown
   c. If detector matched:
      └── detector.get_installed_version(ip, port)  →  HTTP GET to app API
   d. If github_repo is set:
      └── GitHubClient.fetch_latest(repo)  →  GET releases/latest (cached 1h)
   e. Compute update_status: up-to-date / outdated / unknown
   f. Append VersionCheck to history (max 10 entries)
4. Update in-memory guest dict (thread-safe, asyncio.Lock)
5. API serves updated data; frontend polls and re-renders
```

---

## 3. Features

### Phase 1 — Current (read-only)

- **Proxmox API integration** — connects via token-based auth; no password stored
- **Continuous discovery** — configurable polling interval (default: 5 min)
- **LXC + VM support** — LXC always; VMs optional (`DISCOVER_VMS=true`)
- **Multi-strategy app detection**:
  - Proxmox tag matching (`sonarr`, `app:sonarr`)
  - Guest name token matching (`sonarr-lxc` → sonarr)
  - Docker container inspection via SSH (`docker ps`)
- **15 built-in app detectors** — arr-stack, Plex, Immich, Gitea, Seer, and more
- **Installed version detection** — queries each app's own HTTP API
- **Latest version lookup** — GitHub Releases API with 1-hour cache
- **Semantic version comparison** — `packaging.version.Version`, handles build hashes
- **Per-guest version history** — last 10 checks retained in memory
- **Dashboard** — filterable table: status (outdated/up-to-date/unknown), type (LXC/VM), text search
- **Per-guest detail page** — all metadata, version history, raw detection output
- **Manual refresh** — POST `/api/refresh` triggers an immediate cycle
- **Setup wizard** — 5-step guided first-run configuration (no `.env` editing required)
- **Editable settings page** — live connection test, dirty tracking, save without restart
- **Config persistence** — settings saved to SQLite at `/app/data/proxmon.db` (Docker volume)
- **Per-app HTTPS scheme override** — configure `http` or `https` per app in Settings
- **Per-app GitHub repo override** — custom `owner/repo` per app in Settings (e.g. fork or alternate release source)
- **App logo in header** — clickable app names link to the app's web UI; responsive mobile layout
- **SQLite-backed config store** — settings persisted in SQLite (`/app/data/proxmon.db`); auto-migrates from `config.json` on first start
- **GitHub Actions CI** — auto-builds and pushes Docker images to `ghcr.io` on every push to main
- **Backward compatible** — existing `.env` deployments continue to work

### Phase 2 — Planned

- Update button per app (triggers update on the guest)
- Pre-update Proxmox snapshot hook (safety net before every update)
- App-specific update handlers (plugin per app)
- Audit log (who triggered what, when, outcome)
- Health checks per app (is the app actually responding?)
- Notification webhooks (ntfy, Gotify, Discord)
- Persistent version history (SQLite instead of in-memory)

---

## 4. Supported Applications

| App | Detection keys | Version endpoint | GitHub repo | Default port |
|---|---|---|---|---|
| **Sonarr** | `sonarr` | `GET /api/v3/system/status` → `version` | Sonarr/Sonarr | 8989 |
| **Radarr** | `radarr` | `GET /api/v3/system/status` → `version` | Radarr/Radarr | 7878 |
| **Bazarr** | `bazarr` | `GET /api/bazarr/api/v1/system/status` → `bazarr_version` | morpheus65535/bazarr | 6767 |
| **Prowlarr** | `prowlarr` | `GET /api/v1/system/status` → `version` | Prowlarr/Prowlarr | 9696 |
| **Overseerr** | `overseerr` | `GET /api/v1/status` → `version` | sct/overseerr | 5055 |
| **Plex** | `plex`, `plexmediaserver`, `pms` | `GET /identity` (XML attr) | plexinc/pms-docker | 32400 |
| **Immich** | `immich` | `GET /api/server/about` → `version` | immich-app/immich | 2283 |
| **Gitea** | `gitea` | `GET /api/v1/version` → `version` | go-gitea/gitea | 3000 |
| **qBittorrent** | `qbittorrent`, `qbit` | `GET /api/v2/app/version` (plain text) | qbittorrent/qBittorrent | 8080 |
| **SABnzbd** | `sabnzbd`, `sab` | `GET /api?mode=version&output=json` → `version` | sabnzbd/sabnzbd | 8085 |
| **Traefik** | `traefik` | `GET /api/version` → `version` | traefik/traefik | 8080 |
| **Caddy** | `caddy` | `GET :2019/config/` (admin API) | caddyserver/caddy | 2019 |
| **ntfy** | `ntfy` | `GET /v1/info` → `version` | binwiederhier/ntfy | 80 |
| **Seer** | `seer` | `GET /api/v1/status` → `version` | seerr-team/seerr | 5055 |
| **Docker (generic)** | any Docker image | image tag parsing | N/A | N/A |

**Detection keys** are matched against guest names (token-split on `-_.\s`) and Proxmox tags (exact match or `app:<key>`). For Docker detection, the image name substrings listed in each detector's `docker_images` list are matched against `docker ps` output.

---

## 5. Quick Start

### Prerequisites

- Docker and Docker Compose v2
- A running Proxmox VE node (6.x or later)
- A Proxmox API token (see [Section 6](#6-proxmox-api-token-setup))

### Steps

```bash
# 1. Clone
git clone <repo-url> proxmon
cd proxmon

# 2. Launch
docker compose up -d

# 3. Open the setup wizard
open http://localhost:3000
```

On first launch, proxmon starts in **unconfigured mode** and automatically redirects to the setup wizard. Fill in your Proxmox credentials, test the connection, and click **Save & Start**. The dashboard loads once the first discovery cycle completes (typically 5–15 seconds).

> **Using an existing `.env` file?**
> Copy it to the project root as `.env` — Docker Compose will load it automatically and proxmon will skip the wizard:
> ```bash
> cp backend/.env.example .env
> # edit .env with real values
> docker compose up -d
> ```

### Expected first-run output

```
proxmon-backend   | Starting proxmon
proxmon-backend   | proxmon starting in unconfigured mode -- visit the UI to configure
# (after wizard completes)
proxmon-backend   | Starting proxmon
proxmon-backend   | Settings saved via UI
proxmon-backend   | Discovered 12 LXC containers
proxmon-backend   | Detected sonarr on guest 101 (sonarr-lxc) via name_match
proxmon-backend   | Detected radarr on guest 102 (radarr-lxc) via name_match
proxmon-backend   | Discovery cycle complete: 12 guests, 9 detected, 3 unknown
```

### Updating

```bash
cd proxmon
docker compose pull          # if using pre-built images from ghcr.io
# or
docker compose build         # if building from source
docker compose up -d
```

Pre-built images are pushed to `ghcr.io/counterf/proxmonx-backend:latest` and `ghcr.io/counterf/proxmonx-frontend:latest` on every push to main via GitHub Actions.

---

## 6. Proxmox API Token Setup

proxmon uses Proxmox's API token authentication. Tokens are safer than passwords — they can be scoped to read-only permissions and revoked independently.

### Create the token

1. Log in to the Proxmox web UI
2. Go to **Datacenter → Permissions → API Tokens**
3. Click **Add**
4. Fill in:
   - **User**: `root@pam` (or a dedicated user)
   - **Token ID**: `proxmon` (becomes part of the token ID string)
   - **Privilege Separation**: check this box (limits token to explicitly granted permissions)
5. Click **Add** — copy the **Secret** immediately (shown only once)

Your token ID will be: `root@pam!proxmon`
Your token secret will be: a UUID like `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`

### Required permissions

Grant the token read-only access at the datacenter level:

1. Go to **Datacenter → Permissions → Add → API Token Permission**
2. Set:
   - **Path**: `/`
   - **API Token**: `root@pam!proxmon`
   - **Role**: `PVEAuditor` (read-only built-in role)
3. Click **Add**

The `PVEAuditor` role grants `VM.Audit` and `Sys.Audit` — sufficient to list containers, VMs, and their network configs. proxmon never writes to Proxmox in Phase 1.

### Verify

```bash
curl -sk "https://<proxmox-host>:8006/api2/json/version" \
  -H "Authorization: PVEAPIToken=root@pam!proxmon=<secret>"
# Should return: {"data":{"version":"8.x.x",...}}
```

---

## 7. Configuration Reference

proxmon reads configuration from two sources, in priority order:

```
/app/data/proxmon.db    ← highest priority (SQLite, written by setup wizard / settings UI)
environment variables   ← fallback (from .env file or docker-compose env_file)
built-in defaults       ← lowest priority
```

When you configure proxmon via the UI, settings are saved to the SQLite database. Environment variables continue to work for all fields — useful for secret management via Docker secrets or CI/CD pipelines.

> **Migration from config.json**: If upgrading from an earlier version that used `config.json`, proxmon automatically imports it into SQLite on first start. No manual migration needed.

### All configuration variables

| Variable | Default | Required | Description |
|---|---|---|---|
| `PROXMOX_HOST` | — | **Yes** | Full URL including port, e.g. `https://192.168.1.10:8006` |
| `PROXMOX_TOKEN_ID` | — | **Yes** | API token ID, format `user@realm!tokenname` |
| `PROXMOX_TOKEN_SECRET` | — | **Yes** | UUID secret from Proxmox token creation |
| `PROXMOX_NODE` | — | **Yes** | Node name shown in Proxmox UI, e.g. `pve` |
| `POLL_INTERVAL_SECONDS` | `300` | No | Seconds between discovery cycles (min: 30, max: 3600) |
| `DISCOVER_VMS` | `false` | No | Set `true` to also enumerate QEMU VMs |
| `VERIFY_SSL` | `false` | No | Set `true` to verify Proxmox TLS certificate (requires a valid cert) |
| `SSH_ENABLED` | `true` | No | Enable SSH-based Docker container inspection |
| `SSH_USERNAME` | `root` | No | Username for SSH connections to guests |
| `SSH_KEY_PATH` | — | No | Absolute path to SSH private key file (inside container) |
| `SSH_PASSWORD` | — | No | SSH password (key auth preferred; only used if `SSH_KEY_PATH` unset) |
| `SSH_KNOWN_HOSTS_PATH` | — | No | Path to known_hosts file; enables strict host key verification |
| `GITHUB_TOKEN` | — | No | GitHub personal access token; increases rate limit from 60 to 5,000 req/hr |
| `CORS_ORIGINS` | `http://localhost:3000,http://frontend` | No | Allowed CORS origins (comma-separated or JSON array) |
| `LOG_LEVEL` | `info` | No | `debug` / `info` / `warning` / `error` |
| `PROXMON_ENABLED` | `true` | No | Master switch; set `false` to pause all polling |
| `PROXMON_API_KEY` | — | No | API key for protecting mutating endpoints (POST settings, refresh) |
| `CONFIG_DB_PATH` | `/app/data/proxmon.db` | No | Override path for SQLite config database |

### SSH key mount example

If using key-based SSH authentication, mount the key into the backend container:

```yaml
# docker-compose.override.yml
services:
  backend:
    volumes:
      - ./data:/app/data
      - ~/.ssh/id_ed25519:/app/ssh/id_ed25519:ro
    environment:
      SSH_KEY_PATH: /app/ssh/id_ed25519
```

### `.env.example`

```bash
# Required (or configure via wizard)
PROXMOX_HOST=https://192.168.1.10:8006
PROXMOX_TOKEN_ID=root@pam!proxmon
PROXMOX_TOKEN_SECRET=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
PROXMOX_NODE=pve

# Discovery
POLL_INTERVAL_SECONDS=300
DISCOVER_VMS=false
VERIFY_SSL=false

# SSH (for Docker detection)
SSH_USERNAME=root
SSH_KEY_PATH=/app/ssh/id_rsa
SSH_ENABLED=true
# SSH_PASSWORD=         # alternative to key auth
# SSH_KNOWN_HOSTS_PATH=/app/ssh/known_hosts

# GitHub (recommended)
# GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Application
LOG_LEVEL=info
PROXMON_ENABLED=true
```

### Per-app configuration

Per-app overrides are configured in the Settings UI under the **App Configuration** section. Each detected app can have the following overrides:

| Field | Type | Default | Description |
|---|---|---|---|
| `port` | `int` | Detector default | Override the HTTP port used for version probing |
| `api_key` | `string` | — | API key for authenticated endpoints (e.g. *arr apps) |
| `scheme` | `string` | `http` | Protocol scheme: `http` or `https` |
| `github_repo` | `string` | Detector default | Override the GitHub `owner/repo` for latest version lookup |

---

## 8. Setup Wizard & Settings UI

### First-run wizard

When proxmon starts without a valid Proxmox configuration, it enters **unconfigured mode**. The frontend detects this via `GET /api/setup/status → { configured: false }` and renders the 5-step setup wizard instead of the dashboard.

```
Step 1 — Proxmox Connection
  • Host URL          (required, must start with http:// or https://)
  • API Token ID      (required, format: user@realm!tokenname)
  • API Token Secret  (required, show/hide toggle)
  • Node Name         (required, e.g. pve)

Step 2 — Discovery
  • Poll Interval     (seconds, 30–3600, default 300)
  • Include VMs       (toggle, default off)
  • Verify SSL        (toggle, default off — amber warning shown when off)

Step 3 — SSH
  • Enable SSH        (toggle; collapses rest of section if off)
  • SSH Username      (default: root)
  • Auth method       (radio: key file / password)
  • Key path or password field (conditional)

Step 4 — GitHub Token
  • Personal access token (optional, masked input)
  • Explanation of rate limit benefit (60 → 5,000 req/hr)

Step 5 — Review & Save
  • Read-only summary of all settings (secrets masked)
  • "Test Connection" button (async, shows spinner → green/red result)
  • "Save & Start" button
  • "Skip test and save anyway" link (for VPN/firewall scenarios)
```

After saving, a transition screen polls `GET /health` until `guest_count > 0` (max 30 seconds), then navigates to the dashboard.

### Settings page

The Settings page (`/settings`) is a fully editable form with the same four sections as the wizard, plus a **Per-App Configuration** section where you can set port, API key, scheme (`http`/`https`), and GitHub repo overrides for each detected app. It pre-populates from `GET /api/settings/full` (with secrets shown as `***`).

Key behaviors:
- **Dirty tracking** — unsaved changes indicator; `beforeunload` warning if you try to navigate away
- **Token secret** — send `null` to keep existing secret unchanged; changing it sends the new value
- **Test Connection** — live Proxmox test using the values currently in the form (does not save)
- **Save Changes** — writes to `/app/data/proxmon.db`, reloads settings, restarts the scheduler with zero downtime
- **Success toast** — auto-dismisses after 4 seconds

### Config persistence

Settings saved via the UI are stored in a SQLite database at `/app/data/proxmon.db` (mounted as `./data:/app/data` in Docker Compose). The database uses a single `settings` table with one row containing a JSON blob. On restart, the database is loaded first; env vars fill in anything not in the database.

**Migration from config.json**: if upgrading from a version that used `config.json`, proxmon automatically imports it into SQLite on first start. The original file is left in place but is no longer read after migration.

**Backward compatibility**: if you already have a working `.env` file and no database exists, proxmon reads all settings from env vars and skips the wizard. No migration needed.

---

## 9. App Detection Logic

Each guest goes through a three-stage detection pipeline. The first stage to produce a match wins.

### Stage 1 — Tag match (highest priority)

proxmon reads the Proxmox tags field for each guest. Tags are matched against:
- Exact detector name: `sonarr`
- Prefixed format: `app:sonarr`

Example: a guest with Proxmox tags `sonarr;media` will be detected as Sonarr.

To add a tag in Proxmox: **Container/VM → Summary → Tags → Edit**.

### Stage 2 — Name match

The guest's name is split on delimiters (`-`, `_`, `.`, whitespace) and each token is checked against detector names and aliases.

```
Guest name: "sonarr-lxc-01"
Tokens:     ["sonarr", "lxc", "01"]
Matches:    SonarrDetector (name="sonarr")  ✓
```

```
Guest name: "media-server"
Tokens:     ["media", "server"]
Matches:    nothing  →  proceed to stage 3
```

This token-based approach prevents false positives from substring matches (e.g. `"openpms"` would not match Plex's alias `"pms"`).

### Stage 3 — Docker container inspection (SSH)

If name and tag matching fail and SSH is enabled, proxmon connects to the guest via SSH and runs:

```bash
docker ps --format '{{.Image}}'
```

The output (one image name per line) is matched against each detector's `docker_images` list using substring matching:

```
docker ps output:  linuxserver/sonarr:latest
SonarrDetector.docker_images: ["sonarr", "linuxserver/sonarr"]
Match: "sonarr" in "linuxserver/sonarr:latest"  ✓
```

### Stage 4 — Fallback

If no detector matches after all three stages, the guest is marked `app_name: null`, `update_status: "unknown"`.

### After detection

Once a detector is matched:

1. **Installed version** — `detector.get_installed_version(ip, port, api_key, scheme)` makes an HTTP GET to the app's local API on the guest's IP. If the request fails or times out (5 s), `installed_version` is set to `null`.

2. **Latest version** — `GitHubClient.fetch_latest(github_repo)` queries the GitHub Releases API. Results are cached for 1 hour. Detectors with `github_repo = None` (like `DockerGenericDetector`) skip this step.

3. **Update status** computation:
   - Both versions known → compare using `packaging.version.Version`
   - Either version unknown → `"unknown"`
   - `installed >= latest` → `"up-to-date"`
   - `installed < latest` → `"outdated"`

---

## 10. Version Checking Details

### GitHub API

proxmon calls `GET https://api.github.com/repos/{owner}/{repo}/releases/latest` and reads the `tag_name` field.

```json
{
  "tag_name": "v4.0.14.2939",
  "name": "Sonarr v4.0.14.2939"
}
```

**Caching**: results are stored in a dict keyed by `"{owner}/{repo}"` with a 1-hour TTL. This means the 60/5,000 req/hr rate limit is consumed at most once per repo per hour regardless of how many guests are running the same app.

**Rate limits**:

| Token | Requests/hr | Suitable for |
|---|---|---|
| None (unauthenticated) | 60 | ≤ 5 unique apps |
| `GITHUB_TOKEN` set | 5,000 | Any homelab |

Set `GITHUB_TOKEN` to a GitHub PAT with no scopes (read-only public data) to avoid rate limit issues.

**Error handling**: 404 (no releases) → `latest_version: null`. Rate limit (429/403) → `latest_version: null`, warning logged. Network error → `latest_version: null`.

### Version normalization

Before comparison, both versions are normalized:

1. Strip leading `v`: `"v4.0.14"` → `"4.0.14"`
2. Strip build hash suffix (split on `-`, take first segment): `"1.40.0.7998-c29d4c0c8"` → `"1.40.0.7998"`

Comparison uses `packaging.version.Version` for proper semantic ordering. Falls back to string equality if parsing fails (handles non-semver tags like Proxmox's `8.3-1`).

### Update status logic

```
installed_version = None  →  update_status = "unknown"
latest_version    = None  →  update_status = "unknown"
installed >= latest       →  update_status = "up-to-date"
installed <  latest       →  update_status = "outdated"
```

---

## 11. SSH Integration

SSH is used exclusively for Docker container detection (Stage 3 of the detection pipeline). It is optional — disable it with `SSH_ENABLED=false` if your guests don't run Docker or you prefer not to grant SSH access.

### How it works

1. `DiscoveryEngine._process_guest()` calls `SSHClient.execute(ip, "docker ps --format {{.Image}}")`
2. `SSHClient.execute()` dispatches to `asyncio.to_thread(self._execute_sync, ...)` to avoid blocking the event loop
3. `_execute_sync()` opens a paramiko SSH connection, runs the command, reads stdout
4. Output is returned to the engine, which matches image names against all detector `docker_images` lists

### Security

**Command whitelist**: only commands with these prefixes are allowed:

```python
COMMAND_WHITELIST = frozenset({
    "docker ps",
    "docker inspect",
    "cat ",
    "which ",
    "dpkg -l",
    "rpm -q",
})
```

**Metacharacter guard**: before the prefix check, the command string is rejected if it contains:

```
; & | ` $ < > ( ) { } ! \n \ #
```

This prevents injection like `"docker ps; rm -rf /"` — the `;` is caught before the prefix is checked.

**Host key policy**:

| Condition | Policy | Behavior |
|---|---|---|
| `SSH_KNOWN_HOSTS_PATH` set and file exists | `RejectPolicy` | Refuses connections with unknown/changed host keys |
| `SSH_KNOWN_HOSTS_PATH` not set | `WarningPolicy` | Logs a warning for unknown host keys but connects |

To enable strict host key verification:

```bash
# On the proxmon host, scan your Proxmox guests:
ssh-keyscan 192.168.1.100 192.168.1.101 ... >> ./data/known_hosts

# In .env or settings:
SSH_KNOWN_HOSTS_PATH=/app/data/known_hosts
```

### Authentication

Key file (recommended):
```bash
SSH_KEY_PATH=/app/ssh/id_ed25519
SSH_USERNAME=root
```

Password (fallback):
```bash
SSH_PASSWORD=yourpassword
SSH_USERNAME=root
```

---

## 12. API Reference

All endpoints are served by the FastAPI backend. In production (Docker Compose), the frontend nginx container proxies `/api/*` and `/health` to the backend. In development, Vite's dev server does the same.

### `GET /health`

Returns backend status and statistics.

```json
{
  "status": "ok",
  "configured": true,
  "last_poll": "2026-03-08T14:23:01+00:00",
  "guest_count": 12,
  "is_polling": false,
  "seconds_since_last_poll": 47.3
}
```

When unconfigured: `"status": "unconfigured"`, `"configured": false`, counts are 0.

---

### `GET /api/guests`

Returns all discovered guests as a summary list.

```json
[
  {
    "id": "101",
    "name": "sonarr-lxc",
    "type": "lxc",
    "status": "running",
    "app_name": "sonarr",
    "installed_version": "4.0.14.2939",
    "latest_version": "4.0.14.2939",
    "update_status": "up-to-date",
    "last_checked": "2026-03-08T14:23:01+00:00",
    "tags": ["media", "arr"]
  }
]
```

Returns `[]` when unconfigured.

---

### `GET /api/guests/{id}`

Returns full detail for a single guest including version history and raw detection output.

```json
{
  "id": "101",
  "name": "sonarr-lxc",
  "type": "lxc",
  "status": "running",
  "app_name": "sonarr",
  "installed_version": "4.0.14.2939",
  "latest_version": "4.0.14.2939",
  "update_status": "up-to-date",
  "last_checked": "2026-03-08T14:23:01+00:00",
  "tags": ["media", "arr"],
  "ip": "192.168.1.101",
  "detection_method": "name_match",
  "detector_used": "sonarr",
  "raw_detection_output": {"version": "4.0.14.2939", "branch": "main"},
  "version_history": [
    {
      "timestamp": "2026-03-08T14:23:01+00:00",
      "installed_version": "4.0.14.2939",
      "latest_version": "4.0.14.2939",
      "update_status": "up-to-date"
    }
  ]
}
```

Returns `404` if guest ID not found. Returns `503` when unconfigured.

---

### `POST /api/refresh`

Triggers an immediate discovery cycle. Returns `202 Accepted` immediately; the cycle runs asynchronously.

```json
{"status": "started"}
```

Returns `503` when unconfigured.

---

### `GET /api/settings`

Returns current settings with all secrets masked.

```json
{
  "proxmox_host": "https://192.168.1.10:8006",
  "proxmox_token_id": "root@pam!****",
  "proxmox_node": "pve",
  "poll_interval_seconds": 300,
  "discover_vms": false,
  "verify_ssl": false,
  "ssh_username": "root",
  "ssh_enabled": true,
  "github_token_set": true,
  "log_level": "info",
  "proxmon_enabled": true
}
```

---

### `GET /api/settings/full`

Returns all settings for pre-populating the settings form. Secrets shown as `"***"` if set, `null` if not set.

```json
{
  "proxmox_host": "https://192.168.1.10:8006",
  "proxmox_token_id": "root@pam!proxmon",
  "proxmox_token_secret": "***",
  "proxmox_node": "pve",
  "poll_interval_seconds": 300,
  "discover_vms": false,
  "verify_ssl": false,
  "ssh_enabled": true,
  "ssh_username": "root",
  "ssh_key_path": "/app/ssh/id_rsa",
  "ssh_password": null,
  "github_token": "***",
  "log_level": "info"
}
```

---

### `POST /api/settings/test-connection`

Tests Proxmox connectivity with the provided credentials **without saving them**. Always returns `200`; check `success` field.

Request body:
```json
{
  "proxmox_host": "https://192.168.1.10:8006",
  "proxmox_token_id": "root@pam!proxmon",
  "proxmox_token_secret": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "proxmox_node": "pve",
  "verify_ssl": false
}
```

Success response:
```json
{
  "success": true,
  "message": "Connected to Proxmox 8.3.2 on node pve",
  "node_info": {
    "pve_version": "8.3.2",
    "node": "pve",
    "uptime": 1209600
  }
}
```

Failure response:
```json
{
  "success": false,
  "message": "Authentication failed: invalid token ID or secret",
  "node_info": null
}
```

---

### `POST /api/settings`

Saves settings to `/app/data/proxmon.db` and hot-reloads: restarts the scheduler with the new config without restarting the container.

Request body (all fields):
```json
{
  "proxmox_host": "https://192.168.1.10:8006",
  "proxmox_token_id": "root@pam!proxmon",
  "proxmox_token_secret": null,
  "proxmox_node": "pve",
  "poll_interval_seconds": 300,
  "discover_vms": false,
  "verify_ssl": false,
  "ssh_enabled": true,
  "ssh_username": "root",
  "ssh_key_path": null,
  "github_token": null,
  "log_level": "info"
}
```

> `proxmox_token_secret: null` means "keep the current secret" — the backend resolves it from the config file or env var before saving. Send the actual secret string only when changing it.

Response:
```json
{"success": true, "message": "Settings saved"}
```

Returns `422` for validation errors, `500` if the config file is unwritable or the scheduler fails to start.

---

### `GET /api/setup/status`

Returns whether the app is fully configured and which required fields are missing.

```json
{
  "configured": false,
  "missing_fields": ["proxmox_token_secret"]
}
```

---

## 13. Development Setup

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Node.js 20+
- Docker + Docker Compose (for integration testing)

### Backend

```bash
cd backend

# Install dependencies (creates .venv automatically)
uv sync --all-extras

# Copy and edit config
cp .env.example .env
# Edit .env with your Proxmox credentials

# Run development server (auto-reload)
uv run uvicorn app.main:app --reload --port 8000

# Run tests
uv run --extra dev pytest -v

# Run tests with coverage
uv run --extra dev pytest --cov=app --cov-report=term-missing
```

The backend reads `.env` from the `backend/` directory when run locally.

### Frontend

```bash
cd frontend

# Install dependencies
npm install

# Start dev server (auto-proxies /api to :8000)
npm run dev
# → http://localhost:3000

# Type-check
npm run build

# Preview production build
npm run preview
```

Vite's dev proxy is configured in `vite.config.ts`:

```ts
server: {
  proxy: {
    '/api': 'http://localhost:8000',
    '/health': 'http://localhost:8000',
  }
}
```

### Docker Compose (both services)

```bash
# Production build
docker compose up -d --build

# Tail logs
docker compose logs -f

# Rebuild after code changes
docker compose build && docker compose up -d

# Dev overrides (hot reload)
cp docker-compose.override.yml.example docker-compose.override.yml
docker compose up -d
```

The `docker-compose.override.yml.example` mounts source directories for hot-reload in development.

### Running tests

```bash
cd backend
uv run --extra dev pytest -v
```

```
tests/test_config_store.py     8 tests  — load, save, migration, merge, is_configured
tests/test_detectors.py       36 tests  — detection matching + version fetching for all 15 apps
tests/test_discovery.py       10 tests  — Proxmox parsing, IP resolution, full cycle integration
tests/test_github.py           8 tests  — caching, v-prefix stripping, rate limit, auth header
tests/test_ssh_version_cmd.py 22 tests  — SSH version command safety validation
─────────────────────────────────────────────────────
Total: 84 tests, ~2 seconds
```

---

## 14. Writing a Custom Detector

Detectors are Python classes that inherit from `BaseDetector`. Adding a new one takes about 20 lines.

### Step 1 — Create the detector file

```python
# backend/app/detectors/homebridge.py
from app.detectors.base import BaseDetector


class HomeBridgeDetector(BaseDetector):
    # Name used for name/tag matching (lowercase, no spaces)
    name = "homebridge"

    # Human-readable name shown in the UI
    display_name = "Homebridge"

    # GitHub repo for latest version lookup ("owner/repo"), or None to skip
    github_repo = "homebridge/homebridge"

    # Additional name tokens that match this detector (besides `name`)
    aliases: list[str] = ["hb"]

    # Port to connect to when querying the app's local API
    default_port = 8581

    # Docker image substrings for Docker detection
    docker_images: list[str] = ["homebridge/homebridge", "oznu/homebridge"]

    async def get_installed_version(
        self, host: str, port: int | None = None, api_key: str | None = None,
        scheme: str = "http",
    ) -> str | None:
        """Query Homebridge's local REST API for its installed version."""
        p = port or self.default_port
        try:
            resp = await self._http_get(f"{scheme}://{host}:{p}/api/auth/noauth")
            if resp.status_code == 200:
                data = resp.json()
                # Homebridge returns version in env.packageVersion
                return data.get("env", {}).get("packageVersion")
        except Exception:
            pass
        return None
```

### Step 2 — Register it

```python
# backend/app/detectors/registry.py

from app.detectors.homebridge import HomeBridgeDetector   # add this import

ALL_DETECTORS: list[BaseDetector] = [
    SonarrDetector(),
    RadarrDetector(),
    # ... existing detectors ...
    HomeBridgeDetector(),   # add to list
]
```

### Step 3 — Rebuild

```bash
docker compose up -d --build backend
```

### BaseDetector reference

| Attribute / method | Type | Required | Description |
|---|---|---|---|
| `name` | `str` | Yes | Primary key for name and tag matching |
| `display_name` | `str` | Yes | UI display name |
| `github_repo` | `str \| None` | Yes | `"owner/repo"` for GitHub lookup, `None` to skip |
| `aliases` | `list[str]` | Yes | Additional name tokens (do not duplicate `name`) |
| `default_port` | `int` | Yes | Default HTTP port for version probing |
| `docker_images` | `list[str]` | Yes | Docker image substrings for `docker ps` matching |
| `get_installed_version(host, port, api_key, scheme)` | `async → str \| None` | Yes | Return version string or `None` on any failure |
| `_http_get(url, timeout)` | `async → httpx.Response` | Inherited | HTTP GET helper; uses shared connection pool in production |
| `detect(guest)` | `→ str \| None` | Inherited | Returns `"tag_match"`, `"name_match"`, or `None` |
| `match_docker_image(image)` | `→ bool` | Inherited | Returns `True` if `image` matches any entry in `docker_images` |

### Detection matching rules

- **Tag match**: Proxmox tag equals `name` or `app:{name}`, or same for any alias
- **Name match**: guest name split on `[-_.\s]+`; any token equals `name` or any alias
- **Docker match**: Docker image string contains any substring from `docker_images`

### Version string tips

- Return exactly what the app reports; normalization (stripping `v`, build hash) happens in `DiscoveryEngine`
- Return `None` on any exception — never let `get_installed_version` raise
- Use `self._http_get()` instead of creating your own `httpx.AsyncClient` — it uses the shared connection pool
- For XML responses (like Plex), use `xml.etree.ElementTree.fromstring(resp.text)`
- For plain-text responses (like qBittorrent), use `resp.text.strip()`

---

## 15. Project Structure

```
proxmon/
│
├── backend/                          Python 3.12 / FastAPI
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                   FastAPI app entry point
│   │   │                             • lifespan: config loading, scheduler init
│   │   │                             • CORS middleware (env-configured origins)
│   │   │                             • dependency injection via app.dependency_overrides
│   │   │
│   │   ├── config.py                 pydantic-settings Settings class
│   │   │                             • all env vars with defaults
│   │   │                             • optional Proxmox fields (unconfigured mode)
│   │   │                             • masked_settings() for safe API exposure
│   │   │
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   └── routes.py             All HTTP endpoints + request/response models
│   │   │                             • SettingsSaveRequest (Pydantic v2, field validators)
│   │   │                             • ConnectionTestRequest
│   │   │                             • graceful 503 when scheduler is None (unconfigured)
│   │   │
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── config_store.py       /app/data/proxmon.db SQLite read/write
│   │   │   │                         • single settings row, JSON blob
│   │   │   │                         • auto-migrates config.json on first start
│   │   │   │                         • merge_into_settings(settings) → Settings
│   │   │   │                         • is_configured() / get_missing_fields()
│   │   │   │
│   │   │   ├── discovery.py          DiscoveryEngine orchestrator
│   │   │   │                         • run_full_cycle(existing_guests) → dict
│   │   │   │                         • asyncio.gather with semaphore (max 10 concurrent)
│   │   │   │                         • error isolation: one guest failure doesn't stop others
│   │   │   │                         • version history append-then-truncate (MAX=10)
│   │   │   │
│   │   │   ├── github.py             GitHub Releases API client
│   │   │   │                         • 1-hour in-memory TTL cache
│   │   │   │                         • v-prefix stripping + build hash normalization
│   │   │   │                         • graceful rate limit handling
│   │   │   │
│   │   │   ├── proxmox.py            Proxmox VE async API client
│   │   │   │                         • GET-only enforced (ALLOWED_METHODS = frozenset{"GET"})
│   │   │   │                         • list_guests() → LXC + optional VM
│   │   │   │                         • get_guest_network() → IP from net0/ipconfig0
│   │   │   │                         • check_connection() for settings test
│   │   │   │
│   │   │   ├── scheduler.py          asyncio background scheduler
│   │   │   │                         • asyncio.Event for manual refresh (no task cancel)
│   │   │   │                         • asyncio.Lock for thread-safe guest dict access
│   │   │   │                         • guests property returns dict copy (no torn reads)
│   │   │   │
│   │   │   └── ssh.py                paramiko SSH executor
│   │   │                             • asyncio.to_thread (non-blocking)
│   │   │                             • COMMAND_WHITELIST (frozenset of allowed prefixes)
│   │   │                             • SHELL_METACHARACTERS regex guard
│   │   │                             • WarningPolicy / RejectPolicy host key handling
│   │   │
│   │   ├── detectors/
│   │   │   ├── __init__.py
│   │   │   ├── base.py               BaseDetector ABC
│   │   │   │                         • instance-level http_client (not class-level)
│   │   │   │                         • _name_matches(): token-split matching
│   │   │   │                         • detect(): tag → name → None
│   │   │   │                         • match_docker_image(): substring match
│   │   │   │                         • _http_get(): shared client or per-request fallback
│   │   │   │
│   │   │   ├── registry.py           ALL_DETECTORS list + DOCKER_DETECTOR + DETECTOR_MAP
│   │   │   ├── sonarr.py
│   │   │   ├── radarr.py
│   │   │   ├── bazarr.py
│   │   │   ├── prowlarr.py
│   │   │   ├── overseerr.py
│   │   │   ├── plex.py               XML parsing via xml.etree.ElementTree
│   │   │   ├── immich.py
│   │   │   ├── gitea.py
│   │   │   ├── qbittorrent.py        plain-text response
│   │   │   ├── sabnzbd.py
│   │   │   ├── traefik.py
│   │   │   ├── caddy.py              admin API on port 2019
│   │   │   ├── ntfy.py
│   │   │   └── docker_generic.py     image tag parsing, no GitHub lookup
│   │   │
│   │   └── models/
│   │       ├── __init__.py
│   │       └── guest.py              Pydantic v2 models
│   │                                 • GuestInfo (internal, mutable)
│   │                                 • GuestSummary (API response, list view)
│   │                                 • GuestDetail (API response, detail view)
│   │                                 • VersionCheck (history entry)
│   │
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── test_config_store.py      config store: load, save, migration, merge
│   │   ├── test_detectors.py         detection matching + version fetching (all 14 apps)
│   │   ├── test_discovery.py         Proxmox parsing, IP resolution, full cycle
│   │   └── test_github.py            caching, normalization, rate limits
│   │
│   ├── Dockerfile                    Python 3.12-slim + uv + curl (healthcheck)
│   ├── pyproject.toml                hatchling build, uv deps, pytest config
│   └── .env.example                  documented env var template
│
├── frontend/                         React 18 + TypeScript + Vite + Tailwind CSS
│   ├── src/
│   │   ├── main.tsx                  React entry point (BrowserRouter)
│   │   ├── index.css                 Tailwind directives + dark mode base
│   │   │
│   │   ├── App.tsx                   Root component
│   │   │                             • fetchSetupStatus() on mount
│   │   │                             • renders SetupWizard when unconfigured
│   │   │                             • renders navbar + Routes when configured
│   │   │
│   │   ├── api/
│   │   │   └── client.ts             Typed fetch wrappers
│   │   │                             • HttpError class (structured status code)
│   │   │                             • fetchGuests, fetchGuest, triggerRefresh
│   │   │                             • fetchSetupStatus, fetchFullSettings
│   │   │                             • testConnection, saveSettings
│   │   │
│   │   ├── types/
│   │   │   └── index.ts              TypeScript interfaces matching backend Pydantic models
│   │   │                             • GuestSummary, GuestDetail, VersionCheck
│   │   │                             • SetupStatus, FullSettings, SettingsSaveRequest
│   │   │                             • ConnectionTestResult, HealthStatus, AppSettings
│   │   │
│   │   ├── hooks/
│   │   │   └── useGuests.ts          Data fetching hook
│   │   │                             • 60-second auto-poll (setInterval)
│   │   │                             • manual refresh (triggerRefresh + 2s wait + reload)
│   │   │                             • HttpError 503 → "not_configured" error state
│   │   │
│   │   └── components/
│   │       ├── Dashboard.tsx         Main guest table
│   │       │                         • FilterBar (status / type / text search)
│   │       │                         • loading skeleton, empty states
│   │       │                         • health badge + last-refresh timestamp
│   │       │                         • refresh button with spinner
│   │       │
│   │       ├── GuestRow.tsx          Single table row
│   │       │                         • type badge (LXC/VM)
│   │       │                         • StatusBadge
│   │       │                         • relative time display
│   │       │                         • click → navigate to detail
│   │       │
│   │       ├── GuestDetail.tsx       Per-guest detail page (/guest/:id)
│   │       │                         • breadcrumb navigation
│   │       │                         • all GuestDetail fields
│   │       │                         • version history table (last 10)
│   │       │                         • collapsible raw detection output (JSON)
│   │       │
│   │       ├── Settings.tsx          Editable settings form (/settings)
│   │       │                         • pre-populates from /api/settings/full
│   │       │                         • dirty tracking + tokenSecretChanged ref
│   │       │                         • beforeunload guard
│   │       │                         • ConnectionTestButton
│   │       │                         • sticky Save Changes bar
│   │       │                         • SuccessToast on save
│   │       │
│   │       ├── setup/
│   │       │   ├── SetupWizard.tsx   5-step first-run wizard
│   │       │   │                     • per-step validation (blur + Next press)
│   │       │   │                     • mountedRef unmount guard for poll loop
│   │       │   │                     • transition screen with health polling
│   │       │   │
│   │       │   ├── FormField.tsx     Label + input wrapper + error display
│   │       │   ├── PasswordField.tsx Input with show/hide eye toggle
│   │       │   ├── Toggle.tsx        ARIA switch (aria-labelledby, role=switch)
│   │       │   ├── ConnectionTestButton.tsx  Async test + inline result (idle/loading/ok/err)
│   │       │   └── SuccessToast.tsx  Auto-dismiss toast (ref-captured callback, no timer reset)
│   │       │
│   │       ├── FilterBar.tsx         Status / type dropdowns + text search (URL param sync)
│   │       ├── StatusBadge.tsx       Color-coded pill: green/red/gray
│   │       ├── ErrorBanner.tsx       Dismissible error with retry
│   │       └── LoadingSpinner.tsx    Centered spinner with optional text
│   │
│   ├── Dockerfile                    Node 20 build stage → nginx:alpine serve stage
│   ├── nginx.conf                    SPA fallback + /api proxy + gzip
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   └── postcss.config.js
│
├── docs/
│   ├── prd.md                        Product requirements (MVP)
│   ├── prd-setup-ui.md               Product requirements (setup UI)
│   ├── ux-spec.md                    UX specification (dashboard + detail)
│   └── ux-spec-setup-ui.md           UX specification (wizard + settings)
│
├── data/                             (created at runtime, gitignored)
│   └── proxmon.db                    UI-saved settings (SQLite)
│
├── .github/
│   └── workflows/
│       └── docker-build.yml          CI: build & push to ghcr.io on push to main
│
├── docker-compose.yml                Production: backend (internal) + frontend (:3000)
├── docker-compose.override.yml.example  Dev: hot reload mounts
├── CLAUDE.md                         Claude Code project context
├── .gitignore
└── README.md
```

---

## 16. Security Considerations

### Proxmox access

- proxmon uses an **API token**, not your root password
- The `ProxmoxClient` enforces `ALLOWED_METHODS = frozenset({"GET"})` — write requests are refused at the client level, not just avoided
- The recommended `PVEAuditor` role grants read-only access only
- Token secret is never logged; `masked_settings()` replaces it with `"****"` in all API responses

### SSH access

- Commands are validated against `COMMAND_WHITELIST` (prefix match) **and** a metacharacter guard (regex rejecting `;`, `|`, `$`, `(`, `)`, `{`, `}`, `!`, `#`, `\n`, `\`)
- Only `docker ps`, `docker inspect`, `cat`, `which`, `dpkg -l`, `rpm -q` prefixes are permitted
- `WarningPolicy` by default; set `SSH_KNOWN_HOSTS_PATH` for `RejectPolicy` (MITM protection)

### Config database

- `/app/data/proxmon.db` is a SQLite database with a single settings row
- Token secret is stored in plaintext in the database — this is an accepted trade-off for a self-hosted homelab tool; do not expose the data volume publicly

### Network

- Backend is **not exposed** on the host network; only the frontend (nginx, port 3000) is published
- CORS is configured with explicit allowed origins, no wildcard
- No authentication on the web UI — designed for local network use; do not expose port 3000 to the public internet

### GitHub API

- Only public release data is read; no write operations
- `GITHUB_TOKEN` requires no scopes — a token with no permissions grants 5,000 req/hr for public data

---

## 17. Troubleshooting

### Connection issues

| Symptom | Cause | Fix |
|---|---|---|
| "Connection refused" in test-connection | Wrong host or port | Verify `PROXMOX_HOST` includes the port (`:8006`) |
| "Authentication failed" | Wrong token ID or secret | Regenerate token in Proxmox; check format `user@realm!tokenname` |
| "Authorization denied" | Insufficient token permissions | Add `PVEAuditor` role to the token at path `/` |
| SSL errors with `VERIFY_SSL=true` | Self-signed certificate | Set `VERIFY_SSL=false` or install a valid cert on Proxmox |
| Wizard shows even after setting `.env` | `.env` not found by Docker Compose | Ensure `.env` is in the project root (same directory as `docker-compose.yml`) |

### Detection issues

| Symptom | Cause | Fix |
|---|---|---|
| All guests show "unknown" | Guest names don't match any detector | Add Proxmox tags (e.g. `sonarr`) to the guest |
| Specific guest not detected | Name tokenization doesn't match | Check: `"sonarr-01"` → tokens `["sonarr", "01"]` → matches. `"arr-sonarr"` → also matches. `"xsonarr"` → does not match (no token equals "sonarr") |
| Installed version shows `null` | App not reachable on its default port | Guest may use a non-default port; SSH detection only finds the app, not the port |
| App always shows "outdated" | Plex build hash in version string | Normalized to `1.40.0.7998` — should match. If not, check GitHub repo tag format |

### Version checking

| Symptom | Cause | Fix |
|---|---|---|
| Latest version always `null` | GitHub rate limit hit | Set `GITHUB_TOKEN` in settings |
| Latest version shows wrong release | App uses non-standard tag format | Open an issue; the detector's `github_repo` may need a custom normalization |
| "outdated" for an up-to-date app | Version comparison fails for non-semver | Falls back to string equality; should still work for exact matches |

### SSH issues

| Symptom | Cause | Fix |
|---|---|---|
| Docker detection not working | SSH disabled | Enable SSH in settings |
| SSH connection refused | Guest doesn't have SSH | Install and enable sshd on the guest |
| "Command not in whitelist" in logs | A detector tried a non-whitelisted command | This is a bug; open an issue |
| Host key warnings in logs | `SSH_KNOWN_HOSTS_PATH` not set | Expected; set it to enable strict verification |

### GitHub token `"***"` bug

If GitHub API calls return 401 Unauthorized after saving settings, the masked placeholder `"***"` may have been saved as the actual token value. To fix: open Settings, clear the GitHub Token field, type the new token, and save. The `_keep_or_replace()` function in `routes.py` guards against this, but older UI versions or manual API calls can trigger it.

### Container / Docker Compose

| Symptom | Cause | Fix |
|---|---|---|
| Config lost after `docker compose down` | `./data` volume not mounted | Default `docker-compose.yml` includes `./data:/app/data`; config is in `proxmon.db` |
| Backend fails to start | Missing required env vars (`.env` mode) | Check logs: `docker compose logs backend` |
| Frontend shows "Failed to fetch" | Backend not running or unhealthy | Check: `docker compose ps`, `docker compose logs backend` |
| Port 3000 already in use | Another service on the host | Change the port mapping in `docker-compose.yml`: `"3001:80"` |

### Viewing logs

```bash
# All services
docker compose logs -f

# Backend only
docker compose logs -f backend

# With timestamps
docker compose logs -f -t backend

# Last 100 lines
docker compose logs --tail=100 backend
```

---

## 18. Roadmap

### Phase 2 (planned)

- [ ] **Update button** — trigger app update directly from the dashboard
- [ ] **Pre-update snapshot** — automatic Proxmox snapshot before every update (rollback point)
- [ ] **App-specific update handlers** — plugin per app (e.g. `apt upgrade sonarr`, Docker pull + restart)
- [ ] **Audit log** — immutable record of all update actions with timestamps, outcomes, and user context
- [ ] **Health checks** — per-app HTTP health probe (is the app actually responding, not just running?)
- [ ] **Notification webhooks** — push alerts to ntfy, Gotify, or Discord when updates are available
- [ ] **Persistent history** — SQLite backend so version history survives restarts
- [x] **Multi-node support** — monitor guests across multiple Proxmox nodes (shipped)

---

## 19. License

MIT License — see [LICENSE](LICENSE) for details.

---

*Built for homelab operators who want to know what needs updating without visiting 20 web UIs.*
