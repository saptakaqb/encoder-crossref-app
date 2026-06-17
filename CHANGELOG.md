# Changelog

All notable changes to EncoderMatch are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [v2.2.1] — 2026-06-16

### Added
- **User Detail Overview analytics** — three new analytics cards below the existing stat row: Total Searches (all time, violet accent matching Client Admin badge), Avg Match Score (colour-coded green/amber/red by score tier), Feedback Score (thumbs up %). Feedback data now fetched on Overview tab open (not only when Feedback tab is clicked).
- **7-day search activity bar chart** — pure SVG bar chart on the Overview tab. Violet bars, today's bar highlighted with gradient. Count label above each bar. Zero-search days show faint placeholder. Renders only when user has search history.
- **Top Searched Parts list** — ranked list (max 5) of most repeated source part numbers for this user. Monospace part numbers with violet count badges. Renders alongside the 7-day chart.
- **Export User Data (ZIP)** — "Export User Data" button on User Detail page now downloads a named ZIP (`encodermatch_{client}_{name}_{date}.zip`) containing four CSVs: `profile.csv`, `history.csv`, `feedback.csv`, `errors.csv`. JSZip loaded dynamically from CDN. All three activity tables fetched fresh with `limit=9999` (full history, not truncated). Replaces the old "Download All Users CSV" button which incorrectly downloaded all users' data instead of the viewed user's data.

### Changed
- **Lika Silver updated** — 7,299 rows (was 4,072). Housing diameter fix applied manually in Bronze2. New fill rates: `housing_diameter_mm` 97%, `has_index` 100%, `sensing_method` 100%, `reverse_polarity_protection` 100%, `short_circuit_protection` 100%.
- **Total Silver rows: 1,657,202** (was 1,653,975).

### Fixed
- **`_client_slug()` routing bug** (`auth.py`) — `clientadmin` role was incorrectly routed to the `"admin"` DynamoDB bucket (same as `superadmin`), meaning all client admin searches landed in `encodermatch_history_admin` with no per-client isolation. Fixed: `clientadmin` now routes to their client slug (same tables as their endusers). `superadmin` routes to `"aqb_solutions"` (table already exists). `_admin` tables orphaned — 82 historical AQB searches stay, no new writes.
- **`dynamo_setup.py` safety** — docstring changed from "Safe to re-run" (incorrect — `seed_users()` calls `put_item()` unconditionally and would overwrite live admin records) to a hard "!! DO NOT RE-RUN ON A LIVE SYSTEM !!" warning with explanation.
- **Lika Bronze2 S3 key** (`csv_to_silver_parquet.py`) — `lika_raw_full.csv.gz` corrected to `lika_raw_full.gz` (actual S3 object name). Was causing `NoSuchKey` error on every Lika Silver transform run.
- **`parse_bool_str()` uppercase booleans** (`csv_to_silver_parquet.py`) — Lika Bronze2 stores boolean fields as `"TRUE"`/`"FALSE"` (uppercase). Parser only handled title-case and lowercase. Fixed by adding `"TRUE"` and `"FALSE"` to the respective lists. Affected fields: `has_index`, `reverse_polarity_protection`, `short_circuit_protection` — all went from 0% to 100% fill.
- **`sensing_method` blank fill for Lika** (`csv_to_silver_parquet.py`) — 3,590 of 7,299 Lika rows had empty string `""` for `sensing_method` (not NaN, so `fillna()` didn't catch them). Fixed with a per-row inference function: `R.C50MI` → `"magnetic"` (right-angle variant of C50MI, confirmed magnetic); all other blank families → `"optical"` (verified from circuit types: CK, C, I, CB, IT series all use digital optical circuits).

---

## [v2.2.0] — 2026-06-11

### Added
- **Product selector landing page** — full-screen page after login presenting Encoders and Valves as product categories. Valves is a placeholder ("Coming Soon"). Lays groundwork for multi-product expansion.
- **3-tier role system** — superadmin → clientadmin → enduser. Superadmin creates client admins and assigns their constraints (user creation cap, allowed results per search, source/target manufacturer pools). Client admins create and manage their own end users within those constraints.
- **AddUserModal: role-aware** — role toggle (End User / Client Admin), client/company field, `allowed_results` slider (3–20), `user_creation_limit` field. Source and target manufacturer pools are independently scoped to the creating admin's own access — no union bleed.
- **User hierarchy table** — expandable client admin rows (purple, with quota bar) and indented end user rows (blue connector). "Created by" label on each row. "Direct Accounts" section for superadmin-created users. Expand/collapse all groups, default expanded.
- **User quota strip** — visible in AdminPage header for clientadmin: progress bar showing X / N users created, colour-coded (purple → amber → red at 80% / 100%). Add User button auto-disables at limit.
- **UserDetailPage** — full-page user record replacing the side panel. Tabs: Overview (stat cards + recent activity), Activity (paginated table, 25/page), Account (field grid + source/target chips), Feedback, Errors. Sticky 230px identity card with limit adjuster always visible regardless of active tab.
- **ClientAnalyticsTab** — scoped analytics view for clientadmin: their users' total/active/locked counts, searches this month, top searched parts.
- **Scoring explanation redesign** — T1 cards with plain-English rules, T2 split into directional (IP, PPR) and proximity (housing, bore, circuit) sub-groups with worked IP rating example, T3 split into directional capability (voltage, shock, load, temp) and preference match (sensing method, pins) with worked voltage example. Corrects the incorrect implication that T3 fields are non-directional.
- **NumInput component** — fixes the clear-and-retype bug on all number inputs (searches limit, allowed results, user creation limit, topN results slider). Uses `type="text"` with blur-clamping instead of `type="number"` with `isNaN` guard.
- **`allowed_results` field** — stored per user in DynamoDB, enforced server-side in `/api/match` (`min(requested_n, user.allowed_results)`). Replaces the hardcoded end-user cap of 3.
- **`created_by` field** — stored on every user record at creation time. Used for clientadmin scoping in analytics and future table queries.
- **`/api/admin/analytics/client`** — new endpoint, `require_admin` gated. Returns scoped analytics for clientadmin: their users' stats, searches this month, top parts.
- **`user_creation_limit` and `allowed_results`** returned by `_safe_user` so frontend has them on login.

### Changed
- Login page left panel copy is now hardware-generic: "AI-powered hardware cross-reference", "1.65M+ variants across leading manufacturer catalogues". Removes encoder/manufacturer-specific copy.
- `handleLogin` always routes to `page = 'selector'` first instead of directly to `search` or `admin`. Selector page renders standalone (no sidebar), same as login page.
- `canAccessConsole` — clientadmin now sees the Console nav item in AppNav. Database stats panel (manufacturer row counts) remains hidden from clientadmin; the `/health/db` fetch short-circuits on `!isAdmin`.
- AdminPage Database tab hidden from clientadmin. Usage Analytics tab shows `ClientAnalyticsTab` for clientadmin and the existing global `AnalyticsTab` for superadmin.
- Role badge in topbar header now shows "Super Admin" (blue), "Client Admin" (purple), "End User" (green) instead of "ADMIN" / "END USER".
- `run_match` — only superadmin gets unrestricted access to `VALID_MANUFACTURERS`. Clientadmin and enduser are now correctly scoped to their configured `allowed_sources`/`allowed_targets`. `effective_top_n` uses `user.allowed_results` for non-superadmin roles.
- `CreateUserRequest` Pydantic model — added `role`, `allowed_results`, `user_creation_limit` fields. Removed incorrect `client_must_be_valid` validator that was rejecting company names against manufacturer IDs. Added `role_must_be_valid` validator.
- `create_user` endpoint — uses `body.role` instead of hardcoded `"enduser"`. Stores `allowed_results`, `created_by`, `user_creation_limit` in DynamoDB record.
- `_admin_user` now includes `created_by` in the extended user dict returned to admin endpoints.

### Fixed
- **Login white screen** — Pydantic 422 responses return `detail` as an array of objects. Setting React state to an array of objects then rendering it crashed the component. Fixed with type-safe error parsing (`Array.isArray(raw) ? raw.map(d => d.msg).join(' · ') : raw`).
- **Login 422 on empty password** — frontend now guards `if(!pwRef.current)` before submitting. Shows "Password is required" inline instead of hitting the server.
- **Peek last character stale closure** — `handlePwChange` was reading `password` state (stale on fast typing) to compute deltas. Replaced with `pwRef = useRef('')` which is always current regardless of React render cycles. Submit handler also reads `pwRef.current` directly.
- **Manufacturer pools cross-contamination** — clientadmin's Add User modal was showing the union of `allowed_sources + allowed_targets` for both source and target pools. Now uses separate `availableSrcIds` and `availableTgtIds` derived independently.
- **Baumer missing from ALL_MANUFACTURERS and AppNav MFR_LABELS** — restored after being absent from the working base file.

---

## [v2.1.0] — 2026-06-10

### Added
- **Baumer incremental encoder data** — 475 rows in Silver (industrial + heavy-duty incremental categories). `transform_baumer()` added to `csv_to_silver_parquet.py`. Baumer added to `ALL_MANUFACTURERS`, `MFR_LABELS`, `db_load.py` family prefix map, `url_lookup.py`.
- **Multi-target search** — users can select multiple target manufacturers independently. Tab-based multi-select pools for source and target in the search panel.
- **`CLAUDE.md`** — project context file in repo root for Claude Code auto-read.

### Changed
- Total Silver rows: 1,653,975 (EPC 1,520,586 · Kübler 102,748 · Posital 18,742 · Sick 7,352 · Lika 4,072 · Baumer 475)

---

## [v2.0.0] — 2026-06-05

### Added
- Posital lifecycle filter: `_load_posital_exiting()` reads Posital Bronze2 CSV from S3 at startup, filters 7,492 Exiting part numbers from candidates
- `match_pair()` utility and `--target-part` CLI flag for direct pair scoring
- No-match reason system: `no_match_reasons` in API response + `NoMatchBanner` in frontend

### Fixed
- Zero-score results now filtered from match output
- Float32 Parquet precision artifacts rounded in `serialize_source()`
- 429 daily limit shows error message instead of silently greying out
- Shaft type display labels: `hollow_blind` → "Hollow bore (blind)"

---

## [v1.1.0] — 2026-05-22

### Added
- EPC real order code decoder (`epc_decoder.py`): 28 entries, 25 families
- EPC Stage 2b decode path in `db_load.py`
- Silver grows: 1,319,556 → 1,520,586 rows (15T/H and 25T/H sibling expansion)

---

## [v1.0.0] — 2026-05-21

### Added
- Kübler real order code decoder (`kubler_decoder.py`): 31 families, Path A and B
- Hollow encoder housing pre-filter fix
- T1 `solid_only` condition on housing OD
- ECS deployed: revision 4 (2 vCPU / 8 GB)
