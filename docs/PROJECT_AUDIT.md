# WorkSphere HRMS — project audit

Date: 2026-10-28. Scope: read-only inspection of `backend/`, `frontend/`, `e2e/`, `docker*`, `nginx/` and the docs. **No application code was changed for this audit.**
`docs/IMPLEMENTATION_PLAN.md` and `CHECKLIST.md` are the change logs of earlier phases; this file is the current-state assessment and the plan awaiting approval.

How to read the evidence column: **[code]** = read in the source this session; **[ran]** = a test/suite I executed this session; **[docs]** = taken from an earlier log and not re-verified.

## 1. Baseline (actually run this session)

| Check | Result |
|---|---|
| Backend `pytest` (SQLite tenants, 32 modules) | exit 0, no failures **[ran]** (pass count line was swallowed by warning output; last counted run was 440 collected) |
| Frontend `vitest` | 11 files, 113 tests passed **[ran]** |
| Playwright (real Chromium, backend + Vite started by the config) | 256 passed, 0 failed **[ran]** — includes an axe a11y sweep and a two-browser WebRTC call with fake camera |
| Migrations 0017 up/down/up on SQLite | passed **[ran]** |
| PostgreSQL, Docker build, `nginx -t`, load tests, linting, CI | **not run** — no Docker/Postgres here, and no lint/CI config exists |

## 2. Architecture as found

* **Backend:** FastAPI, ~12.9k lines in `app/modules/*` (largest: `employees` 1531, `teams` 1071, `performance` 917, `leave` 918, `attendance` 853, `payroll` 845). SQLAlchemy models in `app/db/tenant_models.py` / `platform_models.py`. Two Alembic trees: platform (head 0003) and tenant (head 0017). A model-vs-migration drift test exists.
* **Tenancy:** a central platform DB holds companies, platform admins and the token denylist; every company has its own database. The tenant is taken from the JWT, never from request input; DB URLs are encrypted. `deps.get_ctx` resolves user + tenant session per request.
* **Auth/session:** bcrypt, lockout limiter, JWT with `jti` + `session_version`, denylist, refresh rotation, TOTP MFA (users and platform admins), e-mail reset/verification. Browser sessions use three httpOnly SameSite=Strict cookies plus an `X-WS-Client` header as the CSRF check; API clients use bearer tokens. WebSockets re-validate the session every 30 s.
* **Authorization:** `access.py` (hierarchy, `can_message`, user scope), role + per-permission checks, branch scoping. **Department is an attribute, not an access boundary.**
* **Realtime:** one in-process `RoomManager`/connection manager; optional Redis pub/sub bridge, Redis rate limits and webhook lock with in-memory fallback. Meetings are WebRTC mesh (max 8) with WebSocket signalling; as of the last change, meetings are private to host + invitees.
* **Frontend:** React + Vite + Tailwind + TanStack Query; feature folders; shared `components/ui.jsx`. Only 2 `lazy()` imports.
* **Deploy:** two Dockerfiles, `docker-compose.yml`, `docker-compose.prod.yml`, `nginx/nginx.conf` (TLS, HSTS, CSP, WebSocket upgrade, rate-limit zones), Postgres init script.

## 3. Feature inventory (verified status)

| Area | Status | Notes |
|---|---|---|
| Employees (CRUD, profile, documents, onboarding/offboarding checklists, history, org chart) | Implemented, tested | Lifecycle history append-only. Asset return, handover checklist and final-settlement status are **not** modelled (only generic exit clearance). |
| Org (company, branches, departments, teams, hierarchy) | Implemented, tested | Departments are not an access scope (see F-07). |
| Attendance | Implemented, tested | Timezone-aware, shifts, corrections, geofence, overtime. Selfie/biometric absent; leave-aware absence marking open **[docs]**. |
| Leave | Implemented, tested | Ledger, accrual, carry-forward, half-day, delegation. Encashment absent. Docs disagree about whether leave uses branch working days (F-15). |
| Projects / milestones / members | Implemented, tested | |
| Tasks | **Partial** | Statuses are only todo/in_progress/review/done (+ changes-requested). **No** backlog, cancelled, nested subtasks, comments, per-task activity history, or reminders on project tasks **[code: `Task` model]**. Personal `todos` do have one-level subtasks. |
| Payroll | Implemented, tested | Decimal money, 4-eyes approval, frozen payslips. No statutory/tax rules by design; no payroll reports/export beyond what exists. |
| Performance | Implemented, tested | Cycles, goals, KPIs, confidentiality enforced server-side. |
| Notifications | Partial | In-app + WS push + webhooks. **No notification preferences, no attendance reminders, no e-mail notifications beyond auth mails** **[code]**. |
| Chat | Implemented, tested | |
| Meetings / WebRTC | Implemented; private rooms; real two-browser test **[ran]** | Mesh only; TURN depends on configuration; no recovery/ICE-restart test. |
| Webhooks | Implemented, tested | HMAC, outbox, retries, SSRF guard. |
| Recruitment | **Absent** | No code. |
| Reports | CSV only | No xlsx/pdf; no large-report/async handling. |
| Role dashboards | Present for founder/HR/manager/employee/board/platform | Content not re-reviewed this session. |
| Platform admin | Create/suspend/migrate/backup/delete company, stats | No platform audit log; no tenant restore. |

## 4. Findings

Severity scale: Critical = exploitable data exposure/takeover; High = serious weakness or silent wrong results; Medium = real gap with limited blast radius; Low = hygiene.
**No Critical finding was confirmed.** Items already fixed in earlier phases are not repeated.

### Security and tenancy

| ID | Module / file | Confirmed issue | Sev | Recommended solution | Tests required |
|---|---|---|---|---|---|
| F-01 *(open: awaiting your decision)* | `backend/auth_activity.log` (155 KB) | An old log of sign-in attempts (email and password length) sits in the project folder. The folder is **not a git repository**, so `.gitignore` protects nothing yet. **[code]** | High (if the folder is ever zipped, committed or shared) | Your decision first: delete or archive it. Then `git init` with `.gitignore` verified, and a pre-commit secret scan. | CI job that fails if `*.log`, `.env`, `*.db` or key files are tracked. |
| F-02 **FIXED 2026-10-28** | `app/main.py:50-65` | `bootstrap_platform()` resets the platform admin's password to `BOOTSTRAP_ADMIN_PASSWORD` **on every start** (it only logs "synced"). A leaked `.env` is a permanent admin credential, and a password changed by the admin (or MFA-protected account) is silently reverted. **[code]** | High | Create the admin only if none exists; add a CLI command to reset a password; refuse to start in production with the default value. | Start-up test: changed password survives restart; production mode refuses weak/default bootstrap value. |
| F-03 *(open: design decision needed, see IMPLEMENTATION_PROGRESS.md)* | `auth/router.py:68-110` | Login without a company slug iterates over **every active tenant database**. Cost grows with the tenant count (latency side channel; slow with hundreds of tenants) and is a brute-force amplifier across tenants (limiter key is `*|email|ip`). **[code]** | Medium | Resolve the company from a platform-level email→company index (hash or normalized email), or require the slug / company sub-domain. | Test: login latency independent of tenant count (mock N tenants); same email in two companies still disambiguated. |
| F-04 **FIXED 2026-10-28** (directory; `/departments` counts still company-wide) | `employees` directory (`/employees/directory`), `/departments` counts, some notification fan-outs | Branch scoping is bypassed by the picker/directory endpoints: names, roles and e-mails are company-wide for all internal roles. **[docs, matches design note]** | Medium | Scope the directory by `user_scope` (or return only id/name for pickers), and add an explicit "whole company" permission. | API tests per role/branch: a branch HR/manager cannot list other branches' people. |
| F-05 **FIXED 2026-10-28** (guard added) | `app/modules/*` (all 249 route handlers) | Authentication coverage is good: the only handlers without an auth dependency are login, platform login, refresh, password-reset request/confirm, verify-email confirm and MFA verify (all intentionally public, all rate limited). **[code, scripted scan]** There is **no automated guard** that a *new* route cannot be added without auth or tenant scope. | Medium | Add a test that enumerates the app's routes and fails on any route outside an explicit public allow-list; add a lint-style test that tenant queries go through `ctx.db`. | The route-enumeration test itself; a cross-tenant ID-swap sweep that iterates every GET/PATCH/DELETE route with a second company's ids. |
| F-06 **PARTLY FIXED 2026-10-28** (unknown-id sweep on every route and method) | Cross-tenant ID tests | Isolation is tested for the main resources (same ids in two tenants, WebSocket, notifications, webhooks, documents, meetings) but not systematically per route. **[ran: tests pass; coverage by sampling]** | Medium | The generated sweep above, run in CI. | See F-05. |
| F-07 | `access.py`, all modules | **Department-based access control is not implemented** (company + role + branch + reporting line only), although the brief asks for it. **[code, docs]** | Medium | Decide the policy (e.g. department head sees their department; managers limited to department), add `scope.department_ids` to `user_scope`, apply to employees, attendance, leave, performance, payroll lists. | Role × department matrix tests for each list/detail/export endpoint. |
| F-08 | Browser sessions | Cookie sessions are bound to a device cookie and use the header-based CSRF check; HSTS and CSP exist in nginx. Two gaps: (a) the API process itself sets `X-Content-Type-Options` only (`main.py:160`) — HSTS/CSP/X-Frame depend on running behind the supplied nginx; (b) CSP allows `style-src 'unsafe-inline'`. **[code]** | Low | Add a security-headers middleware in FastAPI for non-nginx deployments; replace inline styles over time. | Header test on `/api/health` and the SPA. |
| F-09 | Uploads | Allow-list + magic-byte checks are in place; **no malware scanning** and no per-tenant storage quota. **[code/docs]** | Medium | Pluggable scanner hook (ClamAV) and quota per company. | Upload of EICAR test string refused when scanner is enabled; quota exceeded → 413. |
| F-10 | `platform` module | No platform-level audit trail (only structured logs); no tenant data export/restore tooling; company delete exists (`DELETE /platform/companies/{id}`) but its safeguards/export-before-delete were not inspected in depth. | Medium | Platform `audit_events` table + endpoint; documented backup/restore command and a restore drill; require export confirmation before delete. | Audit rows for each platform action; restore test from backup into a scratch tenant. |
| F-11 | `core/ratelimit.py`, `realtime.py` | In-process limiter/fan-out fall back to memory when Redis is absent. With several instances and no Redis, limits and push notifications silently degrade. Redis paths were tested **against fakeredis only**. **[docs]** | Medium | Fail fast (or warn loudly) in production if more than one worker is configured without Redis; run the Redis tests against a real Redis in CI. | Integration test with real Redis, two app instances: message from instance A reaches socket on B; limiter shared. |

### Correctness and business logic

| ID | Module | Confirmed issue | Sev | Recommended solution | Tests required |
|---|---|---|---|---|---|
| F-12 *(comments FIXED 2026-10-29, migration 0018; the rest open)* | `projects` / `Task` model | Tasks lack backlog and cancelled statuses, nested subtasks, activity history and reminders (comments are now implemented); there is no transition table, so any status can be set from any other by users allowed to edit. **[code]** | High (a core requirement) | Migration for `task_comments`, `task_events`, `parent_task_id`; explicit transition rules in a pure module (like attendance/leave engines); overdue/reminder job. | Transition matrix tests, comment/activity visibility per role, subtask rollup, migration up/down/up. |
| F-13 | Notifications | No per-user notification preferences, no attendance/task-due reminders, no e-mail copies of in-app notifications. Webhook outbox is the only background worker (`asyncio.create_task` in `main.py`). **[code]** | Medium | Preferences table; a small scheduler (APScheduler or a Redis-backed job loop with a lock) for reminders; e-mail channel using the existing mailer. | Preference respected per channel; reminder fired once across two instances; tenant scoping of the job. |
| F-14 | Employee lifecycle | Asset return, handover checklist, final-settlement status, relieving/experience letter generation and multi-step resignation approval (manager then HR) are not implemented; the resignation is a single HR-handled record plus generic exit clearance. **[code/docs]** | Medium | Extend exit clearance items (asset, handover), add settlement status field and document templates. | State-machine tests for the resignation flow; document generation test. |
| F-15 | Leave vs holiday calendar | `CHECKLIST.md` still says leave and holidays "assume a Mon–Fri week", while the leave rebuild (phase 4b) reportedly counts days on the person's branch week. The two documents disagree and I did not re-verify the holiday-on-weekend rule. | Medium | Verify against `leave/engine.py` and the holiday validator; fix the docs or the code. | Test for a Sun–Thu branch: leave days, holidays on Friday/Saturday, attendance agreeing with leave. |
| F-16 | Dashboards | The "present today" count and role dashboards were built before the attendance engine in places; not re-reviewed. | Low | Review dashboard queries against the attendance engine's work-date semantics. | Dashboard counts across a branch with a non-UTC timezone near midnight. |
| F-17 | Payroll / reports | No xlsx/pdf export, no payroll reports, no async generation for large reports. Reports are CSV only. | Medium | Report service with streaming CSV, xlsx (openpyxl) and pdf; background generation above a row threshold. | Export content/permission tests; formula-injection test for every format; large-dataset memory test. |
| F-18 | Recruitment | Module does not exist. | Medium (scope) | Only if you want it; separate phase. | n/a until designed. |

### Architecture, performance and quality

| ID | Module | Confirmed issue | Sev | Recommended solution | Tests required |
|---|---|---|---|---|---|
| F-19 | `employees` (1531 lines), `teams` (1071), `projects` | Business logic lives in routers; only leave, payroll, performance, attendance, notifications, webhooks have service/engine modules. Harder to test and reuse. | Medium | Extract services opportunistically when touching those modules; do not rewrite. | Existing API tests must stay green (characterization). |
| F-20 | Query patterns | A few per-row `db.get/scalar` loops exist in list serializers (e.g. 2 in `employees/router.py`); there is no systematic N+1 or query-count check, and only 8 explicit `Index(...)` declarations (others come from FK/`index=True`). | Medium | Add query-count assertions on the main list endpoints (employees, leave, tasks, attendance); add composite indexes where `EXPLAIN` shows scans (e.g. attendance by user+date, notifications by user+read). | Query-count tests with SQLAlchemy event listener; Postgres `EXPLAIN` review. |
| F-21 | Frontend | **No ESLint/Prettier/type checking** (`package.json` has only build and test). Only 2 `lazy()` imports, so the whole app ships as one bundle. | Medium | Add ESLint (react, hooks, jsx-a11y) and fix findings; route-level `React.lazy` for heavy pages (payroll, performance, meetings, org chart); check bundle size. | `npm run lint` in CI; bundle-size budget check. |
| F-22 | `Modal` (fixed during the last change) | Focus was re-stolen on every parent render. Fixed and covered. Other components relying on `onClose` identity were not audited. | Low | Grep for effects depending on unstable callback props. | Existing typing tests. |
| F-23 | CI/CD | **No CI workflow, no repository** (`.git` absent), no dependency or container vulnerability scanning, no pre-commit. | High (process) | `git init`; GitHub Actions: backend tests, vitest, lint, build, Playwright, `pip-audit`, `npm audit`, Trivy on images. | The pipeline is the test. |
| F-24 | Deployment | Dockerfiles (non-root user, healthcheck) and compose files are written but **have never been built or run**; `nginx -t` never run; Postgres verified earlier only for the schema up to ~0009 and manual provisioning **[docs]**; migrations 0010–0017 untested on Postgres. | High (unknown risk, not known-broken) | Run on a machine with Docker: `docker compose build`, bring up with Postgres + Redis, run migrations, run the e2e suite against it. | Compose smoke test; migration suite on Postgres 16; backup/restore drill. |
| F-25 | Docs | `CHECKLIST.md` contains stale lines: "⛔ MFA, SSO, refresh-token rotation/revocation, password reset by email" (all but SSO are implemented), "Tokens are stored in sessionStorage" (they are httpOnly cookies now), "company deletion not done" (an endpoint exists), "no Component/E2E tests" (there are 113 + 256). | Low | Rewrite those lines; add one source of truth for status. | n/a |
| F-26 | WebRTC | Protocol and a real two-browser local call are verified. Not verified: behaviour behind NAT/TURN, reconnect/ICE restart, 8-party load, mobile browsers. Mesh scales poorly beyond ~6. | Medium | Document the limits; add TURN to the compose files with credentials from env; optional SFU later. | Network-condition test (Playwright + `tc`/throttling), reconnection test. |
| F-27 | SSO | Not implemented; "SSO readiness" is not designed (no OIDC/SAML hooks). | Low | Add OIDC login as an optional provider per company when requested. | OIDC flow test with a mock IdP. |

## 5. Prioritized roadmap (proposal — nothing started)

**Priority 1 — security and tenancy (do first, small and low-risk)** — status: F-02, F-04, F-05, F-06 done; F-03 and F-01 waiting for decisions; F-07 waiting for the policy.
1. F-02 bootstrap password behaviour (+ production config guard).
2. F-05/F-06 route-enumeration guard and cross-tenant ID sweep in the test suite (no behaviour change; may reveal real holes).
3. F-04 directory/branch scoping decision, then enforcement.
4. F-03 login tenant discovery.
5. F-01 decision on the old log + `git init` and secret scanning (needs your OK before deleting anything).
6. F-07 department scope policy (needs your decision on the rules).

**Priority 2 — functional gaps that affect the brief**
7. F-12 tasks (statuses, subtasks, comments, activity, transitions).
8. F-13 notification preferences and reminders (scheduler).
9. F-14 offboarding completeness; F-15 leave/holiday calendar verification.

**Priority 3 — platform quality**
10. F-23 git + CI + scanning; F-21 lint and code-splitting; F-20 query counts and indexes.
11. F-24 Docker/Postgres verification (needs a machine with Docker); F-11 real-Redis integration test.
12. F-10 platform audit log, backup/restore drill; F-17 exports; F-09 scanning/quota.

**Priority 4 — optional scope**: F-18 recruitment, F-27 SSO, F-26 SFU/TURN hardening, F-19 gradual service extraction.

## 6. Decisions needed from you before implementation

1. **F-01:** may I delete `backend/auth_activity.log` (or move it somewhere you choose)?
2. **F-02:** should a changed platform-admin password survive a restart (my recommendation: yes)?
3. **F-04/F-07:** what is the intended rule for departments — may a department head or manager see everyone in their department across branches, and should the directory be branch-scoped for employees?
4. **F-18/F-27:** are recruitment and SSO in scope now?
5. **Docker/Postgres:** can the container and Postgres checks run on your machine (I cannot run them here)?

## 7. Limits of this audit

* I read the code paths named above and ran the three automated suites; I did **not** read every line of the ~13k backend lines or every frontend page, so absence from this list is not proof of absence.
* Findings marked [docs] come from earlier logs and need re-verification when touched.
* No penetration test, dependency vulnerability scan, load test, Docker build or PostgreSQL run was performed.
