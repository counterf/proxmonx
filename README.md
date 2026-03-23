# proxmon

Self-hosted Proxmox monitoring dashboard that continuously discovers LXC containers and VMs, identifies the application running inside each guest, compares the installed version against the latest upstream release on GitHub, and shows a live update-status dashboard — with a built-in setup wizard so you never have to touch a config file.

![build: passing](https://img.shields.io/badge/build-passing-brightgreen) ![tests: 169 passing](https://img.shields.io/badge/tests-169%20passing-brightgreen) ![license: MIT](https://img.shields.io/badge/license-MIT-blue)

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
9. [Login & Authentication](#9-login--authentication)
10. [App Detection Logic](#10-app-detection-logic)
11. [Version Checking Details](#11-version-checking-details)
12. [SSH Integration](#12-ssh-integration)
13. [API Reference](#13-api-reference)
14. [Development Setup](#14-development-setup)
15. [Writing a Custom Detector](#15-writing-a-custom-detector)
16. [Project Structure](#16-project-structure)
17. [Security Considerations](#17-security-considerations)
18. [Troubleshooting](#18-troubleshooting)
19. [Roadmap](#19-roadmap)
20. [License](#20-license)

---

## 1. What is proxmon?

Homelabs tend to accumulate services. A Proxmox node with 20 LXC containers running Sonarr, Radarr, Immich, Gitea, Traefik, and a dozen other apps quickly becomes a maintenance burden — not because updates are hard to apply, but because knowing which apps *need* updating requires visiting each one individually.

**proxmon** solves this by connecting directly to the Proxmox API, enumerating every LXC container and VM, fingerprinting the application inside each one (by guest name, Proxmox tag, or Docker image), querying the app's own API for its installed version, and comparing that against the latest GitHub release. The result is a single dashboard showing every guest, what's running inside it, and whether it's up to date.

No agents are installed on guests. No configuration is required on the guest side. proxmon connects to Proxmox read-only, optionally SSHs into guests to inspect Docker containers, and makes outbound HTTPS calls to GitHub. It runs as a single Docker container.

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
│  Single Docker container (Python 3.12)                       │
│  Uvicorn serves API + built React SPA                        │
│                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │  Scheduler   │  │  API routes  │  │  ConfigStore     │  │
│  │  asyncio bg  │  │  REST + DI   │  │  /app/data/      │  │
│  └──────┬───────┘  └──────────────┘  └──────────────────┘  │
│         │                                                     │
│  ┌──────▼──────────────────────────────────────────────┐    │
│  │  DiscoveryEngine                                      │    │
│  │  • ProxmoxClient (async httpx, GET-only)             │    │
│  │  • 15 detectors (config-driven HttpJsonDetector +     │    │
│  │    specialized: Plex, qBittorrent, SABnzbd, Caddy)   │    │
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
| **SSHClient** | Connects to guests via paramiko; runs `docker ps` to identify running containers; executes version commands via SSH or `pct exec`; enforces a command whitelist and metacharacter guard |
| **ConfigStore** | Reads/writes `/app/data/proxmon.db` (SQLite); single-row settings table with JSON blob; all application config lives in the database |
| **FastAPI routes** | REST API serving guests, settings, setup status, and connection test; dependency injection via `app.dependency_overrides` |
| **React frontend** | Dashboard, per-guest detail, editable settings, 5-step setup wizard; polls `/api/guests` every 60 s |

### Full poll cycle (step by step)

```
1. Scheduler fires (interval elapsed or manual trigger)
2. ProxmoxClient.list_guests()
   └── GET /nodes/{node}/lxc  →  list of LXC containers
   └── GET /nodes/{node}/qemu  →  list of VMs (if DISCOVER_VMS=true)
3. For each running guest (asyncio.gather, max 10 concurrent):
   a. Resolve guest IP + OS type
      └── GET /nodes/{node}/lxc/{vmid}/config  →  parse net0 ip= field + ostype
   b. Run detector pipeline:
      i.  Tag match: check Proxmox tags for "sonarr", "app:sonarr", etc.
      ii. Name match: tokenize guest name on [-_.\s], check each token
      iii. Docker match: SSH → "docker ps" → match image names
      iv. Fallback: mark as unknown
   c. If detector matched, resolve config (guest > app > detector defaults):
      └── detector.get_installed_version(ip, port, api_key, scheme)  →  HTTP GET to app API
      └── If API fails, try CLI fallback (pct exec or SSH) based on VERSION_DETECT_METHOD
   d. If github_repo is set:
      └── GitHubClient.fetch_latest(repo)  →  GET releases/latest (cached 1h)
   e. Compute update_status: up-to-date / outdated / unknown
   f. Append VersionCheck to history (max 10 entries)
4. Update in-memory guest dict (thread-safe, asyncio.Lock)
5. AlertManager evaluates disk + outdated rules → sends ntfy notifications
6. API serves updated data; frontend polls and re-renders
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
- **15 built-in app detectors** — arr-stack, Plex, Immich, Gitea, Seerr, and more; most are config-driven via `http_json.py`; specialized detectors (Plex, qBittorrent, SABnzbd, Caddy) subclass `BaseDetector` directly
- **Installed version detection** — queries each app's own HTTP API
- **Latest version lookup** — GitHub Releases API with 1-hour cache
- **Semantic version comparison** — `packaging.version.Version`, handles build hashes
- **Per-guest version history** — last 10 checks retained in memory
- **Dashboard** — filterable, sortable table with configurable columns; status badges, disk usage bars, OS type, detection method
- **Configurable columns** — add/remove dashboard columns; selection persisted in browser
- **Disk usage monitoring** — color-coded bars per guest (blue < 50%, green 50–75%, amber 76–90%, red 90%+)
- **OS type display** — shows the guest OS (Alpine, Debian, Ubuntu, etc.) from Proxmox config
- **App icons** — icons from [selfhst/icons](https://github.com/selfhst/icons) displayed next to app names
- **Per-guest detail page** — all metadata, version history, raw detection output, instance settings
- **Manual refresh** — POST `/api/refresh` triggers an immediate cycle
- **Setup wizard** — 5-step guided first-run configuration (no `.env` editing required)
- **Editable settings page** — live connection test, dirty tracking, field descriptions, save without restart
- **Config persistence** — settings saved to SQLite at `/app/data/proxmon.db` (Docker volume)
- **Multi-host support** — monitor guests across multiple Proxmox VE nodes from a single dashboard
- **Per-app configuration** — override port, API key, scheme, GitHub repo, and SSH settings per app
- **Per-guest configuration** — override API key, port, and scheme for individual guest instances (guest > app > detector defaults)
- **Version detection cascade** — API probe first, then CLI fallback via pct exec or SSH (configurable: `pct_first`, `ssh_first`, `ssh_only`, `pct_only`)
- **ntfy notifications** — push alerts when disk usage exceeds a threshold or an app becomes outdated; configurable cooldown
- **App logo in header** — clickable app names link to the app's web UI; responsive mobile layout
- **SQLite-backed config store** — settings persisted in SQLite (`/app/data/proxmon.db`)
- **GitHub Actions CI** — auto-builds and pushes a single Docker image to `ghcr.io` on every push to main
- **SQLite-only config** — all settings stored in SQLite; no `.env` file needed

### Phase 2 — Planned

- Update button per app (triggers update on the guest)
- Pre-update Proxmox snapshot hook (safety net before every update)
- App-specific update handlers (plugin per app)
- Audit log (who triggered what, when, outcome)
- Health checks per app (is the app actually responding?)
- Additional notification channels (Gotify, Discord, webhooks)
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
| **Immich** | `immich` | `GET /api/server/about` → `version` (requires API key with `server.about` permission) | immich-app/immich | 2283 |
| **Gitea** | `gitea` | `GET /api/v1/version` → `version` | go-gitea/gitea | 3000 |
| **qBittorrent** | `qbittorrent`, `qbit` | `GET /api/v2/app/version` (plain text) | qbittorrent/qBittorrent | 8080 |
| **SABnzbd** | `sabnzbd`, `sab` | `GET /api?mode=version&output=json` → `version` | sabnzbd/sabnzbd | 8085 |
| **Traefik** | `traefik` | `GET /api/version` → `version` | traefik/traefik | 8080 |
| **Caddy** | `caddy` | `GET :2019/config/` (admin API) | caddyserver/caddy | 2019 |
| **ntfy** | `ntfy` | `GET /v1/info` → `version` | binwiederhier/ntfy | 80 |
| **Seerr** | `seerr`, `seer` | `GET /api/v1/status` → `version` | seerr-team/seerr | 5055 |
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

> **Note:** All configuration is stored in the SQLite database (`/app/data/proxmon.db`). No `.env` file is needed — just run `docker compose up -d` and complete the setup wizard in your browser.

### Expected first-run output

```
proxmon  | Starting proxmon
proxmon  | proxmon starting in unconfigured mode -- visit the UI to configure
# (after wizard completes)
proxmon  | Starting proxmon
proxmon  | Settings saved via UI
proxmon  | Discovered 12 LXC containers
proxmon  | Detected sonarr on guest 101 (sonarr-lxc) via name_match
proxmon  | Detected radarr on guest 102 (radarr-lxc) via name_match
proxmon  | Discovery cycle complete: 12 guests, 9 detected, 3 unknown
```

### Custom port

By default proxmon listens on port **3000**. To use a different port, set the `PORT` environment variable and match it in your port mapping:

```yaml
# docker-compose.override.yml
services:
  proxmon:
    environment:
      PORT: 8080
    ports:
      - "8080:8080"
```

### Updating

```bash
cd proxmon
docker compose pull          # if using pre-built images from ghcr.io
# or
docker compose build         # if building from source
docker compose up -d
```

Pre-built images are pushed to `ghcr.io/counterf/proxmon:latest` on every push to main via GitHub Actions.

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
/app/data/proxmon.db    ← SQLite database (written by setup wizard / settings UI)
built-in defaults       ← lowest priority
```

All application configuration is stored in the SQLite database. Configure everything via the setup wizard or Settings UI.

### Environment variables

Only two environment variables are recognized (both optional):

| Variable | Default | Description |
|---|---|---|
| `CONFIG_DB_PATH` | `/app/data/proxmon.db` | Override path for the SQLite config database |
| `PORT` | `3000` | Port the app listens on inside the container |

All other settings (Proxmox hosts, SSH, GitHub token, notifications, API key, etc.) are configured through the **Settings UI** and persisted in the SQLite database.

### SSH key mount example

If using key-based SSH authentication, mount the key into the container and set the path in Settings → SSH:

```yaml
# docker-compose.override.yml
services:
  proxmon:
    volumes:
      - ./data:/app/data
      - ~/.ssh/id_ed25519:/app/ssh/id_ed25519:ro
```

Then set **SSH Key Path** to `/app/ssh/id_ed25519` in the Settings UI.

### Per-app configuration

Per-app overrides are configured in the Settings UI under the **App Configuration** section. Each detected app can have the following overrides:

| Field | Type | Default | Description |
|---|---|---|---|
| `port` | `int` | Detector default | Override the HTTP port used for version probing |
| `api_key` | `string` | — | API key for authenticated endpoints (e.g. *arr apps, Immich) |
| `scheme` | `string` | `http` | Protocol scheme: `http` or `https` |
| `github_repo` | `string` | Detector default | Override the GitHub `owner/repo` for latest version lookup |
| `ssh_version_cmd` | `string` | — | Custom SSH command for CLI-based version detection |
| `ssh_username` | `string` | Global default | Override SSH username for this app |
| `ssh_key_path` | `string` | — | Override SSH private key path for this app |
| `ssh_password` | `string` | — | Override SSH password for this app |

### Per-guest configuration

When multiple instances of the same app exist, per-guest overrides take precedence over per-app overrides. Configure them via the "Instance Settings" panel on each guest's detail page, or via API.

Configuration priority: **guest-specific > app-specific > detector defaults**.

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

The Settings page (`/settings`) is a fully editable form with sections for Proxmox hosts, discovery, SSH, GitHub token, **notifications** (ntfy), and **per-app configuration** where you can set port, API key, scheme (`http`/`https`), GitHub repo, and SSH overrides for each detected app. Every field includes a description/hint. It pre-populates from `GET /api/settings/full` (with secrets shown as `***`).

Key behaviors:
- **Dirty tracking** — unsaved changes indicator; `beforeunload` warning if you try to navigate away
- **Token secret** — send `null` to keep existing secret unchanged; changing it sends the new value
- **Test Connection** — live Proxmox test using the values currently in the form (does not save)
- **Save Changes** — writes to `/app/data/proxmon.db`, reloads settings, restarts the scheduler with zero downtime
- **Success toast** — auto-dismisses after 4 seconds

### Config persistence

Settings are stored in a SQLite database at `/app/data/proxmon.db` (mounted as `./data:/app/data` in Docker Compose). The database uses a single `settings` table with one row containing a JSON blob.

---

## 9. Login & Authentication

proxmon ships with a built-in forms-based authentication system enabled by default. On first start, a default admin account is automatically created.

### Default credentials

| Field | Value |
|---|---|
| Username | `root` |
| Password | `proxmon!` |

**Change the default password immediately** via Settings → Security → Change Password.

### How it works

- Sessions are stored in the same SQLite database (`/app/data/proxmon.db`) using UUID tokens with a 24-hour TTL
- The session token is set as an `HttpOnly`, `SameSite=Lax` cookie (`proxmon_session`)
- Password hashing uses **scrypt** (stdlib, no extra dependencies) with a random salt per password
- All `/api/*` routes (except `/api/auth/*` and `/api/setup/status`) require a valid session when `auth_mode=forms`

### Changing your password

1. Log in to the dashboard
2. Go to **Settings → Security**
3. Enter a new password (minimum 8 characters) and click **Change Password**

Alternatively, via API:
```bash
curl -X POST http://localhost:3000/api/auth/change-password \
  -H "Content-Type: application/json" \
  -b "proxmon_session=<your-token>" \
  -d '{"current_password": "your-current-password", "new_password": "my-new-password"}'
```

### Disabling authentication

If proxmon runs in a fully trusted network and you don't want to log in every session, set `auth_mode=disabled` in Settings → Security. This bypasses all session checks — any request to `/api/*` is treated as authenticated.

### Auth API endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/auth/login` | Validate credentials, set session cookie |
| `POST` | `/api/auth/logout` | Revoke session, clear cookie |
| `GET` | `/api/auth/status` | Return `{auth_mode, authenticated}` |
| `POST` | `/api/auth/change-password` | Change password (session required) |

### API key bypass

For automation and scripts, set the **API Key** in Settings → Security and pass it as an `X-Api-Key` header. API key access bypasses session auth for all regular API routes but **cannot** be used for `change-password` (session required).

```bash
curl -H "X-Api-Key: my-secret-api-key" http://localhost:3000/api/guests
```

### Rate limiting

Login attempts are rate-limited to **10 requests per 60 seconds per IP** to prevent brute-force attacks. Exceeded limits return `HTTP 429`.

---

## 10. App Detection Logic

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

## 11. Version Checking Details

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

## 12. SSH Integration

SSH is used for Docker container detection (Stage 3 of the detection pipeline) and as a fallback for version detection when the app's HTTP API probe fails. The version detection cascade (configurable via `VERSION_DETECT_METHOD`) tries API first, then `pct exec` or SSH depending on the strategy. SSH is optional — disable it with `SSH_ENABLED=false` if your guests don't run Docker or you prefer not to grant SSH access.

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

# Then set SSH Known Hosts Path to /app/data/known_hosts in Settings UI
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

## 13. API Reference

All endpoints are served by the FastAPI backend. In production, the same process serves the API and the frontend SPA. In development, Vite's dev server proxies `/api/*` and `/health` to the backend.

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
    "tags": ["media", "arr"],
    "host_id": "pve1",
    "host_label": "PVE Main",
    "disk_used": 2147483648,
    "disk_total": 10737418240,
    "os_type": "debian",
    "latest_version_source": "github"
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

### `GET /api/guests/{id}/config`

Returns the per-guest configuration override for a specific guest instance.

```json
{
  "api_key": "***",
  "port": 8989,
  "scheme": "https"
}
```

Returns an empty object (`{}`) if no per-guest config exists.

---

### `PUT /api/guests/{id}/config`

Creates or updates a per-guest configuration override. Fields not provided are left unchanged.

Request body:
```json
{
  "api_key": "my-secret-key",
  "port": 8989,
  "scheme": "https"
}
```

Response:
```json
{"status": "saved"}
```

---

### `DELETE /api/guests/{id}/config`

Removes all per-guest configuration overrides for a guest.

Response:
```json
{"status": "cleared"}
```

---

### `POST /api/notifications/test`

Sends a test notification via ntfy using the currently saved notification settings. Useful for verifying ntfy URL, token, and connectivity.

Response:
```json
{"success": true, "message": "Test notification sent successfully"}
```

Returns `{"success": false, "message": "..."}` if notifications are disabled or the ntfy server is unreachable.

---

### `GET /api/settings/full`

Returns all settings for pre-populating the settings form. Secrets shown as `"***"` if set, `null` if not set.

```json
{
  "proxmox_hosts": [
    {
      "id": "pve1",
      "label": "PVE Main",
      "host": "https://192.168.1.10:8006",
      "token_id": "root@pam!proxmon",
      "token_secret": "***",
      "node": "pve",
      "verify_ssl": false,
      "ssh_username": "root",
      "ssh_password": null,
      "ssh_key_path": null,
      "pct_exec_enabled": true
    }
  ],
  "poll_interval_seconds": 300,
  "discover_vms": false,
  "verify_ssl": false,
  "ssh_enabled": true,
  "ssh_username": "root",
  "ssh_key_path": "/app/ssh/id_rsa",
  "ssh_password": null,
  "github_token": "***",
  "version_detect_method": "pct_first",
  "log_level": "info",
  "notifications_enabled": false,
  "ntfy_url": null,
  "ntfy_token": null,
  "ntfy_priority": 3,
  "notify_disk_threshold": 95,
  "notify_disk_cooldown_minutes": 60,
  "notify_on_outdated": true,
  "app_config": {},
  "guest_config": {}
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

## 14. Development Setup

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

# Run development server (auto-reload)
uv run uvicorn app.main:app --reload --port 8000

# Run tests
uv run --extra dev pytest -v

# Run tests with coverage
uv run --extra dev pytest --cov=app --cov-report=term-missing
```

The backend stores all configuration in SQLite. On first launch, complete the setup wizard at `http://localhost:3000`.

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

### Docker Compose

```bash
# Production build (single container)
docker compose up -d --build

# Tail logs
docker compose logs -f

# Rebuild after code changes
docker compose build && docker compose up -d
```

### Running tests

```bash
cd backend
uv run --extra dev pytest -v
```

```
tests/test_alerting.py        17 tests  — disk threshold, cooldown, outdated transitions, enable/disable
tests/test_config_store.py     6 tests  — load, save, merge, is_configured
tests/test_detectors.py       37 tests  — detection matching + version fetching for all 15 apps
tests/test_discovery.py       16 tests  — Proxmox parsing, IP resolution, config resolution, full cycle
tests/test_github.py           8 tests  — caching, v-prefix stripping, rate limit, auth header
tests/test_notifier.py         8 tests  — ntfy send, auth, priority, error handling, shared client
tests/test_ssh_version_cmd.py 22 tests  — SSH version command safety validation
─────────────────────────────────────────────────────
Total: 169 tests, ~5 seconds
```

---

## 15. Writing a Custom Detector

There are two paths depending on how the app exposes its version.

### Path A — Simple JSON endpoint (most apps)

Add a `DetectorConfig` entry to `SIMPLE_DETECTOR_CONFIGS` in `backend/app/detectors/http_json.py`. No new file needed.

```python
# backend/app/detectors/http_json.py  →  SIMPLE_DETECTOR_CONFIGS list

DetectorConfig(
    name="homebridge",
    display_name="Homebridge",
    github_repo="homebridge/homebridge",
    default_port=8581,
    path="/api/server",          # GET endpoint that returns JSON with version
    version_keys=("version",),   # JSON key(s) to extract (dot-notation supported)
    docker_images=["homebridge/homebridge", "oznu/homebridge"],
    aliases=["hb"],
    accepts_api_key=False,
),
```

Then register it in `backend/app/detectors/registry.py`:

```python
ALL_DETECTORS: list[BaseDetector] = [
    # ... existing entries ...
    make_detector("homebridge"),  # add this line
]
```

### Path B — Non-JSON or custom auth (e.g. Plex XML, qBittorrent cookie auth)

Create a subclass in a new file and register it directly:

```python
# backend/app/detectors/homebridge.py
from app.detectors.base import BaseDetector

class HomeBridgeDetector(BaseDetector):
    name = "homebridge"
    display_name = "Homebridge"
    github_repo = "homebridge/homebridge"
    aliases: list[str] = ["hb"]
    default_port = 8581
    docker_images: list[str] = ["homebridge/homebridge", "oznu/homebridge"]

    async def get_installed_version(
        self, host: str, port: int | None = None, api_key: str | None = None,
        scheme: str = "http",
    ) -> str | None:
        p = port or self.default_port
        try:
            resp = await self._http_get(f"{scheme}://{host}:{p}/api/auth/noauth")
            if resp.status_code == 200:
                return resp.json().get("env", {}).get("packageVersion")
        except Exception:
            pass
        return None
```

```python
# backend/app/detectors/registry.py
from app.detectors.homebridge import HomeBridgeDetector

ALL_DETECTORS: list[BaseDetector] = [
    # ... existing entries ...
    HomeBridgeDetector(),
]
```

### Step 3 — Rebuild

```bash
docker compose up -d --build
```

### DetectorConfig reference

| Field | Type | Description |
|---|---|---|
| `name` | `str` | Primary key for name/tag matching (lowercase) |
| `display_name` | `str` | UI label |
| `github_repo` | `str \| None` | `"owner/repo"` for latest-version lookup, `None` to skip |
| `default_port` | `int` | HTTP port for version probe |
| `path` | `str` | URL path for the version endpoint |
| `version_keys` | `tuple[str, ...]` | JSON key(s) to try in order; dot-notation for nested (e.g. `"data.version"`) |
| `docker_images` | `list[str]` | Image name substrings for `docker ps` matching |
| `aliases` | `list[str]` | Extra name tokens beyond `name` |
| `accepts_api_key` | `bool` | Whether this app uses an API key header |
| `auth_header` | `str \| None` | Header name for the API key (e.g. `"X-Api-Key"`) |
| `strip_v` | `bool` | Strip leading `v` from version string (e.g. `v1.2.3` → `1.2.3`) |
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

## 16. Project Structure

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
│   │   │   │                         • merge_into_settings(settings) → Settings
│   │   │   │                         • is_configured() / get_missing_fields()
│   │   │   │
│   │   │   ├── alerting.py           Alert evaluation engine
│   │   │   │                         • disk threshold with per-guest cooldown
│   │   │   │                         • outdated transition detection (one-shot)
│   │   │   │                         • dispatches via NtfyNotifier
│   │   │   │
│   │   │   ├── discovery.py          DiscoveryEngine orchestrator
│   │   │   │                         • run_full_cycle(existing_guests) → dict
│   │   │   │                         • asyncio.gather with semaphore (max 10 concurrent)
│   │   │   │                         • error isolation: one guest failure doesn't stop others
│   │   │   │                         • version history append-then-truncate (MAX=10)
│   │   │   │                         • layered config resolution (guest > app > detector)
│   │   │   │
│   │   │   ├── github.py             GitHub Releases API client
│   │   │   │                         • 1-hour in-memory TTL cache
│   │   │   │                         • v-prefix stripping + build hash normalization
│   │   │   │                         • graceful rate limit handling
│   │   │   │
│   │   │   ├── notifier.py           ntfy push notification sender
│   │   │   │                         • async HTTP POST to ntfy server
│   │   │   │                         • bearer token auth, configurable priority
│   │   │   │                         • never raises (logs warnings on failure)
│   │   │   │
│   │   │   ├── proxmox.py            Proxmox VE async API client
│   │   │   │                         • GET-only enforced (ALLOWED_METHODS = frozenset{"GET"})
│   │   │   │                         • list_guests() → LXC + optional VM
│   │   │   │                         • get_guest_network() → (IP, os_type) from net0/config
│   │   │   │                         • check_connection() for settings test
│   │   │   │
│   │   │   ├── scheduler.py          asyncio background scheduler
│   │   │   │                         • asyncio.Event for manual refresh (no task cancel)
│   │   │   │                         • asyncio.Lock for thread-safe guest dict access
│   │   │   │                         • guests property returns dict copy (no torn reads)
│   │   │   │                         • AlertManager integration (post-cycle evaluation)
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
│   │   │   ├── seerr.py              aliases: seer
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
│   │   ├── test_alerting.py          disk/outdated alert logic, cooldowns
│   │   ├── test_config_store.py      config store: load, save, merge, is_configured
│   │   ├── test_detectors.py         detection matching + version fetching (all 15 apps)
│   │   ├── test_discovery.py         Proxmox parsing, IP resolution, config resolution, full cycle
│   │   ├── test_github.py            caching, normalization, rate limits
│   │   ├── test_notifier.py          ntfy send, auth, errors, shared client
│   │   └── test_ssh_version_cmd.py   SSH command whitelist + metacharacter guard
│   │
│   ├── Dockerfile                    Backend-only build (dev use only)
│   ├── pyproject.toml                hatchling build, uv deps, pytest config
│   └── .env.example                  documents CONFIG_DB_PATH (the only env var)
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
│   │   │   ├── useGuests.ts          Data fetching hook
│   │   │   │                         • 60-second auto-poll (setInterval)
│   │   │   │                         • manual refresh (triggerRefresh + 2s wait + reload)
│   │   │   │                         • HttpError 503 → "not_configured" error state
│   │   │   │
│   │   │   └── useColumnVisibility.ts  Column visibility management
│   │   │                             • COLUMN_DEFS registry (all dashboard columns)
│   │   │                             • persists selection to localStorage
│   │   │
│   │   └── components/
│   │       ├── AppIcon.tsx           App icon from selfhst/icons CDN
│   │       │                         • maps app name to icon slug
│   │       │                         • graceful fallback on load error
│   │       │
│   │       ├── ColumnToggle.tsx      Column visibility toggle dropdown
│   │       │
│   │       ├── Dashboard.tsx         Main guest table
│   │       │                         • FilterBar (status / type / text search)
│   │       │                         • configurable columns with persistence
│   │       │                         • sorting by any visible column
│   │       │                         • health badge + last-refresh timestamp
│   │       │                         • refresh button with spinner
│   │       │
│   │       ├── GuestRow.tsx          Single table row
│   │       │                         • dynamic cells based on visible columns
│   │       │                         • DiskUsageCell (color-coded progress bar)
│   │       │                         • VersionSourceCell (API/PCT/SSH badge)
│   │       │                         • OsTypeCell (OS icon + label)
│   │       │                         • click → navigate to detail
│   │       │
│   │       ├── GuestDetail.tsx       Per-guest detail page (/guest/:id)
│   │       │                         • breadcrumb navigation
│   │       │                         • all GuestDetail fields + instance settings panel
│   │       │                         • version history table (last 10)
│   │       │                         • collapsible raw detection output (JSON)
│   │       │
│   │       ├── Settings.tsx          Editable settings form (/settings)
│   │       │                         • pre-populates from /api/settings/full
│   │       │                         • dirty tracking + tokenSecretChanged ref
│   │       │                         • field descriptions / hints throughout
│   │       │                         • notification section (ntfy config + test)
│   │       │                         • ConnectionTestButton
│   │       │                         • sticky Save Changes bar
│   │       │                         • SuccessToast on save
│   │       │
│   │       ├── settings/
│   │       │   ├── AppConfigSection.tsx    Per-app config (port, api_key, scheme, github_repo)
│   │       │   └── ProxmoxHostsSection.tsx Multi-host config with per-host settings
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
│   ├── Dockerfile                    Standalone frontend build (dev use only)
│   ├── nginx.conf                    Dev nginx config (not used in production)
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
│       └── docker-build.yml          CI: build & push single image to ghcr.io on push to main
│
├── Dockerfile                        Multi-stage: builds frontend + backend into one image
├── docker-compose.yml                Single service: proxmon on port 3000
├── CLAUDE.md                         Claude Code project context
├── .gitignore
└── README.md
```

---

## 17. Security Considerations

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

- The app listens on port 3000 by default (configurable via `PORT` env var)
- CORS is configured with explicit allowed origins for local development; production uses same-origin
- Forms-based authentication is enabled by default (see [§9 Login & Authentication](#9-login--authentication)); set `auth_mode=disabled` only on trusted local networks
- Default password is `proxmon!` — change it immediately after first login

### GitHub API

- Only public release data is read; no write operations
- `GITHUB_TOKEN` requires no scopes — a token with no permissions grants 5,000 req/hr for public data

---

## 18. Troubleshooting

### Connection issues

| Symptom | Cause | Fix |
|---|---|---|
| "Connection refused" in test-connection | Wrong host or port | Verify `PROXMOX_HOST` includes the port (`:8006`) |
| "Authentication failed" | Wrong token ID or secret | Regenerate token in Proxmox; check format `user@realm!tokenname` |
| "Authorization denied" | Insufficient token permissions | Add `PVEAuditor` role to the token at path `/` |
| SSL errors with `VERIFY_SSL=true` | Self-signed certificate | Set `VERIFY_SSL=false` or install a valid cert on Proxmox |
| Wizard keeps showing | No valid config in SQLite database | Complete the setup wizard or check that `./data` volume is mounted |

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
| App fails to start | Corrupted config database or missing volume | Check logs: `docker compose logs proxmon` |
| Frontend shows "Failed to fetch" | Container not running or unhealthy | Check: `docker compose ps`, `docker compose logs proxmon` |
| Port 3000 already in use | Another service on the host | Set `PORT=3001` and change port mapping to `"3001:3001"` |

### Viewing logs

```bash
# Follow logs
docker compose logs -f

# With timestamps
docker compose logs -f -t

# Last 100 lines
docker compose logs --tail=100
```

---

## 19. Roadmap

### Phase 2 (planned)

- [ ] **Update button** — trigger app update directly from the dashboard
- [ ] **Pre-update snapshot** — automatic Proxmox snapshot before every update (rollback point)
- [ ] **App-specific update handlers** — plugin per app (e.g. `apt upgrade sonarr`, Docker pull + restart)
- [ ] **Audit log** — immutable record of all update actions with timestamps, outcomes, and user context
- [ ] **Health checks** — per-app HTTP health probe (is the app actually responding, not just running?)
- [ ] **Additional notification channels** — Gotify, Discord, generic webhook support
- [ ] **Persistent history** — SQLite backend so version history survives restarts

### Already shipped (Phase 1.x)

- [x] **Multi-node support** — monitor guests across multiple Proxmox nodes
- [x] **ntfy notifications** — push alerts for disk threshold and outdated transitions with configurable cooldown
- [x] **Per-guest configuration** — instance-level API key, port, scheme overrides
- [x] **Configurable dashboard columns** — user can show/hide columns; selection persisted in browser
- [x] **Disk usage monitoring** — color-coded disk bars on the dashboard
- [x] **OS type display** — guest OS from Proxmox config shown in dashboard
- [x] **App icons** — icons from selfhst/icons CDN next to app names
- [x] **Version detection cascade** — API > PCT > SSH fallback strategy
- [x] **Settings field descriptions** — hints and descriptions for all configuration options

---

## 20. License

MIT License — see [LICENSE](LICENSE) for details.

---

*Built for homelab operators who want to know what needs updating without visiting 20 web UIs.*
