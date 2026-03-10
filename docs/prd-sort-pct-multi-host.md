# PRD: Dashboard Sorting, pct exec Version Detection, Multi-Host Support

**Author:** proxmon team
**Date:** 2026-03-09
**Status:** Draft -- awaiting review
**Stakeholders:** Self-hosted / homelab users running Proxmox clusters

---

## Context & Why Now

proxmon monitors Proxmox LXC/VM guests, detects running apps, and compares installed vs. latest versions. Three gaps limit its usefulness today:

1. **No column sorting** -- users with 20+ guests cannot quickly find outdated apps or locate a specific guest without scrolling/searching.
2. **SSH-only version detection** -- getting installed versions via SSH requires key/password setup inside every LXC. Proxmox already provides `pct exec` which runs commands inside containers without any guest-side SSH config.
3. **Single-host limitation** -- the settings model stores one `proxmox_host` / `proxmox_node` / token. Users running 2+ Proxmox nodes (common in homelab clusters) must pick one or run separate proxmon instances.

All three are the top friction points reported by early users and block adoption in multi-node homelab setups.

---

## Users & Jobs-to-be-Done

| User | JTBD |
|------|------|
| Homelab admin (single node) | "I want to see at a glance which guests are outdated, sorted by status or app name." |
| Homelab admin (single node, no SSH) | "I want version detection without configuring SSH keys inside every LXC." |
| Homelab admin (cluster) | "I want one dashboard for all my Proxmox nodes so I stop context-switching between hosts." |

---

## Business Goals & Success Metrics

| Goal | Leading metric | Lagging metric |
|------|---------------|----------------|
| Reduce time to find outdated guests | Column sort usage > 50% of sessions (frontend telemetry, if added) | Fewer manual checks reported in GitHub issues |
| Lower setup friction for version detection | % of guests with installed_version != null increases after pct exec rollout | Reduction in SSH-related issues/questions on GitHub |
| Support multi-node clusters | Number of configured hosts > 1 per instance (settings data) | New stars / adoption from cluster users |

---

## Feature 1: Dashboard Column Sorting

### Functional Requirements

| # | Requirement | Acceptance Criteria |
|---|------------|-------------------|
| F1.1 | Clicking a column header sorts the table by that column ascending; clicking again toggles descending; clicking a third time returns to default (unsorted). | Given the dashboard table, when a user clicks "Guest Name" header, rows re-order alphabetically A-Z. Clicking again reverses to Z-A. Clicking a third time returns to the original order. |
| F1.2 | A visual arrow indicator (up/down chevron) appears on the active sort column. No arrow on inactive columns. | Given sorting is active on "Installed" column descending, the "Installed" header shows a down-arrow and no other header shows an arrow. |
| F1.3 | Sortable columns: Guest Name, Type, App, Installed Version, Latest Version, Status (update_status), Last Checked. "Actions" column is NOT sortable. | All listed columns respond to click; "Actions" does not. |
| F1.4 | Sort state persists in URL search params (`?sort=name&dir=asc`) so it survives page refresh and is shareable. | Given sort by "App" descending, the URL contains `sort=app_name&dir=desc`. Reloading the page preserves the sort. |
| F1.5 | Sorting applies AFTER filtering. If a filter is active, only filtered rows are sorted. | Given filter "outdated" is active and sort is "Guest Name" ascending, only outdated guests appear, sorted A-Z. |
| F1.6 | Null/empty values sort last regardless of direction. | Guests with no app_name appear at the bottom when sorting by App ascending or descending. |
| F1.7 | Mobile card view does NOT show sort controls (sorting is desktop-table only). | On screens < md breakpoint, no sort UI is rendered. |

### Technical Notes

- State: add `sortColumn` and `sortDirection` to Dashboard component, synced to `useSearchParams`.
- Comparator: use `String.localeCompare` for text, date comparison for Last Checked, semver-aware compare for version columns (fall back to string if not parseable).
- No backend changes needed; sorting is client-side on the already-fetched guest list.

### Out of Scope

- Server-side sorting / pagination (guest count is typically < 200).
- Sorting the mobile card view.
- Multi-column sort.

---

## Feature 2: Version Discovery via `pct exec`

### Functional Requirements

| # | Requirement | Acceptance Criteria |
|---|------------|-------------------|
| F2.1 | Add a new version-detection strategy: run `pct exec <vmid> -- <version_cmd>` on the Proxmox host via SSH. | Given an LXC guest 101 with detector "sonarr" and ssh_version_cmd configured, the backend SSHes into the Proxmox host and runs `pct exec 101 -- <cmd>`, returning the version string. |
| F2.2 | New global setting `version_detect_method` with values: `pct_first` (default), `ssh_first`, `ssh_only`, `pct_only`. | The Settings UI shows a dropdown for "Version detection method" with these four options. Value is persisted in SQLite. |
| F2.3 | `pct_first`: try pct exec; if it fails or returns empty, fall back to direct SSH into guest. `ssh_first`: try SSH; fall back to pct exec. `*_only`: no fallback. | Given `pct_first` and pct exec returns empty output, the system falls back to SSH and logs the fallback. |
| F2.4 | pct exec commands go through the same safety validation as SSH version commands (`_is_version_cmd_safe`). | A version_cmd containing `;` or `|` is rejected before execution, and a WARNING is logged. |
| F2.5 | pct exec requires a working SSH connection to the Proxmox host itself (not the guest). The Proxmox host SSH credentials are the global SSH settings already in config. | Given global SSH username=root and ssh_key_path set, pct exec connects to `proxmox_host` IP (parsed from URL) on port 22. |
| F2.6 | pct exec only applies to LXC guests (type=lxc). VMs always use SSH or HTTP probe. | Given a VM guest, pct exec is never attempted regardless of the detection method setting. |
| F2.7 | The guest detail API response includes a new field `version_detect_method` indicating which method succeeded ("http", "ssh", "pct_exec"). | GET /api/guests/101 returns `"version_detect_method": "pct_exec"` when pct exec was used. |

### Technical Design

- **Where**: `discovery.py` `_check_version()` method. After the HTTP probe, insert pct exec logic alongside existing SSH version cmd logic.
- **SSH to Proxmox host**: reuse `SSHClient._execute_sync()` targeting the Proxmox host IP (extracted from `settings.proxmox_host` URL). The command template: `pct exec {vmid} -- {version_cmd}`.
- **Command construction**: the vmid comes from `guest.id` (already validated as a Proxmox VMID). The version_cmd comes from the detector's `ssh_version_cmd` config.
- **New fields**: add `version_detect_method: str = "pct_first"` to `Settings`; add `version_detect_method: str | None = None` to `GuestInfo` / `GuestDetail`.

### Security Considerations

- pct exec runs as root on the Proxmox host. The same `_is_version_cmd_safe()` validation applies.
- The VMID is always an integer string from Proxmox API -- validate with `vmid.isdigit()` before interpolation.
- No new network exposure; this reuses the existing SSH channel to the Proxmox host.

### Out of Scope

- Using the Proxmox API (`POST /nodes/{node}/lxc/{vmid}/exec`) instead of SSH + pct exec. The API exec endpoint is not available on all PVE versions and requires websocket handling.
- Per-app override of detection method (global setting only for v1).

---

## Feature 3: Multiple Proxmox Hosts

### Functional Requirements

| # | Requirement | Acceptance Criteria |
|---|------------|-------------------|
| F3.1 | Replace single Proxmox host config with an array of host objects, each containing: `id` (user label, e.g. "pve1"), `proxmox_host`, `proxmox_token_id`, `proxmox_token_secret`, `proxmox_node`, `verify_ssl`. | Settings UI shows a list of Proxmox hosts with add/remove buttons. Each host has its own connection fields. |
| F3.2 | Discovery runs against ALL configured hosts in parallel. Each host produces its own guest list; results are merged. | Given 2 hosts configured, discovery finds 5 guests on pve1 and 8 on pve2; the dashboard shows 13 guests total. |
| F3.3 | Guest IDs are namespaced by host to avoid collisions: `{host_id}:{vmid}` (e.g. "pve1:101"). | Two guests with VMID 101 on different hosts appear as separate rows with IDs "pve1:101" and "pve2:101". |
| F3.4 | The dashboard table includes a new "Host" column showing the host label. | The "Host" column displays "pve1" or "pve2" for each guest. This column is sortable (Feature 1). |
| F3.5 | The filter bar gains a host filter dropdown (all / pve1 / pve2 / ...). | Selecting "pve2" from the host dropdown shows only pve2 guests. |
| F3.6 | The "Test Connection" button in Settings tests each host independently and shows per-host results. | Given 2 hosts, clicking "Test Connection" on pve1 shows success/failure for pve1 only. |
| F3.7 | Backward compatibility: existing single-host config auto-migrates to the new array format with `id = "default"`. | On first startup after upgrade, the existing host config becomes `proxmox_hosts: [{ id: "default", ... }]`. No user action needed. |
| F3.8 | Minimum 1 host required. Maximum 10 hosts (guard against misconfiguration). | Attempting to save with 0 hosts returns a 422 error. Attempting to add an 11th host is blocked in the UI. |

### Technical Design

- **Config schema change**: replace `proxmox_host`, `proxmox_token_id`, `proxmox_token_secret`, `proxmox_node`, `verify_ssl` with `proxmox_hosts: list[ProxmoxHostConfig]` in `Settings` and `SettingsSaveRequest`.
- **New model** `ProxmoxHostConfig(BaseModel)`: `id`, `proxmox_host`, `proxmox_token_id`, `proxmox_token_secret`, `proxmox_node`, `verify_ssl`.
- **ProxmoxClient**: parameterize per-host. `DiscoveryEngine` instantiates one `ProxmoxClient` per host and runs `list_guests()` concurrently with `asyncio.gather()`.
- **GuestInfo**: add `host_id: str` field. `GuestInfo.id` becomes `"{host_id}:{vmid}"`.
- **GuestSummary / GuestDetail**: add `host_id: str` and `host_label: str` fields.
- **Migration**: `ConfigStore._migrate_multi_host()` checks for old flat keys and wraps them into `proxmox_hosts: [...]`.
- **Settings UI**: `ProxmoxHostsSection` component with accordion-style per-host forms. Add/Remove buttons. Each host has its own "Test Connection".
- **pct exec (Feature 2 interaction)**: pct exec targets the correct Proxmox host for each guest based on `host_id`.

### Data Migration

```
Before (single host):
{
  "proxmox_host": "https://192.168.1.10:8006",
  "proxmox_token_id": "root@pam!monitor",
  "proxmox_token_secret": "xxx",
  "proxmox_node": "pve",
  "verify_ssl": false,
  ...
}

After (multi-host):
{
  "proxmox_hosts": [
    {
      "id": "default",
      "proxmox_host": "https://192.168.1.10:8006",
      "proxmox_token_id": "root@pam!monitor",
      "proxmox_token_secret": "xxx",
      "proxmox_node": "pve",
      "verify_ssl": false
    }
  ],
  ...
}
```

### Out of Scope

- Per-host SSH credentials (use global SSH config for all hosts in v1).
- Per-host poll intervals.
- Cluster auto-discovery (user must manually add each node).
- Guest live-migration tracking across hosts.

---

## Non-Functional Requirements

| Category | Requirement |
|----------|------------|
| **Performance** | Column sorting must complete in < 50ms for 200 guests (client-side JS). Discovery cycle across 10 hosts must complete within 2x single-host time (parallel execution). |
| **Scale** | Support up to 10 Proxmox hosts, 500 total guests. Beyond that, performance is best-effort. |
| **SLO** | Discovery cycle completes within `poll_interval_seconds` (default 300s). If any single host is unreachable, other hosts still complete normally. |
| **Privacy** | No new PII collected. Proxmox tokens masked in API responses (existing `_keep_or_replace` pattern). Multi-host tokens each get the same masking treatment. |
| **Security** | pct exec commands validated with `_is_version_cmd_safe()`. VMID validated as digit-only before interpolation. No new network ports opened. API key auth (existing `_require_api_key`) applies to all new/modified endpoints. |
| **Observability** | Log per-host discovery timing at INFO level. Log pct exec attempts and fallbacks at INFO. Log sort usage only if frontend telemetry is added (not required for v1). |
| **Backward Compat** | Single-host configs auto-migrate. Existing API responses (`/api/guests`) add new fields (`host_id`) but do not remove existing fields. Frontend gracefully handles missing `host_id` (old backend). |

---

## Rollout Plan

| Phase | Scope | Guardrails |
|-------|-------|-----------|
| **Phase 1** | Feature 1 (column sorting) -- frontend only, zero backend risk | Ship behind no flag; purely additive UI. Revert = single frontend commit. |
| **Phase 2** | Feature 2 (pct exec) -- backend + settings UI | Default to `pct_first`. Global setting `version_detect_method` = kill-switch: set to `ssh_only` to fully disable pct exec path. Log all pct exec attempts at INFO. |
| **Phase 3** | Feature 3 (multi-host) -- largest change, schema migration | Auto-migration is idempotent and preserves existing data. If migration fails, fall back to reading legacy flat keys (code path kept for 2 releases). Add `PROXMON_MULTI_HOST_ENABLED=true` env var gate for early testing; remove gate once stable. |

### Kill Switches

- **Feature 2**: set `version_detect_method: ssh_only` in Settings to completely bypass pct exec.
- **Feature 3**: set `PROXMON_MULTI_HOST_ENABLED=false` env var to revert to single-host mode during rollout.

---

## Risks & Mitigations

| Risk | Impact | Likelihood | Mitigation |
|------|--------|-----------|-----------|
| pct exec not available (older PVE, or user lacks root on host) | Version detection fails silently | Medium | Fallback to SSH (default `pct_first`); clear error message in logs |
| Guest ID collision after multi-host migration (e.g., version history keyed on old "101" vs new "default:101") | Lost version history for existing guests | High (on first upgrade) | Migration maps old IDs to `default:{vmid}`; version history lookup checks both old and new ID formats for one cycle |
| Config migration corrupts settings | App becomes unconfigured | Low | Migration is read-then-write with rollback on error; backup of old JSON blob logged before overwrite |
| Frontend sorting slow with many guests | Janky UI | Low | 500 rows sorts in < 10ms in modern browsers; no risk at expected scale |
| Multi-host increases discovery time linearly | Polls exceed interval | Medium | Parallel host discovery. Log warning if cycle > 80% of poll_interval. |

---

## Open Questions

1. **Per-host SSH credentials (Feature 3)**: Should each Proxmox host have its own SSH username/key for pct exec, or is global SSH config sufficient for v1?
   - **Recommendation**: Global SSH for v1. Add per-host SSH in a follow-up if users request it.

2. **Proxmox API exec endpoint**: PVE 7.2+ supports `POST /nodes/{node}/lxc/{vmid}/status/exec`. Should we prefer this over SSH + pct exec?
   - **Recommendation**: No for v1. The API exec requires websocket handling and is not universally available. SSH + pct exec is simpler and more portable.

3. **Guest ID format**: `{host_id}:{vmid}` introduces a breaking change for any external tooling consuming `/api/guests`. Should we version the API?
   - **Recommendation**: No formal versioning. Document the change in release notes. The `host_id` field is always present; consumers can split on `:` if needed.

4. **Max hosts limit**: Is 10 hosts sufficient, or should it be configurable?
   - **Recommendation**: Hard-cap at 10 for v1. Revisit if a real user hits the limit.
