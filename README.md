# proxmon

Self-hosted web app that monitors Proxmox LXC containers and VMs, auto-detects installed applications, compares installed versions against the latest GitHub releases, and displays an update-status dashboard. Zero agent installation required -- all detection is API and SSH based.

## Quick Start

```bash
# 1. Clone and configure
git clone <repo-url> proxmon && cd proxmon
cp backend/.env.example .env

# 2. Edit .env with your Proxmox credentials
#    Required: PROXMOX_HOST, PROXMOX_TOKEN_ID, PROXMOX_TOKEN_SECRET, PROXMOX_NODE

# 3. Launch
docker compose up -d

# 4. Open dashboard
open http://localhost:3000
```

## Configuration

All settings via environment variables (`.env` file):

| Variable | Required | Default | Description |
|---|---|---|---|
| `PROXMOX_HOST` | Yes | -- | Proxmox API URL (e.g., `https://192.168.1.10:8006`) |
| `PROXMOX_TOKEN_ID` | Yes | -- | API token ID (e.g., `proxmon@pve!monitor`) |
| `PROXMOX_TOKEN_SECRET` | Yes | -- | API token secret |
| `PROXMOX_NODE` | Yes | -- | Proxmox node name (e.g., `pve`) |
| `POLL_INTERVAL_SECONDS` | No | `300` | Seconds between discovery cycles |
| `DISCOVER_VMS` | No | `false` | Also discover QEMU VMs |
| `VERIFY_SSL` | No | `false` | Verify Proxmox TLS certificate |
| `SSH_USERNAME` | No | `root` | SSH user for Docker inspection |
| `SSH_KEY_PATH` | No | -- | Path to SSH private key |
| `SSH_PASSWORD` | No | -- | SSH password (alternative to key) |
| `SSH_ENABLED` | No | `true` | Enable SSH-based Docker detection |
| `GITHUB_TOKEN` | No | -- | GitHub PAT for higher API rate limits |
| `LOG_LEVEL` | No | `info` | Logging level (debug/info/warning/error) |
| `PROXMON_ENABLED` | No | `true` | Master switch for polling |

## Supported Apps

| App | Detection | Version Endpoint | GitHub Repo |
|---|---|---|---|
| Sonarr | name/tag/docker | `/api/v3/system/status` | Sonarr/Sonarr |
| Radarr | name/tag/docker | `/api/v3/system/status` | Radarr/Radarr |
| Bazarr | name/tag/docker | `/api/bazarr/api/v1/system/status` | morpheus65535/bazarr |
| Prowlarr | name/tag/docker | `/api/v1/system/status` | Prowlarr/Prowlarr |
| Plex | name/tag/docker | `/identity` (XML) | plexinc/pms-docker |
| Immich | name/tag/docker | `/api/server/about` | immich-app/immich |
| Gitea | name/tag/docker | `/api/v1/version` | go-gitea/gitea |
| qBittorrent | name/tag/docker | `/api/v2/app/version` | qbittorrent/qBittorrent |
| SABnzbd | name/tag/docker | `/api?mode=version` | sabnzbd/sabnzbd |
| Traefik | name/tag/docker | `/api/version` | traefik/traefik |
| Caddy | name/tag/docker | Admin API (`:2019`) | caddyserver/caddy |
| ntfy | name/tag/docker | `/v1/info` | binwiederhier/ntfy |
| Docker (generic) | docker ps | Image tag parsing | N/A |

## Adding a Custom Detector

1. Create `backend/app/detectors/myapp.py`:

```python
from app.detectors.base import BaseDetector

class MyAppDetector(BaseDetector):
    name = "myapp"
    display_name = "My App"
    github_repo = "owner/repo"       # or None
    aliases = ["myapp", "my-app"]
    default_port = 8080
    docker_images = ["myapp", "org/myapp"]

    async def get_installed_version(self, host: str, port: int | None = None) -> str | None:
        port = port or self.default_port
        try:
            resp = await self._http_get(f"http://{host}:{port}/api/version")
            if resp.status_code == 200:
                return resp.json().get("version")
        except Exception:
            pass
        return None
```

2. Register in `backend/app/detectors/registry.py`:

```python
from app.detectors.myapp import MyAppDetector
# Add to ALL_DETECTORS list:
ALL_DETECTORS.append(MyAppDetector())
```

3. Rebuild and restart.

## Development Setup

### Backend

```bash
cd backend
uv sync --all-extras
cp .env.example .env  # edit with your Proxmox credentials
uv run uvicorn app.main:app --reload --port 8000
uv run pytest
```

### Frontend

```bash
cd frontend
npm install
npm run dev    # starts on http://localhost:3000
```

Vite dev server proxies `/api` requests to `http://localhost:8000`.

## Architecture

```
+-----------+         +-----------+         +-----------+
|  Browser  | <-----> |  Frontend | <-----> |  Backend  |
| (React)   |  HTTP   |  (nginx)  |  proxy  |  (FastAPI)|
+-----------+         +-----------+         +-----------+
                                                  |
                                    +-------------+-------------+
                                    |             |             |
                              +-----------+ +-----------+ +-----------+
                              |  Proxmox  | |  GitHub   | |  Guests   |
                              |  API      | |  API      | |  (SSH)    |
                              +-----------+ +-----------+ +-----------+
```

**Data flow:**
1. Scheduler triggers discovery every N seconds
2. Proxmox API queried for LXC/VM list
3. Each guest matched against detector plugins (name -> tag -> Docker)
4. Matched detector queries guest's app API for installed version
5. GitHub Releases API queried for latest version (cached 1h)
6. Results stored in-memory, served via REST API
7. Frontend polls `/api/guests` every 60s

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check + stats |
| `GET` | `/api/guests` | List all guests |
| `GET` | `/api/guests/{id}` | Guest detail |
| `POST` | `/api/refresh` | Trigger immediate refresh (202) |
| `GET` | `/api/settings` | Current config (secrets masked) |

## License

MIT
