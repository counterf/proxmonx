# PRD: Backup & Restore

| Field        | Value                                     |
|--------------|-------------------------------------------|
| Author       | Alysson Silva                             |
| Status       | Draft                                     |
| Created      | 2026-03-11                                |
| Last updated | 2026-03-11                                |
| Version      | 0.1                                       |
| Parent PRD   | `docs/prd.md` (proxmon MVP)               |
| Depends on   | `docs/prd-setup-ui.md` (Settings UI)      |

---

## 1. Context & Why Now

- proxmon stores all configuration in a single SQLite database (`/app/data/proxmon.db`) with a `settings` table containing one JSON blob row. This includes Proxmox host credentials, per-app API keys, SSH passwords, notification config, and per-guest overrides.
- Users who run proxmon on Docker have no built-in way to export their configuration before a volume migration, host rebuild, or version upgrade. The only option today is manually copying the raw `.db` file via `docker cp`, which requires CLI access and exposes all secrets in plaintext.
- Multi-host support (landed in `7f62cdb`) significantly increased the amount of configuration a user manages -- multiple Proxmox hosts, each with their own token secrets, SSH credentials, and per-app overrides. Manual re-entry after a rebuild is now a 10+ minute task prone to error.
- Providing a password-protected, optionally redacted export/import flow lets users safely back up, migrate, and restore their proxmon configuration through the UI.

Source -- Docker best practice: bind-mount volumes should be backed up independently; application-level export is the portable alternative.

---

## 2. Users & JTBD

| User | Job To Be Done |
|------|---------------|
| Homelab operator migrating hosts | Export my full proxmon config (with secrets) so I can import it on a new Docker host without re-entering 15+ fields. |
| Operator upgrading proxmon | Create a pre-upgrade backup so I can roll back if the new version has issues. |
| Operator sharing config (no secrets) | Export a redacted config to share with a friend or post in a forum for troubleshooting. |
| Operator restoring after data loss | Import a previously exported backup to restore proxmon to a known-good state. |

---

## 3. Business Goals & Success Metrics

### Goals
- Provide a self-service backup/restore flow entirely within the Settings UI.
- Protect exported secrets with user-supplied password encryption.
- Support forward-compatible schema versioning so future migrations are handled automatically.

### Leading Metrics
- Percentage of active users who create at least one export within 30 days of feature launch (target: >20%).
- Zero support issues related to lost configuration after upgrades.

### Lagging Metrics
- Reduction in GitHub issues tagged "config lost" or "migration help" (target: -80% within 90 days).
- Time-to-restore after a fresh install drops from 10+ minutes to under 1 minute.

---

## 4. Functional Requirements

### FR-1: Export configuration as encrypted SQLite file

- **Description**: User triggers an export that produces a password-encrypted `.db` file containing the `settings` and `backup_meta` tables.
- **Acceptance Criteria**:
  - AC-1.1: `POST /api/backup/export` with `{ include_secrets: bool, password: string }` returns a binary `.db` file with `Content-Disposition: attachment; filename="proxmon-backup-<ISO8601>.db"`.
  - AC-1.2: The exported file is encrypted with the user-supplied password using AES-256 (ZIP AES encryption via Python `zipfile` with `pyminizip` or `pyzipper`; see FR-7 for encryption strategy).
  - AC-1.3: The exported file contains a `backup_meta` table with columns: `schema_version` (INT), `proxmon_version` (TEXT), `exported_at` (TEXT, ISO 8601), `includes_secrets` (BOOL).
  - AC-1.4: The exported `settings` table is a faithful copy of the source, with one row.
  - AC-1.5: Password must be at least 8 characters; reject shorter passwords with HTTP 422.

### FR-2: Optional secret redaction on export

- **Description**: When `include_secrets` is `false`, all secret fields are replaced with empty strings before writing to the export file.
- **Acceptance Criteria**:
  - AC-2.1: Redacted fields include: `proxmox_token_secret`, `ssh_password`, `github_token`, `ntfy_token`, and within `app_config`/`guest_config`/`proxmox_hosts`: `api_key`, `ssh_password`, `token_secret`.
  - AC-2.2: `backup_meta.includes_secrets` is set to `false` in the exported file.
  - AC-2.3: No secret value appears anywhere in the exported file when redaction is enabled.

### FR-3: Import configuration from encrypted backup

- **Description**: User uploads an encrypted `.db` file with the correct password. Backend decrypts, validates, and replaces the current configuration.
- **Acceptance Criteria**:
  - AC-3.1: `POST /api/backup/import` accepts multipart form with `file` (`.db`) and `password` (string). Returns `{ success: bool, message: string }`.
  - AC-3.2: Wrong password returns HTTP 400 with `"Invalid password or corrupted file"`.
  - AC-3.3: Missing or malformed `backup_meta` table returns HTTP 400 with `"Invalid backup file: missing metadata"`.
  - AC-3.4: On success, the entire `settings` row is replaced (full overwrite, no merge).
  - AC-3.5: The backend reloads settings into the running scheduler after import (same pattern as `save_settings` in `routes.py`).
  - AC-3.6: Response includes `{ success: true, message: "Configuration restored successfully. Please reload the page." }`.

### FR-4: Schema version validation on import

- **Description**: The import endpoint compares the backup's `schema_version` against the running app's `BACKUP_SCHEMA_VERSION` constant.
- **Acceptance Criteria**:
  - AC-4.1: If backup `schema_version` equals current, import proceeds directly.
  - AC-4.2: If backup `schema_version` is older, apply registered migrations in order before importing.
  - AC-4.3: If backup `schema_version` is newer than current, reject with HTTP 400: `"Backup was created by a newer version of proxmon. Please upgrade before importing."`.
  - AC-4.4: A `BACKUP_MIGRATIONS` registry (dict mapping `from_version -> migration_fn`) exists in the backend for future use. Initially empty (current version is 1).

### FR-5: Export UI in Settings page

- **Description**: New "Backup" collapsible section at the bottom of the Settings page with export controls.
- **Acceptance Criteria**:
  - AC-5.1: Section is collapsed by default, matching the existing collapsible section pattern.
  - AC-5.2: Contains a checkbox labeled "Include secrets (API keys, SSH passwords, GitHub token)" -- unchecked by default.
  - AC-5.3: When checkbox is checked, a warning appears: "This backup will contain sensitive credentials. Keep it secure."
  - AC-5.4: Password field with a confirmation field; both must match before the Export button enables.
  - AC-5.5: "Export Backup" button triggers the download. Shows a loading spinner during the request.
  - AC-5.6: Error feedback displayed inline (e.g., password too short, server error).

### FR-6: Import UI in Settings page

- **Description**: Import controls within the same "Backup" section.
- **Acceptance Criteria**:
  - AC-6.1: File picker accepts only `.db` files.
  - AC-6.2: Password field for decryption.
  - AC-6.3: "Import Backup" button opens a confirmation dialog: "This will overwrite all current settings. This action cannot be undone. Continue?"
  - AC-6.4: On success, a toast/banner prompts: "Configuration restored. Reloading..." and the page reloads after 2 seconds.
  - AC-6.5: On failure, error message displayed inline with the specific reason (wrong password, version mismatch, invalid file).

### FR-7: Encryption strategy

- **Description**: Use AES-256 encrypted ZIP as the encryption layer (via `pyzipper` library). This avoids the `pysqlcipher3` / `sqlcipher` system dependency which is problematic in Docker Alpine images.
- **Acceptance Criteria**:
  - AC-7.1: The export endpoint creates an in-memory SQLite database, copies `settings` and `backup_meta` tables, serializes to bytes, then wraps in an AES-256 encrypted ZIP.
  - AC-7.2: The file extension remains `.db` but the actual format is an AES-encrypted ZIP containing a single `proxmon-backup.db` SQLite file.
  - AC-7.3: `pyzipper` is added to `backend/requirements.txt` (or `pyproject.toml`).
  - AC-7.4: Import detects the ZIP wrapper, decrypts with the supplied password, and extracts the inner SQLite file for validation.

---

## 5. API Specification

### `POST /api/backup/export`

- **Auth**: `X-Api-Key` (same as other mutating endpoints)
- **Request body** (JSON):
  ```json
  {
    "include_secrets": false,
    "password": "my-secure-password"
  }
  ```
- **Response**: Binary stream, `Content-Type: application/octet-stream`
- **Headers**: `Content-Disposition: attachment; filename="proxmon-backup-2026-03-11T12-00-00Z.db"`
- **Errors**:
  - 422: Password shorter than 8 characters
  - 500: Internal error during export

### `POST /api/backup/import`

- **Auth**: `X-Api-Key`
- **Request**: `multipart/form-data` with fields `file` and `password`
- **Response** (JSON):
  ```json
  {
    "success": true,
    "message": "Configuration restored successfully. Please reload the page."
  }
  ```
- **Errors**:
  - 400: Invalid password, corrupted file, missing metadata, or version mismatch
  - 413: File exceeds 10 MB size limit
  - 422: Missing required fields

---

## 6. UI Specification

### Settings page -- "Backup" section

```
[v] Backup                                          (collapsible, collapsed by default)
+-----------------------------------------------------------------------+
|  EXPORT                                                               |
|  [ ] Include secrets (API keys, SSH passwords, GitHub token)          |
|  [!] This backup will contain sensitive credentials. Keep it secure.  |  <-- only if checked
|                                                                       |
|  Password:          [__________________]                              |
|  Confirm password:  [__________________]                              |
|  Passwords do not match                                    <-- error  |
|                                                                       |
|  [Export Backup]                                                      |
+-----------------------------------------------------------------------+
|  IMPORT                                                               |
|  File:     [Choose file...]  proxmon-backup-2026-03-11.db             |
|  Password: [__________________]                                       |
|                                                                       |
|  [Import Backup]                                                      |
|                                                                       |
|  [!] Error: Invalid password or corrupted file           <-- on fail  |
+-----------------------------------------------------------------------+
```

- Export and Import are visually separated with a subtle divider.
- All fields use existing form components (`PasswordField`, `FormField`, `Toggle`).
- The confirmation dialog for import uses a standard browser `confirm()` or a custom modal consistent with the app's existing patterns.

---

## 7. Non-Functional Requirements

| Category | Requirement |
|----------|-------------|
| **Performance** | Export completes in <2s for a typical config (~50 KB JSON blob). Import completes in <3s including decryption and schema validation. |
| **Scale** | Single-user application; no concurrent export/import concerns. Max backup file size: 10 MB (enforced server-side). |
| **Security** | Password never logged, never stored, never returned in any response. AES-256 encryption. Backup file validated (magic bytes, ZIP structure) before attempting decryption. Uploaded files rejected if >10 MB before processing. |
| **Privacy** | When `include_secrets=false`, zero secret values in the exported file. Verified by test that parses the exported JSON blob and asserts all secret fields are empty. |
| **Observability** | Log (INFO): "Backup exported (secrets: yes/no)" and "Backup imported (schema_version: N)". Log (WARNING): failed import attempts with reason (no secrets logged). |
| **Reliability** | Import is atomic: if any step fails (decryption, validation, migration, save), the existing config is untouched. Use a transaction or write-to-temp-then-swap pattern. |
| **Compatibility** | Backup files are portable across OS and Docker architectures (SQLite is cross-platform). |

---

## 8. Scope

### In Scope
- Manual export/import via UI and API
- AES-256 encrypted ZIP packaging
- Optional secret redaction
- Schema versioning with migration registry
- Full config replacement on import
- Settings page "Backup" section

### Out of Scope
- Scheduled / automatic backups
- Cloud storage upload (S3, Google Drive, etc.)
- Partial / merge imports (e.g., import only app_config)
- Alert history, notification logs, or discovery cache in the backup
- CLI-based backup commands
- Backup rotation or retention policies

---

## 9. Rollout Plan

| Phase | Description | Guardrails |
|-------|-------------|------------|
| 1. Backend (export) | Implement `POST /api/backup/export` with encryption, redaction, and `backup_meta`. Add `pyzipper` dependency. Unit tests. | Tests assert: encrypted output, redaction correctness, schema version presence. |
| 2. Backend (import) | Implement `POST /api/backup/import` with decryption, validation, migration registry, and atomic config replacement. Unit tests. | Tests assert: wrong password rejected, version mismatch rejected, successful round-trip (export then import). |
| 3. Frontend | Add "Backup" section to Settings page with export/import controls. | Manual QA: export downloads file, import restores config, error states display correctly. |
| 4. Integration test | End-to-end: export with secrets, import on fresh instance, verify all settings restored. | Docker Compose test environment. |
| 5. Release | Ship behind no feature flag (low-risk, additive feature). Document in README. | Monitor error logs for import failures in first 7 days. |

### Kill Switch
- The feature is additive (new endpoints + new UI section). To disable: remove the "Backup" section from Settings.tsx and remove the `/api/backup/*` routes. No data migration needed.

---

## 10. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| `pyzipper` dependency has security vulnerability | Low | High | Pin version; monitor CVEs; `pyzipper` is a well-maintained wrapper around `pyminizip`. Fallback: replace with stdlib `zipfile` (supports AES in Python 3.13+). |
| User forgets backup password | Medium | Medium | No recovery possible by design (documented). UI shows clear warning that password cannot be recovered. |
| Import corrupts running state | Low | High | Atomic import: validate fully before writing. Create automatic pre-import snapshot of current config in memory; restore on failure. |
| Schema migration bugs on future versions | Low | Medium | Each migration is a pure function with unit tests. Migrations run on a copy; original backup is untouched. |
| Large config blobs cause memory pressure | Very Low | Low | 10 MB upload limit. Typical config is <100 KB. |

---

## 11. Open Questions

| # | Question | Owner | Status |
|---|----------|-------|--------|
| 1 | Should we auto-create a backup before each import (safety net)? | Product | Open |
| 2 | Should the export filename include the proxmon version for easier identification? | Product | Proposed: yes, e.g., `proxmon-backup-v1.2.0-2026-03-11.db` |
| 3 | Should we support drag-and-drop for the import file picker? | Frontend | Open -- nice-to-have, not required for v1 |
| 4 | Do we need rate limiting on the export endpoint to prevent abuse? | Backend | Low priority -- single-user app, defer. |

---

## 12. Implementation Notes

### Backend file structure
- `backend/app/core/backup.py` -- Export/import logic, encryption, schema validation, migration registry.
- `backend/app/api/routes.py` -- Add `/api/backup/export` and `/api/backup/import` endpoints (or create a separate `backup_routes.py` and include in the router).
- `backend/app/core/backup.py::BACKUP_SCHEMA_VERSION = 1`
- `backend/app/core/backup.py::BACKUP_MIGRATIONS: dict[int, Callable] = {}`

### Secret fields to redact (exhaustive list)
From `config_store.py` JSON blob structure:
- Top-level: `proxmox_token_secret`, `ssh_password`, `github_token`, `ntfy_token`
- `proxmox_hosts[*]`: `token_secret`, `ssh_password`
- `app_config[*]`: `api_key`, `ssh_password`
- `guest_config[*]`: `api_key`, `ssh_password`

### Frontend file structure
- `frontend/src/components/settings/BackupSection.tsx` -- New component for the Backup collapsible section.
- Import into `Settings.tsx` alongside existing sections.

### Test plan
- `test_backup.py`:
  - Export produces valid encrypted ZIP containing SQLite with `settings` + `backup_meta` tables.
  - Export with `include_secrets=false` redacts all secret fields (parse JSON blob, assert empty).
  - Export with `include_secrets=true` preserves secret values.
  - Import with correct password restores config.
  - Import with wrong password returns 400.
  - Import with newer schema version returns 400.
  - Import with older schema version triggers migration (when migrations exist).
  - Round-trip: export then import produces identical config.
  - File >10 MB rejected with 413.
  - Password <8 chars rejected with 422.
