# Proxmon -- Product Requirements Document

| Field        | Value                              |
|--------------|------------------------------------|
| Author       | Alysson Silva                      |
| Status       | Draft                              |
| Created      | 2026-03-08                         |
| Last updated | 2026-03-08                         |
| Version      | 0.1                                |

---

## 1. Context & Why Now

- Homelab operators run dozens of self-hosted apps across Proxmox LXC containers and VMs. Keeping track of which app version is deployed vs. what is available upstream is manual, error-prone, and often neglected until something breaks.
- Proxmox itself has no concept of "application version" -- it only sees OS-level guests. No first-party tool bridges the gap between infrastructure (Proxmox) and application lifecycle (versions, updates).
- Existing solutions (Watchtower, Renovate, Diun) focus on Docker-native workflows and do not address LXC containers, which are the dominant deployment model in Proxmox homelabs.
- The Proxmox API is stable, well-documented, and supports token-based auth -- making automated, read-only integration low-risk.

Source -- Proxmox VE API docs confirm API token support since PVE 6.1 (2019).
Source -- r/homelab and r/selfhosted surveys consistently cite "keeping things updated" as a top pain point.

---

## 2. Users & Jobs To Be Done

| User               | Job To Be Done                                                                 |
|---------------------|--------------------------------------------------------------------------------|
| Homelab operator    | Know at a glance which apps are outdated so I can plan maintenance windows.     |
| Homelab operator    | Verify a specific app version after a manual update without SSHing into each guest. |
| Homelab operator    | Discover all running apps automatically instead of maintaining a manual inventory. |
| Security-conscious user | Identify apps running known-outdated versions that may have CVE exposure.      |

---

## 3. Business Goals & Success Metrics

### Goals
- Provide a single-pane-of-glass for application version status across a Proxmox cluster.
- Require zero agent installation on guests (agentless, API + SSH-based detection).
- Ship a working MVP within 4 weeks as a Docker Compose one-liner.

### Leading Metrics
- Time to first dashboard render after `docker compose up` (target: < 3 min including discovery).
- Number of apps auto-detected without manual config (target: >= 80% of supported detectors).
- Poll-to-dashboard latency (target: < 30 s for a 20-guest cluster).

### Lagging Metrics
- Percentage of guests with "unknown" status after 24 h of running (target: < 10%).
- User-reported false positives on version mismatch (target: < 5%).

---

## 4. Functional Requirements -- MVP (Phase 1, Read-Only)

### FR-1: Proxmox API Connection
- Connect to one or more Proxmox VE nodes via REST API.
- Auth via API token (`PVEAPIToken=USER@REALM!TOKENID=SECRET`).
- Endpoint, token ID, and secret configurable via environment variables.
- **Acceptance criteria:** App starts, authenticates, and returns cluster/node info within 5 s. Connection failure surfaces a clear error on the dashboard.

### FR-2: Guest Discovery
- Poll Proxmox API (`GET /api2/json/nodes/{node}/lxc` and optionally `/qemu`) on a configurable interval (default: 60 s).
- Persist discovered guests in an in-memory store (SQLite optional for persistence across restarts).
- Track: VMID, name, type (LXC/VM), status (running/stopped), tags, network interfaces.
- **Acceptance criteria:** All running LXC containers appear in the dashboard within one polling cycle. Stopped guests appear with a "stopped" badge. VM discovery is toggled via `PROXMON_DISCOVER_VMS=true`.

### FR-3: Application Detection per Guest
- For each discovered guest, attempt detection in priority order:
  1. **Proxmox tags** -- a tag like `app:sonarr` explicitly maps guest to detector.
  2. **Guest name matching** -- hostname/name matched against registered detector names (fuzzy, case-insensitive).
  3. **Docker container inspection** -- SSH into guest, run `docker ps --format json`, match image names to known detectors.
- Detection runs after each discovery poll.
- **Acceptance criteria:** A guest tagged `app:sonarr` is detected as Sonarr. A guest named `plex-server` is detected as Plex. A guest running a Docker container with image `linuxserver/sonarr:latest` is detected as Sonarr.

### FR-4: Installed Version Detection
- Each detector plugin queries the guest's local API, parses a config file, or runs a CLI command to extract the installed version string.
- Communication to guest apps happens over the guest's LAN IP (resolved from Proxmox API network info or configurable override).
- Timeout per probe: 5 s (configurable).
- **Acceptance criteria:** For each supported app, the installed version is retrieved and displayed. On timeout or error, status is "unknown" with the error reason logged.

### FR-5: Latest Upstream Version Lookup
- Query GitHub Releases API (`GET /repos/{owner}/{repo}/releases/latest`) for each supported app.
- Cache results with a configurable TTL (default: 1 h).
- Support optional GitHub personal access token to avoid rate limits (unauthenticated limit: 60 req/h).
- For apps not on GitHub, detector plugin specifies an alternative version source.
- **Acceptance criteria:** Latest version is fetched and cached. Cache hit does not make a network call. Rate-limit errors are logged and surfaced as "latest version unavailable."

### FR-6: Dashboard
- Single-page table view with columns: Guest Name, VMID, Type, App, Installed Version, Latest Version, Status, Last Checked.
- Status values: `up-to-date` (green), `outdated` (amber), `unknown` (gray), `stopped` (dark gray).
- Sortable and filterable by status, app name, guest type.
- Auto-refreshes on each poll cycle via polling or SSE.
- **Acceptance criteria:** Dashboard loads in < 1 s (excluding initial discovery). Filtering by "outdated" shows only outdated guests. Timestamp shows relative time ("3 min ago").

### FR-7: Manual Refresh
- "Refresh Now" button triggers an immediate full discovery + detection cycle.
- Button is disabled with a spinner while the cycle runs.
- **Acceptance criteria:** Clicking refresh triggers a new cycle; dashboard updates within 30 s for a 20-guest cluster. Button re-enables after completion.

### FR-8: Per-App Detail Page
- Clicking an app row navigates to a detail view.
- Shows: guest metadata (VMID, IP, type, tags), app name, installed version, latest version, version history (if tracked), detection method used, last check timestamp, raw probe response (collapsible).
- **Acceptance criteria:** Detail page renders all listed fields. Back navigation returns to the dashboard with preserved filter state.

### FR-9: Configuration
- All settings via environment variables (12-factor).
- Required: `PROXMON_API_URL`, `PROXMON_API_TOKEN_ID`, `PROXMON_API_TOKEN_SECRET`.
- Optional: `PROXMON_POLL_INTERVAL` (default 60), `PROXMON_DISCOVER_VMS` (default false), `PROXMON_GITHUB_TOKEN`, `PROXMON_SSH_KEY_PATH`, `PROXMON_SSH_USER` (default root), `PROXMON_LOG_LEVEL` (default info).
- **Acceptance criteria:** App starts with only the three required vars set. Missing required vars prevent startup with a descriptive error.

### FR-10: Read-Only Mode Enforcement
- The backend must never issue PUT, POST, DELETE, or PATCH requests to the Proxmox API.
- The backend must never execute mutating commands on guest systems (write, install, restart).
- SSH sessions, if used, execute only read commands (`docker ps`, `cat`, version queries).
- **Acceptance criteria:** Code review confirms no mutating HTTP methods to Proxmox. SSH command whitelist is enforced programmatically.

---

## 5. Functional Requirements -- Phase 2 (Future, Write Mode)

These are out of scope for MVP but inform the architecture.

### FR-P2-1: Update Button
- Per-app "Update" action triggers the app-specific update handler.
- Requires explicit user confirmation modal.

### FR-P2-2: Pre-Update Snapshot
- Before executing an update, create a Proxmox snapshot of the guest via `POST /api2/json/nodes/{node}/{type}/{vmid}/snapshot`.
- Snapshot name format: `proxmon-pre-update-{timestamp}`.

### FR-P2-3: App-Specific Update Handlers
- Plugin interface extended with an `update()` method.
- Each handler defines how to update the app (e.g., `apt upgrade`, Docker image pull, API call).

### FR-P2-4: Audit Log
- All write actions logged with: timestamp, user (future auth), action, target guest, result.
- Stored in SQLite. Viewable in the dashboard.

### FR-P2-5: Health Checks
- Post-update health probe (HTTP 200 check on app endpoint).
- Automatic snapshot rollback if health check fails within N minutes.

### FR-P2-6: Notifications
- Webhook / ntfy / email alerts when new upstream versions are detected.

---

## 6. Non-Functional Requirements

### Performance
- Full discovery + detection cycle for 50 guests completes in < 60 s.
- Dashboard API response (cached data) in < 100 ms (p99).
- Frontend initial load (gzipped bundle) < 500 KB.

### Scale
- Designed for single-cluster homelabs: 1-5 nodes, up to 100 guests.
- No horizontal scaling required. Single-process backend.

### SLOs / SLAs
- Internal tool; no formal SLA.
- Target availability: app stays up as long as the host Docker daemon is running (restart policy: `unless-stopped`).
- Data freshness SLO: dashboard data no older than 2x the configured poll interval.

### Privacy
- No telemetry, no external data collection, no cloud calls except GitHub API for version checks.
- Proxmox API tokens and SSH keys stored only in environment variables or Docker secrets; never logged, never exposed via API.
- Guest IPs and hostnames are considered internal data; API responses are not access-controlled (MVP assumes trusted LAN).

### Security
- Proxmox API token should use a least-privilege role (`PVEAuditor` is sufficient for read-only).
- SSH key used for Docker inspection should be a dedicated key with restricted `authorized_keys` entry on guests (`command=` restriction recommended in docs).
- TLS verification for Proxmox API configurable (`PROXMON_VERIFY_SSL`, default true). Self-signed cert fingerprint pinning supported.
- No inbound ports required beyond the dashboard HTTP port (default 8080).

### Observability
- Structured JSON logging (Python `structlog`).
- Log levels: DEBUG (probe raw responses), INFO (cycle summaries), WARNING (timeouts, unknown apps), ERROR (connection failures).
- `/api/health` endpoint returns: uptime, last poll timestamp, guest count, error count.
- Optional Prometheus metrics endpoint (`/metrics`): `proxmon_guests_total`, `proxmon_outdated_total`, `proxmon_poll_duration_seconds`, `proxmon_probe_errors_total`.

---

## 7. Plugin Architecture Spec

### Detector Interface

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class AppVersion:
    installed: str | None       # semver or raw string
    latest: str | None          # semver or raw string
    status: str                 # "up-to-date" | "outdated" | "unknown"
    metadata: dict              # app-specific extra info

class BaseDetector(ABC):
    """Every detector plugin must implement this interface."""

    name: str                           # e.g., "sonarr"
    display_name: str                   # e.g., "Sonarr"
    github_repo: str | None             # e.g., "Sonarr/Sonarr" for upstream lookup
    aliases: list[str]                  # alternative name matches
    default_port: int                   # e.g., 8989

    @abstractmethod
    async def detect_installed_version(self, host: str, port: int) -> str | None:
        """Query the guest to determine the installed version."""
        ...

    async def detect_latest_version(self) -> str | None:
        """Override if not using GitHub Releases (default impl uses github_repo)."""
        ...

    def match_docker_image(self, image: str) -> bool:
        """Return True if a Docker image string matches this app."""
        ...
```

### Detector Registry

- Detectors are registered via a `DETECTORS` dict in `proxmon/detectors/__init__.py`.
- Adding a new detector = adding a single Python file in `proxmon/detectors/` and registering it.
- No dynamic plugin loading in MVP; all detectors ship with the app.

### Supported Detectors (MVP)

| App           | Detection Method                        | GitHub Repo                  | Default Port |
|---------------|-----------------------------------------|------------------------------|--------------|
| Sonarr        | `GET /api/v3/system/status` (API key)   | Sonarr/Sonarr                | 8989         |
| Radarr        | `GET /api/v3/system/status` (API key)    | Radarr/Radarr                | 7878         |
| Bazarr        | `GET /api/v3/system/status`              | morpheus65535/bazarr          | 6767         |
| Prowlarr      | `GET /api/v3/system/status` (API key)    | Prowlarr/Prowlarr            | 9696         |
| Plex          | `GET /identity` (XML)                    | plexinc/pms-docker           | 32400        |
| Immich        | `GET /api/server/about`                  | immich-app/immich            | 2283         |
| Gitea         | `GET /api/v1/version`                    | go-gitea/gitea               | 3000         |
| qBittorrent   | `GET /api/v2/app/version`                | qbittorrent/qBittorrent      | 8080         |
| SABnzbd       | `GET /api?mode=version`                  | sabnzbd/sabnzbd              | 8085         |
| Traefik       | `GET /api/version`                       | traefik/traefik              | 8080         |
| Caddy         | `GET /config/` (admin API)               | caddyserver/caddy            | 2019         |
| ntfy          | `GET /v1/info`                           | binwiederhier/ntfy           | 80           |
| Generic Docker| Parse image tag from `docker ps`         | per-image                    | N/A          |

### Detector Configuration

- Per-guest overrides via environment or future config file:
  - `PROXMON_APP_{VMID}_PORT` -- override default port.
  - `PROXMON_APP_{VMID}_API_KEY` -- provide API key for arr-stack apps.
- Proxmox tags can encode port/key: `app:sonarr`, `port:8989`, `apikey:xyz`.

---

## 8. API Contract Sketch

Base URL: `http://<host>:8080/api`

### Endpoints

| Method | Path                     | Description                       | Response Shape                          |
|--------|--------------------------|-----------------------------------|-----------------------------------------|
| GET    | `/health`                | Health check                      | `{ uptime, last_poll, guest_count }`    |
| GET    | `/guests`                | List all discovered guests        | `[Guest]`                               |
| GET    | `/guests/{vmid}`         | Single guest detail               | `Guest`                                 |
| POST   | `/refresh`               | Trigger immediate poll cycle      | `{ status: "started" }`                |
| GET    | `/config`                | Current config (secrets redacted) | `Config`                                |

### Guest Object

```json
{
  "vmid": 101,
  "name": "sonarr",
  "type": "lxc",
  "status": "running",
  "tags": ["app:sonarr"],
  "ip": "10.0.0.101",
  "app": {
    "name": "Sonarr",
    "detector": "sonarr",
    "detection_method": "tag",
    "installed_version": "4.0.14.2939",
    "latest_version": "4.0.15.3012",
    "update_status": "outdated",
    "last_checked": "2026-03-08T12:34:56Z",
    "metadata": {
      "branch": "main",
      "runtime": "dotnet"
    }
  }
}
```

### Error Responses

- `500` with `{ "error": "message" }` for internal errors.
- `502` with `{ "error": "proxmox_unreachable" }` when Proxmox API is down.
- `404` for unknown VMID.

---

## 9. Scope

### In Scope (MVP)
- Proxmox API read-only integration
- LXC discovery (VM discovery opt-in)
- 12+ app detectors (see table above)
- GitHub-based upstream version lookup
- Single-page dashboard with status table
- Per-app detail view
- Manual refresh
- Docker Compose deployment
- Structured logging

### Out of Scope (MVP)
- Authentication / authorization (trusted LAN assumption)
- Write operations to Proxmox or guests
- Notifications / alerts
- Update execution
- Multi-cluster support
- Mobile-optimized UI
- Persistent storage (in-memory is acceptable; SQLite optional)
- Automatic remediation

---

## 10. Rollout Plan

### Phase 1a: Core (Weeks 1-2)
- Proxmox API client + guest discovery
- Detector plugin framework + 3 detectors (Sonarr, Plex, generic Docker)
- GitHub version lookup with caching
- Minimal API (`/health`, `/guests`, `/refresh`)
- Backend integration tests with mocked Proxmox API

### Phase 1b: Dashboard (Weeks 3-4)
- React dashboard: table view, filtering, sorting
- Per-app detail page
- Manual refresh button
- Remaining detectors (all 12+)
- Docker Compose with multi-stage build
- End-to-end smoke test against a real Proxmox instance

### Guardrails
- **Rate limit on GitHub API:** Cache aggressively; log warnings at 80% of rate limit budget. If token not provided, limit to 30 unique repos per hour (leaving headroom).
- **SSH safety:** All SSH commands executed via a whitelist. No shell expansion. Timeout of 10 s per session.
- **Proxmox API safety:** HTTP client configured with only GET method allowed. Any non-GET call raises a hard exception in the client layer.
- **Polling backoff:** If Proxmox API returns 5xx, back off exponentially (1 s, 2 s, 4 s, ... up to 5 min).

### Kill Switch
- `PROXMON_ENABLED=false` environment variable stops all polling and probing. Dashboard shows a static "paused" banner.
- `PROXMON_SSH_ENABLED=false` disables all SSH-based detection (Docker inspection) without stopping the rest.
- Per-detector disable: `PROXMON_DETECTOR_{NAME}_ENABLED=false`.

---

## 11. Risks & Mitigations

| Risk                                               | Likelihood | Impact | Mitigation                                                        |
|----------------------------------------------------|------------|--------|-------------------------------------------------------------------|
| GitHub API rate limiting (unauthenticated: 60/h)   | High       | Medium | Aggressive caching (1 h TTL); support PAT; batch lookups.         |
| SSH access denied on guests                        | Medium     | Low    | Graceful fallback; mark as "unknown"; log clearly.                |
| Proxmox API token with excessive privileges         | Low        | High   | Document least-privilege setup (`PVEAuditor` role). Warn in logs if token has write perms (if detectable). |
| Self-signed Proxmox certs cause TLS errors          | High       | Low    | `PROXMON_VERIFY_SSL` toggle; document fingerprint pinning.        |
| App API changes break detectors                     | Medium     | Medium | Each detector has a version field; log parse failures; "unknown" fallback. |
| Polling storm with many guests                      | Low        | Medium | Concurrent probes capped at 10 (configurable semaphore).          |
| Guest IP resolution fails (DHCP, no agent)          | Medium     | Medium | Allow manual IP override per VMID; try Proxmox agent, ARP, DNS.  |

---

## 12. Open Questions

1. **Should we support Proxmox clusters or single-node only in MVP?** Recommendation: single-node MVP, cluster in Phase 1.5 (requires iterating over `/nodes`).
2. **Should detector API keys be stored in Proxmox guest tags or in Proxmon config?** Tags are convenient but leak secrets in the Proxmox UI. Recommendation: environment variables with VMID-keyed naming.
3. **Should we use QEMU Guest Agent for VM IP resolution instead of SSH?** Yes, as a preferred method with SSH as fallback.
4. **SQLite for persistence or pure in-memory?** Recommendation: start in-memory; add optional SQLite for version history tracking before Phase 1 release.
5. **Should the frontend poll the API or use SSE for live updates?** Recommendation: start with polling (simpler); SSE in a fast-follow if latency complaints arise.

---

## 13. Project Structure (Reference)

```
proxmon/
  backend/
    proxmon/
      __init__.py
      main.py                 # FastAPI app entry
      config.py               # Env var parsing, validation
      models.py               # Pydantic models (Guest, AppVersion, etc.)
      proxmox_client.py       # Proxmox API client (read-only)
      discovery.py            # Guest discovery + orchestration
      github_client.py        # GitHub Releases API client w/ cache
      ssh_client.py           # SSH command executor w/ whitelist
      detectors/
        __init__.py            # Registry
        base.py                # BaseDetector ABC
        sonarr.py
        radarr.py
        bazarr.py
        prowlarr.py
        plex.py
        immich.py
        gitea.py
        qbittorrent.py
        sabnzbd.py
        traefik.py
        caddy.py
        ntfy.py
        docker_generic.py
    tests/
      ...
  frontend/
    src/
      App.tsx
      components/
        Dashboard.tsx
        GuestRow.tsx
        DetailPage.tsx
        RefreshButton.tsx
      api/
        client.ts
    ...
  docker-compose.yml
  Dockerfile
```
