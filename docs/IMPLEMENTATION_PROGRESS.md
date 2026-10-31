# Implementation progress (audit-driven work)

Tracks work done against `docs/PROJECT_AUDIT.md`. Older phase logs stay in `docs/IMPLEMENTATION_PLAN.md`.

## Priority 1 — security and tenancy (started 2026-10-28)

| Finding | Status | What changed | Verified by |
|---|---|---|---|
| F-02 bootstrap admin | **Done** | `bootstrap_platform()` creates the platform admin only when none exists and never rewrites its password, status or MFA on later starts. In production the first password must satisfy the password policy or start-up fails. New break-glass script `backend/scripts/reset_platform_admin_password.py` (password read from a prompt, ends all sessions). **Behaviour change:** changing `BOOTSTRAP_ADMIN_PASSWORD` in `.env` no longer changes an existing admin's password. | `tests/test_bootstrap_admin.py` (3 tests) |
| F-05 route guard | **Done** | Test that walks every route (including those behind `include_router`, which newer FastAPI hides in lazy objects) and fails for any route without `get_ctx`/`get_platform_admin` unless listed in an explicit `PUBLIC` allow-list with a reason; a canary asserts the walk sees >250 routes; WebSocket routes pinned; no non-platform route may accept a tenant/company selector from the client. | `tests/test_route_guard.py` |
| F-06 unknown-id sweep | **Done (partial)** | Every route and method with a path id is called with ids that exist nowhere, as a signed-in founder: it must answer 4xx, never 2xx or 5xx. Without a token every protected route must answer 401. Result: **no hole found.** Not covered: a generated sweep using real objects of company A against company B (each company has its own database, so the existing isolation tests remain the evidence there). | same file |
| F-04 directory scope | **Done** (directory only) | `GET /employees/directory`: founders see everyone; others see their own branch plus branch-less people (the founder), never board members; employees get no e-mail or employee code for anyone but themselves. Company-wide HR/managers (no branch) keep the full list. `/departments` counts are still company-wide (counts only). | `tests/test_directory_scope.py` (6 tests) and the existing org, permission, chat, isolation and lifecycle tests |
| F-03 login tenant lookup | **Not started: needs your decision** | A real fix needs either a platform-level email-to-company index kept in sync wherever users are created, renamed or deleted (new migration plus hooks), or making the company name/sub-domain mandatory at sign-in (UX change). The current behaviour keeps working. | n/a |
| F-01 old log file | **Waiting for you** | Not touched. | n/a |
| F-07 department scope | **Waiting for the policy** | Not started. | n/a |

## Test results for this block
Actually run on 2026-10-28 after the Priority 1 changes:
* Backend `pytest`: 476 passed, 0 failed.
* Frontend `vitest`: 113 passed.
* Playwright: 255 passed, 1 failed (`f24-todos F24-H1`, reproduced twice). The test expects a "Time left" summary on My Tasks that is no longer in `frontend/src/features/todos/TodoPage.jsx` (that file was edited at 23:02 on 2026-10-28, not as part of this work; the string only survives in the old `dist` build). The test or the page needs aligning by whoever made that change; I did not alter either.

## Bug-fix sweep (2026-10-29)
See `docs/BUG_FIXES.md` for the full table. New in this block: a refused-request and overflow sweep over every menu page and role (no issue found), task comments (migration 0018), colleague cards and a read-only People directory, the attendance stale-session fix, a manager-permission-aware menu, one-clock date handling, leave approval dialog errors, the modal focus fix and keyboard-reachable tables.
