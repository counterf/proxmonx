# PRD: Version Detection Explainer in Guest Detail View

**Author:** proxmon team
**Date:** 2026-03-10
**Status:** Draft -- awaiting review
**Stakeholders:** Self-hosted / homelab users running Proxmox

---

## Context & Why Now

proxmon's guest detail view has a "Show raw output" accordion that explains *how* an app was discovered (detection method, detector plugin, matched name/tags). However, there is no equivalent explainer for *how* the installed version and latest version were determined.

Users currently see version numbers but have no way to answer:
- "Did proxmon get this version via HTTP, SSH, or pct exec?"
- "Which GitHub repo was queried for the latest version?"
- "Did the GitHub lookup actually succeed, or is the 'unknown' status because the lookup failed vs. no repo configured?"

This information is critical for debugging version mismatches, configuring per-app overrides, and trusting the dashboard output. The backend already tracks `version_detection_method` but does **not** track the GitHub repo queried or the success/failure status of the GitHub lookup. Both gaps need to be closed.

---

## Users & Jobs-to-be-Done

| User | JTBD |
|------|------|
| Homelab admin debugging a version mismatch | "I need to know exactly how proxmon determined the installed version so I can fix a wrong result." |
| Homelab admin setting up a new app | "I want to confirm that proxmon is querying the correct GitHub repo for latest version." |
| Homelab admin with SSH/pct exec configured | "I want to verify which version-fetch method actually succeeded for a given guest." |

---

## Business Goals & Success Metrics

| Goal | Leading metric | Lagging metric |
|------|---------------|----------------|
| Reduce debugging friction for version issues | Users can self-diagnose version problems without reading backend logs | Fewer GitHub issues asking "why is my version wrong / unknown" |
| Increase transparency of detection pipeline | Version explainer section rendered for 100% of guests with a detected app | Increased user trust in dashboard accuracy |
| Surface actionable config hints | Users see which GitHub repo is queried and can override via per-app settings if wrong | Fewer misconfigured `github_repo` overrides |

---

## Functional Requirements

### Backend

| # | Requirement | Acceptance Criteria |
|---|------------|-------------------|
| B1 | Add `github_repo_queried: str \| None` field to `GuestInfo`, `GuestDetail`, and `GuestSummary` models. | Field is present in the `/api/guests/{id}` JSON response. Value is the `owner/repo` string that was actually used (override or detector default), or `null` if no repo is configured. |
| B2 | Add `github_lookup_status: str \| None` field to the same models. Values: `"success"`, `"failed"`, `"rate_limited"`, `"no_repo"`, or `null`. | Field is present in the API response and correctly reflects the outcome of the GitHub API call. |
| B3 | Populate `github_repo_queried` in `_check_version()` with `effective_repo` (the override or detector default). | Given a detector with `github_repo = "Sonarr/Sonarr"` and no user override, the field is `"Sonarr/Sonarr"`. Given a user override of `"MyFork/Sonarr"`, the field is `"MyFork/Sonarr"`. |
| B4 | Populate `github_lookup_status` based on the outcome of `self._github.get_latest_version()`. | `"success"` when a version is returned, `"failed"` on exception, `"no_repo"` when `effective_repo` is `None`/empty. |
| B5 | Propagate both new fields through `to_summary()` and `to_detail()`. | Both fields appear in summary and detail API responses. |
| B6 | Include `version_detection_method`, `github_repo_queried`, and `github_lookup_status` in `raw_detection_output` dict for raw-output display. | The raw JSON shown in the frontend includes these three fields alongside existing detection fields. |

### Frontend

| # | Requirement | Acceptance Criteria |
|---|------------|-------------------|
| F1 | Add a "Version Detection" panel as a standalone top-level section in `GuestDetail.tsx`, positioned between the Version Status panel and the Version History table. This placement (per the UX spec) improves discoverability over nesting inside the raw-output accordion. | The panel renders as a visible section (not inside an accordion) with structured version-detection info whenever an app is detected. |
| F2 | Display the following fields in the Version Detection subsection: `version_detection_method`, `github_repo_queried`, `github_lookup_status`. | Each field is shown with a human-readable label. Null values display as an em-dash. |
| F3 | `version_detection_method` displays as a styled badge: `HTTP` (blue), `SSH` (green), `pct exec` (purple), or "None" (gray). | Badge color matches the method. |
| F4 | `github_repo_queried` renders as a clickable link to `https://github.com/{repo}`. | Clicking opens the GitHub repo in a new tab. If null, show em-dash. |
| F5 | `github_lookup_status` displays as a styled indicator: `success` (green text), `failed` (red text), `rate_limited` (yellow text), `no_repo` (gray text). | Color coding matches the status value. |
| F6 | Add `github_repo_queried` and `github_lookup_status` to the `GuestDetail` TypeScript interface in `types/index.ts`. | TypeScript compiles without errors. |
| F7 | The Version Detection subsection only renders when `version_detection_method` or `github_repo_queried` is non-null (i.e., skip for guests with no detected app). | A stopped guest with no app shows no Version Detection block. |

---

## Non-Functional Requirements

| Category | Requirement |
|----------|------------|
| Performance | No additional API calls introduced. New fields piggyback on existing discovery cycle data. |
| Scale | No impact. Two additional string fields per guest in memory; negligible. |
| Privacy | `github_repo_queried` contains only public repo identifiers (owner/repo). No tokens or secrets exposed. |
| Security | No new attack surface. Fields are read-only, populated server-side. |
| Observability | `github_lookup_status = "failed"` and `"rate_limited"` are already logged as warnings in `discovery.py` and `github.py`. No new logging required. |
| Backwards compat | New fields default to `null`; existing API consumers are unaffected. |

---

## Scope

### In Scope

- Two new fields on backend models (`github_repo_queried`, `github_lookup_status`)
- Population logic in `_check_version()` in `discovery.py`
- Frontend "Version Detection" subsection in the raw-output accordion
- TypeScript type updates

### Out of Scope

- Changing the GitHub client itself (`github.py`) -- it already returns `None` on failure; we just need to capture the reason
- Adding `rate_limited` detection in `GitHubClient` -- requires the client to return structured errors instead of `None`. Deferred; initially `failed` covers both rate-limit and other errors. (See Open Questions)
- Exposing version-detection info on the dashboard table (summary view) -- detail view only for now
- Version detection method selection/override from the frontend -- already handled by existing per-app config

---

## Rollout Plan

| Phase | Scope | Guardrails |
|-------|-------|-----------|
| 1 | Backend: add fields to models, populate in `_check_version()`, include in API response | Unit tests: verify fields populated for HTTP, SSH, pct_exec paths; verify `null` for guests with no app |
| 2 | Frontend: add TypeScript types, render Version Detection subsection | Manual QA: verify rendering for each `version_detection_method` value and each `github_lookup_status` value |
| 3 | Merge to main, deploy | Smoke test: confirm existing guests render correctly, new fields appear in detail view |

### Kill Switch

- Frontend: the Version Detection subsection is purely presentational. If it causes rendering issues, remove the JSX block in `GuestDetail.tsx` -- no backend rollback needed.
- Backend: new fields default to `null` and are not consumed by any other backend logic. Safe to revert the population logic without data migration.

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| `GitHubClient.get_latest_version()` returns `None` for both "no repo" and "API failure" -- caller cannot distinguish | `github_lookup_status` would be inaccurate | Check `effective_repo` before calling; if empty/None, set status to `"no_repo"` without calling the client. For non-None repo, treat `None` return as `"failed"`. |
| Future addition of `rate_limited` status requires changes to `GitHubClient` return type | Deferred complexity | Accept `"failed"` as a catch-all for now; file a follow-up issue to return structured errors from `GitHubClient`. |
| Frontend hardcodes `GITHUB_REPOS` map for release links (line 10-23 of `GuestDetail.tsx`) | Duplicates the backend's detector `github_repo` knowledge | Once `github_repo_queried` is available from the API, refactor the release-notes link to use it instead of the hardcoded map. This is a cleanup opportunity, not a blocker. |

---

## Open Questions

1. **Should `GitHubClient` return structured results (version + status) instead of `str | None`?** This would make `rate_limited` vs `failed` distinguishable. Recommend: yes, but as a follow-up PR to keep this change small.
2. **Should the Version Detection subsection be a separate accordion or part of the existing "Show raw output"?** Recommendation: separate visual block *within* the same accordion to keep it discoverable but not noisy.
3. **Should `github_repo_queried` also appear in `GuestSummary` for the dashboard table?** Recommendation: no for now; it adds table width without clear value. Revisit if users request it.
