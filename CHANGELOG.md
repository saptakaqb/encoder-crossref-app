# Changelog

All notable changes to EncoderMatch are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [v2.4.0] — 2026-06-18

### Added
- **Connection type T1 hard stop with cable exemption** (`matcher.py`, `matcher_config.json`) — connector type promoted from partial T1 (forbidden pairs only) to full exact-match T1, requested by Kübler for plug-and-play replacement accuracy. Rule: when both source and candidate use specific connector types (M12, M23, MS/MIL, etc.), they must match exactly — mismatched connectors cannot physically mate. Cable is exempt from the hard stop on both sides: cable source → all candidates pass T1 and score in T2; cable candidate → passes T1 and scores in T2. Null/empty on either side → T1 skipped (both-known condition). New rule type `exact_match_except_cable` registered in `T1_RULE_REGISTRY`.
- **Cable-conditional T2 weight redistribution** (`matcher.py`) — when both source and candidate are specific (non-cable) connector types, the connection_type T2 score is set to `NaN` for surviving candidates (T1 already guarantees exact match, making T2 connection_type trivially 1.0 and non-discriminating). `_weighted_score()`'s existing null-redistribution flows the 0.15 weight proportionally to the remaining five T2 fields (CPR, IP, output circuit, housing, bore), improving score differentiation among T1-surviving candidates. Cable-involved rows retain the 0.15 weight with matrix-based partial scoring.
- **History row → pre-fill search** (`EncoderMatch.jsx`) — clicking a row in the Search History page now navigates to the cross-reference search panel and pre-populates part number, source manufacturer, and target manufacturer checkboxes from the history record. Search is not auto-submitted — user must click Find Replacements manually. `replayParams` state in App threads through SearchPage → SearchPanel. `setDetectedMfr` set from history source_mfr to bypass the "Code not recognized" guard without firing a detect API call. Replay params cleared after applying to prevent stale pre-fill on future page mounts.

### Changed
- **Scoring Weights page** (`EncoderMatch.jsx`) — Connection type now appears in both the T1 and T2 sections. T1 locked params table gains "Connection Type (non-cable) / Exact Match" row. T1 explanation cards gains a fourth card describing the exact-match-with-cable-exemption rule. T2 description for connection type updated to "Connection Type (cable)" with note explaining cable-only applicability and the cross-reference to T1.
- **Login page feature description** (`EncoderMatch.jsx`) — second feature bullet changed from "Two-tier scoring — physical fit weighted 70%, secondary specs 30%" to "Three-tier compatibility engine with AI-powered match explanations". Removes internal weight percentages from user-facing copy; correctly describes the three-tier architecture (T1 hard stops + T2 primary + T3 secondary); surfaces AI explanation as a differentiator.
- **Product selector page — superadmin only** (`EncoderMatch.jsx`) — `handleLogin` now routes non-superadmin roles directly to `'search'` instead of `'selector'`. Superadmin: selector → search as before. Client admin and end user: skip selector, go directly to the cross-reference tool. Product selector has no nav item, so no nav changes required.
- **Data count — dynamic** (`EncoderMatch.jsx`) — `EmptyState` ("Enter a part number to begin") and `LoadingSpinner` ("Scoring against …") replaced hardcoded `"1.45M+"` with a live total computed from the `mfrs` array (`mfrs.reduce((s,m)=>s+m.count, 0)`) and formatted as `X.XXM+`. Count auto-updates on Silver refresh. Falls back to `"1.65M+"` if mfrs not yet loaded.
- **Search history normalization** (`EncoderMatch.jsx`) — `source_mfr` field added to the history record map in `HistoryPage`. Was present in raw DynamoDB records but missing from the normalized UI object; required for history row pre-fill.
- **History footer text** (`EncoderMatch.jsx`) — "Click any row to re-run the search" → "Click any row to pre-fill the search" to accurately describe the new behavior (pre-fill only, no auto-submit).
- **`matcher_config.json` T1 rule** — `connection_type_canonical` entry replaced: rule type `forbidden_pairs` (10 explicit pairs, partial coverage) → `exact_match_except_cable` (full coverage, no params block needed — cable exception handled in code). T2 description and `_tier2_note` updated to document the dual T1/T2 role.

### Fixed
- **Errors tab badge count shows immediately** (`EncoderMatch.jsx`) — errors were fetched lazily (only when `tab === 'errors'`), so the red numeric badge on the Errors tab always showed nothing until the user clicked it. Fixed by adding `'overview'` to the fetch condition: `if((tab!=='errors'&&tab!=='overview')||...)`. Errors now fetch on component mount (default tab is `'overview'`), making the badge count visible immediately. Fixed in both `UserDetailPage` instances.
- **Error message text truncation** (`EncoderMatch.jsx`) — long error strings in the Errors tab table were cut off by `whiteSpace:'nowrap'` + `textOverflow:'ellipsis'`. Changed to `whiteSpace:'normal'` + `wordBreak:'break-word'`. Column `maxWidth:300` retained.

---

## [v2.3.0] — 2026-06-17

### Added
- **Role colour system** — four distinct, equally-vibrant colour palettes applied consistently across the entire app. Superadmin: blue `#2563eb`. Client admin: purple `#7c3aed` (existing). Client admin's end users ("child"): teal `#0891b2`. Direct accounts (superadmin-created end users): emerald `#059669`. Each role's colour drives: avatar gradient, row left border, connector dot, hover tint, role badge, and sticky card border in `UserDetailPage`. All avatar shapes unified to 8px rounded square.
- **Super Admins section in user management table** — dedicated "SUPER ADMINS" section at the top of the user list, above "CLIENT ADMIN AND USERS" and "DIRECT ACCOUNTS". Superadmins no longer appear mixed into Direct Accounts. Section header conditional — hidden in client admin views (superadmins belong to `AQB Solutions` client, not visible in scoped views). "Created by" line suppressed for superadmin rows.
- **Max Users Allowed adjuster in UserDetailPage sticky card** — new `−`/`+`/Apply control below Daily Search Limit. Appears when a superadmin views a client admin user. Purple accent. Calls `PUT /api/admin/users/{email}` with `{user_creation_limit: value}`. Only visible to superadmin viewers; client admin viewers see "Managed by AQB Solutions" for all limit controls.
- **LIMIT / FULL badges** — inline red pill badge (`LIMIT`) appears next to the count in the Daily Searches column when a user has hit their daily search limit. `FULL` badge appears in the Users column when a client admin's user creation quota is reached. Visible to superadmin at a glance without opening the user detail page.

### Changed
- **Activity/Users column split** — single "Activity / Users" column replaced by two separate columns: "Daily Searches" and "Users". Client admin rows now show their own daily search usage in the first column and their user creation quota in the second. End user rows show a `—` in the Users column. Grid template updated from 7 to 8 columns.
- **User management three-way filter** — `users` array now split into `superAdmins` (role=superadmin), `clientAdmins` (role=clientadmin), and `endUsers` (role=enduser, pure). Superadmins no longer bleed into `directUsers`.
- **UserDetailPage sticky card alignment** — tab bar moved above the two-column flex row. Sticky card at `top:0` now naturally aligns with the first stat card row instead of starting 56px above it.
- **Dark/Light mode toggle on login and product selector pages** — replaced bottom-right `TweaksPanel` floating popup with the same top-right inline sun/moon icon button used in the main app. Single click toggles. Consistent position and behaviour across all pages.
- **AQB Solutions logo** — wrapped in white rounded badge container (`background:white, borderRadius:10, padding:8px 14px, boxShadow`) on the login page left panel. Accommodates the PNG logo's white background cleanly on the navy panel.
- **Brand colour consistency** — nav icon (expanded and collapsed) and EncoderIcon on the product selector page changed from blue/indigo to orange `#e87820`, matching the login page ENCODERMATCH badge and favicon.
- **Download User Data profile.csv column names** — renamed from terse internal names (`dir`, `sources`, `dbs`, `limit`) to readable: `direction`, `allowed_sources`, `allowed_targets`, `daily_search_limit`, `max_users_allowed`.
- **`UpdateUserRequest` (main.py)** — added `user_creation_limit: Optional[int]` field so `PUT /api/admin/users/{email}` can update a client admin's user creation quota.

### Fixed
- **Favicon browser cache** (`index.html`) — added explicit `<link rel="icon" href="/favicon.ico?v=3" type="image/svg+xml"/>`. Browsers cache `.ico` files independently from the page; the explicit link tag with version query string forces a fresh request of the orange SVG favicon.
- **Stale `resolution_ppr` warning** — confirmed `resolution_ppr` field does not appear in any Python source file. `matcher.py` already uses `cpr_values` JSON array correctly throughout. Prior context doc warnings about a needed rewrite were stale and have been removed.

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
- **Scoring explanation redesign** — T1 cards with plain-English rules, T2 split into directional (IP, PPR) and proximity (housing, bore, circuit) sub-groups with worked IP rating example, T3 split into directional capability (voltage, shock, load, temp) and preference match (sensing method, pins) with worked voltage example.
- **NumInput component** — fixes the clear-and-retype bug on all number inputs.
- **`allowed_results` field** — stored per user in DynamoDB, enforced server-side in `/api/match`.
- **`created_by` field** — stored on every user record at creation time.
- **`/api/admin/analytics/client`** — new endpoint, `require_admin` gated.
- **`user_creation_limit` and `allowed_results`** returned by `_safe_user` so frontend has them on login.

### Changed
- Login page left panel copy is now hardware-generic.
- `handleLogin` routes to `page = 'selector'` first (changed to role-based routing in v2.4.0).
- `canAccessConsole` — clientadmin now sees the Console nav item in AppNav.
- AdminPage Database tab hidden from clientadmin.
- `run_match` — only superadmin gets unrestricted access to `VALID_MANUFACTURERS`.
- `CreateUserRequest` — added `role`, `allowed_results`, `user_creation_limit` fields.
- `create_user` endpoint — uses `body.role` instead of hardcoded `"enduser"`.

### Fixed
- Login white screen on Pydantic 422 responses.
- Login 422 on empty password.
- Peek last character stale closure.
- Manufacturer pools cross-contamination in AddUserModal.
- Baumer missing from `ALL_MANUFACTURERS` and `AppNav MFR_LABELS`.

---

## [v2.1.0] — 2026-06-10

### Added
- **Baumer incremental encoder data** — 475 rows in Silver (industrial + heavy-duty incremental categories).
- **Multi-target search** — users can select multiple target manufacturers independently.
- **`CLAUDE.md`** — project context file in repo root for Claude Code auto-read.

### Changed
- Total Silver rows: 1,653,975

---

## [v2.0.0] — 2026-06-05

### Added
- Posital lifecycle filter: `_load_posital_exiting()`.
- `match_pair()` utility and `--target-part` CLI flag.
- No-match reason system: `no_match_reasons` in API response + `NoMatchBanner` in frontend.

### Fixed
- Zero-score results filtered from match output.
- Float32 Parquet precision artifacts rounded in `serialize_source()`.
- 429 daily limit shows error message instead of silently greying out.
- Shaft type display labels: `hollow_blind` → "Hollow bore (blind)".

---

## [v1.1.0] — 2026-05-22

### Added
- EPC real order code decoder (`epc_decoder.py`): 28 entries, 25 families.
- EPC Stage 2b decode path in `db_load.py`.
- Silver grows: 1,319,556 → 1,520,586 rows.

---

## [v1.0.0] — 2026-05-21

### Added
- Kübler real order code decoder (`kubler_decoder.py`): 31 families, Path A and B.
- Hollow encoder housing pre-filter fix.
- T1 `solid_only` condition on housing OD.
- ECS deployed: revision 4 (2 vCPU / 8 GB).
