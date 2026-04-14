# PRD: Normalize Database Schema

**Status:** Draft
**Author:** Auto-generated
**Date:** 2026-04-13

---

## Context & why now

Proxmon stores all configuration in a single-row `settings` table. Four complex fields (`proxmox_hosts`, `app_config`, `guest_config`, `custom_app_defs`) are serialized as JSON TEXT blobs. Every save operation -- whether changing one host's backup storage or one guest's forced detector -- rewrites the entire row including all JSON blobs.

This causes three concrete problems today:

- **Secret masking in two code paths.** `_keep_or_replace()` runs at the scalar level AND inside JSON merge helpers (`_merge_proxmox_hosts`, `_merge_app_config`, `save_guest_config`). Every new secret field requires changes in 2-4 places. This has already caused bugs (code-review finding #5).
- **Full-replace save semantics.** `config_store.save()` requires the complete settings dict. `custom_apps.py` calls `config_store.save(data)` with the entire loaded config just to append one custom app definition. `guests.py` does the same for one guest config entry. A concurrent save from the settings page can overwrite in-flight guest config changes.
- **No surgical queries.** Listing custom apps requires loading all settings, parsing all JSON blobs, then extracting one field. Same for checking if a host exists.

The codebase has grown to 4 separate CRUD flows that all load-modify-rewrite the same JSON blobs. Normalizing now prevents compounding complexity as new features land.

---

## Users & JTBD

| User | Job to be done |
|------|---------------|
| Self-hoster (primary) | Configure and monitor Proxmox guests without worrying about config corruption |
| Developer (maintainer) | Add new config fields or secret types without multi-site masking logic |

---

## Business goals & success metrics

| Goal | Metric | Target |
|------|--------|--------|
| Eliminate full-replace saves | Lines of merge/mask code in settings.py, guests.py, custom_apps.py | Reduce by >50% |
| Uniform secret handling | Number of code paths that call `_keep_or_replace()` inside JSON merge logic | 0 (all secrets in columns) |
| No data loss on upgrade | Existing JSON blob data migrated to new tables | 100% (verified by migration test) |

Leading: migration test passes, all existing API tests pass unchanged.
Lagging: no config-related bug reports for 2 release cycles after merge.

---

## Functional requirements

### FR-1: New tables for normalized data

Create four new tables alongside the existing `settings` table.

**Acceptance criteria:**
- `proxmox_hosts` table: one row per host, columns match `ProxmoxHostConfig` fields. PK = `id` (TEXT).
- `app_config` table: one row per app override, PK = `app_name` (TEXT), columns match `AppConfig` fields.
- `guest_config` table: one row per guest override, PK = `guest_id` (TEXT), columns match `AppConfig` fields (including `forced_detector`, `version_host`).
- `custom_app_defs` table: one row per custom app, PK = `name` (TEXT), columns match `CustomAppDef` fields. List fields (`aliases`, `docker_images`, `version_keys`) stored as JSON TEXT.
- All secret columns (`token_secret`, `ssh_password`, `api_key`) are plain TEXT -- no JSON wrapping.

### FR-2: Automatic migration from JSON blobs

On startup, if new tables are empty but JSON blob columns contain data, migrate rows from blobs to tables.

**Acceptance criteria:**
- Migration runs inside a single transaction.
- After migration, JSON blob columns in `settings` are set to their empty defaults (`'[]'` or `'{}'`).
- Migration is idempotent -- running twice with data already migrated is a no-op.
- Migration logs the count of records migrated per table.

### FR-3: Per-entity CRUD methods on ConfigStore

Replace `load()` + modify + `save()` pattern with targeted methods.

**Acceptance criteria:**
- `ConfigStore` exposes: `list_hosts()`, `get_host(id)`, `upsert_host(data)`, `delete_host(id)`.
- Same pattern for `app_config`, `guest_config`, `custom_app_defs`.
- `save_settings()` only writes scalar columns (no JSON blobs).
- `load()` still returns the full unified dict (for `merge_into_settings()` compatibility) by joining across tables.
- Each CRUD method opens its own connection/transaction -- no cross-method transaction leaks.

### FR-4: Simplified secret masking

Move secret handling into ConfigStore CRUD methods.

**Acceptance criteria:**
- `upsert_host(data)` internally applies `_keep_or_replace()` for `token_secret` and `ssh_password` by reading the existing row.
- `upsert_guest_config(guest_id, data)` does the same for `api_key` and `ssh_password`.
- `upsert_app_config(app_name, data)` does the same for `api_key` and `ssh_password`.
- Route handlers no longer contain merge/mask logic for nested secrets. `_merge_proxmox_hosts()` and `_merge_app_config()` are deleted.

### FR-5: API contract preserved

**Acceptance criteria:**
- `GET /api/settings/full` returns identical JSON shape as today.
- `POST /api/settings` accepts the same `SettingsSaveRequest` body.
- `GET/PUT/DELETE /api/guests/{id}/config` unchanged.
- `GET/POST/PUT/DELETE /api/custom-apps` and `/api/custom-apps/{name}` unchanged.
- All existing frontend TypeScript types remain valid.

### FR-6: Column-level migration for new tables

New tables need the same auto-migration that scalar settings columns have.

**Acceptance criteria:**
- On startup, `_migrate_columns()` runs for each normalized table (not just `settings`).
- Adding a column to a `CREATE TABLE` definition auto-adds it via `ALTER TABLE ADD COLUMN` on next startup.

---

## Non-functional requirements

| Category | Requirement |
|----------|-------------|
| **Performance** | No regression. Single-entity CRUD should be faster (smaller writes). `load()` may add ~1ms for JOINs -- acceptable for a <10-host system. |
| **Scale** | Designed for 2-10 hosts, <50 app configs, <200 guest configs, <20 custom apps. No indexing beyond PKs needed. |
| **Data integrity** | All writes use transactions. Migration is atomic. |
| **Backward compat** | SQLite file at same path. Old containers that downgrade will see empty JSON blobs but won't crash (they'll start with defaults). |
| **Observability** | Migration logs at INFO level with row counts. CRUD operations log at DEBUG. Errors log at ERROR with full context. |
| **Testing** | Migration test: seed JSON blobs, run migration, verify new tables. Round-trip test: CRUD via ConfigStore, verify `load()` output matches. All existing `test_config_store.py` tests pass. |

---

## Scope

### In scope
- Four new SQLite tables (`proxmox_hosts`, `app_config`, `guest_config`, `custom_app_defs`)
- One-time data migration from JSON blobs to tables
- ConfigStore CRUD methods for each entity
- Refactor `settings.py`, `guests.py`, `custom_apps.py` routes to use CRUD methods
- Delete `_merge_proxmox_hosts()`, `_merge_app_config()`, and inline merge logic in `save_guest_config()`
- Update `merge_into_settings()` to read from tables instead of JSON blobs
- Tests for migration and CRUD

### Out of scope
- Changing `sessions` or `task_history` tables
- Changing frontend code or API response shapes
- Encryption at rest for secrets
- Multi-user / concurrent write locking (single-user tool)
- Renaming the database file or changing `CONFIG_DB_PATH`

---

## Schema design

```sql
CREATE TABLE IF NOT EXISTS proxmox_hosts (
    id              TEXT PRIMARY KEY,
    label           TEXT NOT NULL,
    host            TEXT NOT NULL,
    token_id        TEXT NOT NULL DEFAULT '',
    token_secret    TEXT NOT NULL DEFAULT '',
    node            TEXT NOT NULL DEFAULT '',
    ssh_username    TEXT NOT NULL DEFAULT 'root',
    ssh_password    TEXT,
    ssh_key_path    TEXT,
    pct_exec_enabled INTEGER NOT NULL DEFAULT 0,
    backup_storage  TEXT
);

CREATE TABLE IF NOT EXISTS app_config (
    app_name        TEXT PRIMARY KEY,
    port            INTEGER,
    api_key         TEXT,
    scheme          TEXT,
    github_repo     TEXT,
    ssh_version_cmd TEXT,
    ssh_username    TEXT,
    ssh_key_path    TEXT,
    ssh_password    TEXT
);

CREATE TABLE IF NOT EXISTS guest_config (
    guest_id        TEXT PRIMARY KEY,
    port            INTEGER,
    api_key         TEXT,
    scheme          TEXT,
    github_repo     TEXT,
    ssh_version_cmd TEXT,
    ssh_username    TEXT,
    ssh_key_path    TEXT,
    ssh_password    TEXT,
    forced_detector TEXT,
    version_host    TEXT
);

CREATE TABLE IF NOT EXISTS custom_app_defs (
    name            TEXT PRIMARY KEY,
    display_name    TEXT NOT NULL,
    default_port    INTEGER NOT NULL,
    scheme          TEXT NOT NULL DEFAULT 'http',
    version_path    TEXT,
    github_repo     TEXT,
    aliases         TEXT NOT NULL DEFAULT '[]',
    docker_images   TEXT NOT NULL DEFAULT '[]',
    accepts_api_key INTEGER NOT NULL DEFAULT 0,
    auth_header     TEXT,
    version_keys    TEXT NOT NULL DEFAULT '["version"]',
    strip_v         INTEGER NOT NULL DEFAULT 0
);
```

---

## Implementation plan

### Phase 1: Add tables and migration (low risk)
1. Add `CREATE TABLE` statements to `config_store.py`.
2. Add `_migrate_data_from_blobs()` -- runs after table creation, inside a transaction.
3. Add per-entity CRUD methods to `ConfigStore`.
4. Add `_migrate_columns()` coverage for new tables.
5. Write migration tests.

### Phase 2: Refactor routes to use CRUD (medium risk)
1. Refactor `custom_apps.py` -- simplest, fully self-contained CRUD.
2. Refactor `guests.py` `save_guest_config` / `delete_guest_config` / `get_guest_config`.
3. Refactor `settings.py` `save_settings` -- replace `_merge_proxmox_hosts()` and `_merge_app_config()` with `upsert_host()` / `upsert_app_config()` loops.
4. Refactor `settings.py` `get_full_settings` -- can still use `load()` which assembles from tables.
5. Delete dead merge helpers.

### Phase 3: Cleanup
1. Remove JSON blob columns from `_CREATE_TABLE` (or leave as deprecated, empty).
2. Remove `_JSON_FIELDS` from `_dict_to_params()`.
3. Verify all tests pass.

---

## Rollout plan

| Step | Action | Guardrail |
|------|--------|-----------|
| 1 | Merge to `main` | All pytest tests pass. Manual smoke test: save settings, save guest config, CRUD custom app. |
| 2 | Build and deploy via `docker compose build && docker compose up -d` | Check logs for migration output: "Migrated N hosts, N app configs, N guest configs, N custom apps". |
| 3 | Verify settings page loads correctly | `GET /api/settings/full` returns same shape as before migration. |
| 4 | Verify guest config round-trip | Save a guest config override, reload page, confirm it persists. |

**Kill switch:** If migration fails, the app still starts (JSON blobs are read as fallback in `load()` during Phase 1). To fully revert: restore the previous Docker image. The SQLite file retains both JSON blobs and new tables -- no data loss in either direction.

**Backup:** Before deploying, copy `proxmon.db` to `proxmon.db.bak`. Document this in release notes.

---

## Risks & mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Migration corrupts data | Low | High | Atomic transaction; idempotent; pre-deploy DB backup |
| `load()` performance regression from JOINs | Low | Low | <200 total rows across all tables; benchmark if needed |
| Missed code path still writes JSON blobs | Medium | Medium | grep for `"proxmox_hosts"`, `"app_config"`, `"guest_config"`, `"custom_app_defs"` in route files after refactor |
| Downgrade to old container sees empty config | Low | Medium | JSON blobs cleared only after migration confirmed; old container falls back to defaults (same as fresh install) |

---

## Open questions

1. **Should JSON blob columns be dropped or left empty?** Dropping requires `ALTER TABLE DROP COLUMN` (SQLite 3.35+, Python 3.12 ships 3.39+). Leaving them empty is simpler and allows easier rollback.
2. **Should `load()` cache the assembled dict?** Currently called on every settings read. With table JOINs it does 5 queries instead of 1. For a single-user tool this is negligible, but a simple TTL cache could be added later.
3. **Should `upsert_host()` validate required fields?** Currently validation lives in `ProxmoxHostSaveEntry` (Pydantic). Duplicating in ConfigStore adds safety but also coupling. Recommendation: keep validation in route layer only.
