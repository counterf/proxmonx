# PRD: App Logo, Clickable App Names, and Responsive Design

**Author:** Product
**Date:** 2026-03-08
**Status:** Draft
**Target release:** v0.4

---

## Context & why now

- proxmon's dashboard lists monitored Proxmox guests and their detected apps (Sonarr, Radarr, Plex, etc.), but users cannot navigate to an app's web UI from the dashboard. They must manually type the IP:port in a new tab.
- The header shows a plain text "proxmon" with no brand identity; adding a logo gives the product a polished, recognizable presence.
- The current layout uses fixed-width tables and hard-coded pixel values. On mobile or tablet the UI is unusable -- horizontal scrolling, truncated controls, unreachable buttons.
- Addressing all three in one release is efficient: the logo touches the navbar (shared across all pages), the clickable name touches GuestRow/GuestDetail, and responsive design touches every page.

## Users & JTBD

| User | Job to be done |
|---|---|
| **Homelab admin (primary)** | "When I see my app is running, I want to jump straight to its web UI so I can manage it without hunting for the URL." |
| **Homelab admin (mobile)** | "When I check proxmon on my phone I want to see guest status at a glance without horizontal scrolling." |
| **New user** | "When I land on proxmon I want to instantly recognize the product and feel it is professional and trustworthy." |

## Business goals & success metrics

| Goal | Leading indicator | Lagging indicator |
|---|---|---|
| Reduce friction to access monitored apps | Click-through rate on app names > 30% of dashboard sessions (analytics event) | User-reported satisfaction in GitHub discussions |
| Improve mobile usability | Zero horizontal scroll on viewports >= 320px (automated visual regression) | Decrease in "mobile layout" bug reports to zero |
| Strengthen brand identity | Logo renders on all pages including Setup Wizard | N/A (qualitative) |

---

## Functional requirements

### FR-1: Proxmon logo in the navbar

Display an SVG logo beside the "proxmon" text in the top navbar on every page (Dashboard, GuestDetail, Settings, Setup Wizard).

**Acceptance criteria:**
- AC-1.1: An SVG logo file exists at `frontend/src/assets/proxmon-logo.svg`.
- AC-1.2: The logo renders at 24x24px on desktop and 20x20px on mobile (< 640px), with 8px gap before the text.
- AC-1.3: Both the unconfigured navbar (Setup Wizard) and the configured navbar (main app) display the logo.
- AC-1.4: The logo + text combination is wrapped in the existing `<Link to="/">` so clicking either returns to the Dashboard.
- AC-1.5: The logo has `alt="proxmon logo"` (via `<img>` or `role="img" aria-label`).

### FR-2: Clickable app name opens web UI

When a guest has a detected app and a known IP, the app name in the dashboard table and the detail page links to the app's web address (`http://{ip}:{port}`).

**Acceptance criteria:**
- AC-2.1: The backend exposes a new field `web_url: str | null` on both `GuestSummary` and `GuestDetail` models. The URL is constructed as `http://{ip}:{effective_port}` where `effective_port` is the user-configured port override or the detector's `default_port`. The field is `null` when `ip` is null, `app_name` is null, or the guest is stopped.
- AC-2.2: In `GuestRow`, when `web_url` is non-null, the App column renders the app name as an `<a href={web_url} target="_blank" rel="noopener noreferrer">` anchor. Clicking it opens the app in a new tab and does NOT trigger row navigation (must call `e.stopPropagation()`).
- AC-2.3: In `GuestDetail`, the App Detection panel shows the app name as a clickable link when `web_url` is non-null, with a visible external-link icon.
- AC-2.4: When `web_url` is null the app name renders as plain text (current behavior).
- AC-2.5: The frontend `GuestSummary` and `GuestDetail` TypeScript types include `web_url: string | null`.
- AC-2.6: Tooltip on hover shows the full URL (e.g., `http://192.168.1.50:8989`).

### FR-3: Responsive design -- all pages

All pages render correctly at mobile (320-639px), tablet (640-1023px), and desktop (>= 1024px) breakpoints.

**Acceptance criteria:**

#### FR-3a: Dashboard

- AC-3a.1: On mobile, the guest table switches to a card/list layout -- one card per guest with stacked rows for name, app, status, and version info. No horizontal scroll.
- AC-3a.2: On tablet, the table hides low-priority columns (Last Checked, Actions) and uses responsive column widths.
- AC-3a.3: FilterBar inputs stack vertically on mobile, inline on tablet+.
- AC-3a.4: Header badges and Refresh button wrap gracefully on narrow screens.

#### FR-3b: GuestDetail

- AC-3b.1: Metadata chips (type badge, ID, status, tags) wrap to multiple lines on mobile.
- AC-3b.2: Panels (App Detection, Version Status, Version History) are full-width and stack vertically at all breakpoints.
- AC-3b.3: Version History table scrolls horizontally within its container if needed, not the entire page.

#### FR-3c: Settings

- AC-3c.1: Form fields are full-width on mobile. Labels and inputs stack vertically.
- AC-3c.2: The sticky save bar remains fixed at bottom and centered on all widths.
- AC-3c.3: App Configuration cards are single-column on mobile, two-column on tablet+.

#### FR-3d: Setup Wizard

- AC-3d.1: Wizard steps are full-width on mobile with no overflow.
- AC-3d.2: Step navigation buttons remain accessible and do not overlap.

---

## Non-functional requirements

| Category | Requirement |
|---|---|
| **Performance** | Logo SVG must be < 5 KB. No additional HTTP requests (inline or bundled via Vite). |
| **Accessibility** | All new interactive elements must be keyboard-navigable and have ARIA labels. External links announce "(opens in new tab)" to screen readers. Color contrast ratios meet WCAG 2.1 AA. |
| **Browser support** | Chrome, Firefox, Safari, Edge -- latest 2 major versions. |
| **Observability** | (Optional) Add a `data-testid` attribute to the logo, each clickable app link, and the mobile card layout for future E2E tests. |
| **Security** | `web_url` construction must sanitize IP to prevent injection. Only `http://` and `https://` schemes allowed. URLs are rendered via React's href attribute (no `dangerouslySetInnerHTML`). |
| **Privacy** | No new data collection. Guest IPs are already stored server-side. |
| **Scale** | No impact -- purely frontend rendering + one new computed field on existing API models. |

---

## Scope

### In scope

- SVG logo asset creation (simple geometric mark, monochrome with accent color matching existing `blue-600` palette)
- Backend: add `web_url` computed field to `GuestSummary`, `GuestDetail`, and `GuestInfo.to_summary()`/`to_detail()`
- Frontend: logo in navbar, clickable app names, responsive Tailwind CSS for all 4 pages
- Update frontend TypeScript types

### Out of scope

- Custom favicon (separate task)
- HTTPS detection for `web_url` (always defaults to `http://`; users with reverse proxies manage their own URLs)
- User-configurable `web_url` override per guest (future enhancement)
- Dark/light theme toggle
- Analytics/telemetry event tracking
- Backend API changes beyond adding the `web_url` field

---

## Technical constraints

- **Frontend stack:** React 18 + TypeScript + Vite + Tailwind CSS (no additional CSS frameworks)
- **Responsive approach:** Tailwind responsive prefixes (`sm:`, `md:`, `lg:`). No CSS-in-JS. The existing Tailwind config uses default breakpoints (sm: 640px, md: 768px, lg: 1024px).
- **Logo:** Must be an SVG file imported as a React component or via `<img>` tag. No raster images.
- **Backend:** `web_url` is a computed/read-only field derived from existing `ip`, `detector_used` (to look up `default_port`), and `app_config[detector].port` override. No database schema changes.
- **No new dependencies.** Tailwind already supports all required responsive utilities.

---

## Rollout plan

| Phase | Scope | Guardrail |
|---|---|---|
| **1 -- Backend** | Add `web_url` field to models | Unit tests: `web_url` is null when ip is null; correct port resolution with/without override |
| **2 -- Logo + navbar** | SVG asset + navbar update across all page states | Visual snapshot test at 3 breakpoints |
| **3 -- Clickable app names** | GuestRow + GuestDetail links | Manual QA: verify new tab opens, row click still works, null case renders plain text |
| **4 -- Responsive** | Dashboard cards, GuestDetail, Settings, Setup | Automated visual regression at 320px, 768px, 1280px viewports |

**Kill switch:** Feature flag `PROXMON_ENABLE_WEB_LINKS=false` (env var, default true). When false, `web_url` is always returned as null from the API. No frontend changes needed -- null already renders as plain text.

---

## Risks & mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Constructed `web_url` is wrong (custom port, HTTPS, reverse proxy) | User clicks link and gets connection error | Show URL in tooltip so user can verify before clicking. Document limitation. Future: allow per-guest URL override. |
| Mobile card layout loses information density | Power users prefer table view on tablets | Only switch to cards below 640px. Tablet retains table with fewer columns. |
| SVG logo not rendering in older browsers | Broken image | Use inline SVG (not `<object>`), which has universal support. |
| `e.stopPropagation()` on app link breaks click on rest of row | Row navigation stops working | Scoped to the anchor element only; the row `onClick` remains on `<tr>`. Already used for the "View" button. |

---

## Open questions

1. **Logo design:** Should we commission a proper logo, or is a simple geometric SVG placeholder sufficient for MVP?
2. **HTTPS heuristic:** Should we attempt HTTPS first and fall back to HTTP, or always use HTTP? (Recommendation: always HTTP for v1, document the limitation.)
3. **Port 443/80 special case:** Should `web_url` omit the port for 80/443? (Recommendation: yes, for cleaner URLs.)
4. **Mobile card: which fields to show?** Proposed: name, app (clickable), status badge, installed version. Omit: latest version, last checked, type badge. Confirm with stakeholders.
