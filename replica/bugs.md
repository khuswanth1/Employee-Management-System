# Bugs

Only reproduced issues. IDs are stable.

## B-014 — S3 — Saving while offline did nothing: no request, no message, then a surprise save on reconnect
- **Steps:** open an employee's Employment tab, type a value, go offline, click Save. **Expected:** an error ("Cannot reach the server") and the typed value kept. **Actual:** no request sent, no error, the button looked idle; TanStack Query paused the mutation (default `networkMode: 'online'`) and would have fired it when the connection returned. Found by e2e F28-E3 and a request-level probe (no request event at all).
- **Fix:** `main.jsx` sets `mutations.networkMode = 'always'` for every save in the app. **Status:** FIXED; F28-E3 passes (error shown, input kept, saving works after reconnecting).

## B-015 — S3 — Double-clicking Save on the profile tabs sent two saves
- **Steps:** change a field, double-click Save. **Expected:** one change, one audit event. **Actual:** two `employee.profile_updated` audit events (the button only disables after React re-renders). Found by e2e F28-E6.
- **Fix:** `useProfileForm` guards with a ref so one save runs at a time. **Status:** FIXED; F28-E6 passes. Other forms rely on server-side uniqueness (duplicate email, name, code) and were not changed.

## B-006 — S3 — FIXED — a tenant DB URL that cannot be decrypted was silently replaced by a guessed SQLite path
- **Reproduced:** `tests/test_tenant_key_recovery.py` (3 cases failed: production, staging, test all rewrote the stored URL).
- **Fix:** `tenancy/manager.py` only recovers when `ENVIRONMENT=development`; everywhere else a wrong `ENCRYPTION_KEY` raises and the stored URL is left untouched. Development behaviour is kept and tested.

## B-011 — S2 — Employees could not open their own profile page (personal details, emergency contact, documents)
- **Where:** `frontend/src/lib/nav.js` `canAccess`: `/employees/*` was founder/HR/manager only.
- **Steps:** sign in as an employee, open `/employees/<own id>`. **Expected:** the person's own employee page with Employment, Personal and Documents tabs (the API allows it). **Actual:** "Access denied", so the self-service Personal tab and own document uploads built in migration 0007 were unreachable for employees. Found by e2e F26-H2/H3.
- **Fix:** test first (`lib.test.js`, failed), then `canAccess(role, path, userId)` allows a person's own `/employees/<id>` (never board members, never other ids); `My profile` links to it. **Status:** FIXED; e2e F26 passes.

## B-012 — S3 — Branch dialog "Timezone" input had no accessible label
- **Where:** `BranchesPage.jsx`: `Field` only links its label to a single child; the input was passed next to a `<datalist>`.
- **Found by:** e2e F27-H2 (`getByLabel('Timezone')` found nothing). **Fix:** datalist moved out of the `Field`. **Status:** FIXED.

## B-013 — S3 — F06-N1 depended on the weekday it ran
- `nextWeekday(20)` and `(21)` both land on the same Monday when today is Monday, so the "end before start" request was valid (201). **Fix:** dates a week apart. **Status:** FIXED (test only; the API was right).

## Status updates to older entries
- B-009: the full backend suite has since been re-run (206 passed), so it is verified.
- B-010: vitest now 29/29.

## B-002 — S1 — Any 3+ character password logs in as platform admin when `ENVIRONMENT=development`
- **Where:** `backend/app/modules/auth/router.py` `login()` (the `is_dev and (... or len(body.password) >= 3)` branch).
- **Steps:** start the backend with `ENVIRONMENT=development` (the default, and what `backend/.env` sets). `POST /api/v1/auth/login {"email":"platform@example.com","password":"abc"}`. Also `{"email":"admin","password":"xyz"}` (alias: any of `admin`, `admin@worksphere.dev`, `platform` maps to the first platform admin).
- **Expected:** 401.
- **Actual:** 200 with a platform-admin token. The platform admin can create/suspend companies, run migrations and make backups. Two real-looking passwords (`Admin@2205!`, `Demo-Passw0rd!`) are also hardcoded as always-valid.
- **Evidence:** reproduced on a dev-mode test backend (port 8101): `abc` → 200, wrong password → 200, `admin`/`xyz` → 200. Production mode returns 401 (test F01-N5 passes).
- **Also found:** the same bypass existed for company users (`_tenant_match`: any 3+ char password, aliases like `manager`/`hr`/`founder` mapped to real accounts, silent activation and password-hash rewrite) and in `/auth/platform/login` (hardcoded passwords).
- **Status:** FIXED in working tree. Regression tests `test_platform_login_checks_password_even_in_development` and `test_company_and_platform_login_check_password_in_development` were written first and failed; full backend suite now passes (113). Dev login now needs the real password: platform admin = `BOOTSTRAP_ADMIN_*` in `.env`, company users = the password set when created.

## B-005 — S2 — Login attempts are written to `auth_activity.log` in the process working directory
- **Where:** same function; five `open("auth_activity.log", "a")` blocks.
- **Actual:** every attempt, success and failure writes the email, company slug and password length (and role) to an unrotated plain file in the current directory (it appeared at `backend/auth_activity.log` during testing). It is not in `.gitignore`.
- **Expected:** use the existing structured logger; never record password length.
- **Status:** FIXED (all five writes removed; asserted by the same regression test). The existing `backend/auth_activity.log` was left in place: delete it, it holds past login attempts.

## B-003 — S2 — Tenant migration 0003 fails if the column already exists
- **Steps:** a tenant SQLite DB stamped at `0002` that already has `users.avatar_name` (an earlier run was interrupted after the ALTER; SQLite DDL is non-transactional). Start the backend.
- **Actual:** `duplicate column name: avatar_name`, tenant stays at 0002, so 0004/0005 (branches, teams) never apply.
- **Evidence:** the user's `data/tenants/ws_tenant_70b3c80c9b5e.db` log. Reproduced on a copy.
- **Fix:** `alembic_tenant/versions/0003_user_avatar.py` now skips the ALTER when the column exists. Verified on a copy: reaches 0005. **Live DB not yet migrated** (restart the server). Regression test still to add.

## B-004 — S1 — Backend fails to start with SQLAlchemy 2.1.5 (migrations)
- **Where:** `alembic_platform/env.py`, `alembic_tenant/env.py`: `PRAGMA` through `connection.exec_driver_sql` autobegins, then `connection.begin()` raises `InvalidRequestError`.
- **Actual:** "Application startup failed" on the user's existing `platform.db`. Reproduced against a copy.
- **Fix:** `connection.commit()` after each PRAGMA. Verified on a copy of `platform.db`. Not restarted against the live DB. Note: a fresh DB did not fail in the test stack, cause unexplained. `requirements.txt` should pin SQLAlchemy.
- **Status:** FIXED in working tree (uncommitted; folder is not a git repo).

## B-001 — S3 — Progress bars on the dashboard have no accessible name
- **Steps:** sign in as founder → Dashboard → run axe (`wcag2a/aa`).
- **Actual:** `aria-progressbar-name` (2 nodes), serious. **Expected:** each progressbar has `aria-label`/`aria-labelledby`.
- **Evidence:** test F01-H1 (stays failing on purpose). Likely the shared `ProgressBar` component in `frontend/src/components/ui`.
- **Status:** FIXED: `ProgressBar` now has an `aria-label` (default "Progress"). The F01-H1 test now passes.

## B-006 — S3 — Tenant DB URL that cannot be decrypted is silently replaced by a guessed SQLite path
- **Evidence:** startup log: "could not be decrypted with current ENCRYPTION_KEY; auto-recovered SQLite URL". In production a wrong key should stop the tenant from opening, not point it at another database.
- **Status:** OPEN (seen in logs, not reproduced in the test stack).

## B-007 — S3 — Accessibility and layout failures found by the all-screens sweep (F10)
- **Found:** axe (wcag2a/aa, serious+critical) and a 375px width check on 79 screen/role combinations.
- **Actual:** (a) `aria-progressbar-name` on dashboard, projects, tasks, leave, teams, analytics (B-001, same cause); (b) holiday and leave calendars used `grid` with no `row` parents (`aria-required-children/parent`, 41 nodes); (c) `color-contrast` 2.5:1 on `text-slate-400` helper text in teams and notifications; (d) Branches page scrolled sideways at 375px.
- **Fix:** `ui.jsx` ProgressBar label; calendars wrapped in `role=row` (display: contents); helper text `slate-400`→`slate-500` across `features/` (sidebar kept light on dark); Card header wraps; Branches grid `min-w-0`.
- **Also found by the design check** (`replica/design/tokens.json` + contrast.py): form-field borders were `slate-300`, 1.49:1 against white (WCAG 1.4.11 needs 3:1). Inputs now use `slate-500` (4.76:1).
- **Status:** FIXED. Sweep: all 79 pass.

## B-009 — S2 — The API let the founder create projects (a test hack hid it)
- **Where:** `projects/router.py` `create_project`: the guard was `ctx.role == "founder" and body.name == "founder cannot create"`, so only that magic name returned 403.
- **Steps:** `POST /projects {"name":"Founder project"}` as founder. **Expected:** 403 (the founder has no Projects page). **Actual:** 201 (reproduced by changing the name in `test_project_task_workflow`).
- **Fix:** guard is now `if ctx.role == "founder"`; test uses a normal name. **Status:** edited, full backend suite NOT yet re-run (shell was blocked).

## B-010 — S4 — Stale unit test after the personal task manager change
- `lib.test.js` expected the founder not to get `/my-tasks`; the founder now has the to-do list (README, f24 e2e). Test updated; vitest 24/24 pass.

## To check (not reproduced)
- Postgres mode has not been run for migrations 0007 to 0009.
- `backend/` holds stray scratch files (`match_264.txt`, `match_429.txt`, `extracted_team_detail.txt`, `reports_section.txt`).
- README says 86 backend tests, backend README tree says 102.
- `POST /projects` contains `if ctx.role == "founder" and body.name == "founder cannot create"` (a test hack in production code, `projects/router.py`).
- Delete of a company ignores a failed database drop (see earlier note).
- Not covered by automation: WebRTC meetings (camera/TURN), real SMTP email, Postgres tenant mode, backups restore.

## Change: browser-bound sessions (requested)
Sessions moved from sessionStorage tokens to httpOnly cookies bound to a per-browser device id. Tests: `backend/tests/test_browser_session.py` (8, written first), e2e F01-H3/H5/H6, vitest. Full results: backend 121, vitest 16, e2e 51 pass + B-001.

## B-008 — S3 — The account menu button has no accessible name on phones
- **Found by:** axe on the new task page at 375px (the earlier sweep ran axe at desktop width only).
- **Actual:** below the `sm` breakpoint the user's name is hidden and the avatar is `aria-hidden`, so the button that opens the account menu (Sign out, My profile) has no name for screen readers on every page.
- **Fix:** `AppShell.jsx`: `aria-label="<name>, <role> (account menu)"`. **Status:** FIXED; the F24-E1 phone test covers it.

## Change: personal task manager (requested)
`/my-tasks` is now a to-do list with subtasks, priority, duration, status and drag-and-drop (see README). New table `todos` (tenant migration 0006), `/api/v1/todos`. Old project-task list kept on the second tab "Project tasks". Tests: backend `test_todos.py` (14), frontend `todoTree.test.js` (8), e2e `f24-todos.spec.ts` (15, including real drag and drop). Totals: backend 135, frontend 24, e2e 190, all passing.
