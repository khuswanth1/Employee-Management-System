# Test plan — WorkSphere

No `replica/recon.md` exists (this is the user's own app, not a clone), so the flows below were derived from the router (`frontend/src/App.jsx`), `lib/nav.js` and the README role table.
Tests run against an isolated stack (`e2e/start-backend.mjs`: temp SQLite, port 8100; Vite on 5273). The real `.env`, Postgres and SMTP are never used.
Run: `cd e2e && npx playwright test`.

Legend: **A** automated, **M** manual (not done yet), **—** not covered yet.

| Flow | Case | What | How |
|---|---|---|---|
| F01 Sign in/out | H1 founder signs in, dashboard, axe | A (fails: B-001) |
| | H2 platform admin → /platform | A |
| | H3 refresh keeps session; tokens only in sessionStorage | A |
| | H4 sign out, protected pages redirect | A |
| | E1 deep link → login → back | A |
| | E2 emoji + 300-char email | A |
| | E3 double click Sign in | A |
| | E4 keyboard only | A |
| | E5 phone width + axe on login | A |
| | N1 wrong password | A |
| | N2 empty form | A |
| | N3 unknown user vs wrong password same message | A |
| | N4 lockout after 5 failures (429) | A |
| | N5 platform login really verifies password (production mode) | A |
| | N6 same under `ENVIRONMENT=development` | manual repro, fails: B-002 |
| F02 Roles | H founder/hr/manager/employee menus | A |
| | N1 employee on /webhooks | A |
| | N2 API 403 for employee on privileged endpoints | A |
| | N3 HR cannot create founder | A |
| | N4 no/garbage token → 401 | A |
| | N5 refresh token not usable as access token | A |
| F03 Employees | H1 add employee | A |
| | E1 emoji/accents/long name | A |
| | E2 double click Create → one record | A |
| | E3 axe + phone width | A |
| | N1 duplicate email | A |
| | N2 empty form | A |
| | N3 password > 12 chars | A |
| | E-photo upload, edit, offboard, delete | — |
| F04 Attendance | H1 check in / break / check out | A |
| | E1 double click, refresh | A |
| | E-timezone / DST, overnight shift | — |
| F05 Daily update | H1 submit | A |
| | E1 draft survives reload | A |
| | N1 empty, N2 hours 99 | A |
| | E-two tabs editing same day | — |
| F06 Leave | H1 apply → manager approves → employee sees approved | A |
| | N1 end before start | A |
| | N2 self-approval refused | A |
| | N3 overlapping request | A |
| | N-reject, cancel, insufficient balance, holiday/weekend | — |
| F07 Projects/tasks | H1 employee sees own project + task | A |
| | N1 non-member cannot list project | A |
| | N2 employee cannot create project | A |
| | E1 manager creates project (emoji) | A |
| | task status/dependencies/blockers, project delete | — |
| F08 Tenant isolation | N1–N4 API lists, id guessing, forged hints, UI | A |
| F09 Teams, branches, board, escalations, chat, webhooks, meetings (WebRTC), notifications, backups | — (covered by backend pytest only; needs e2e) |
| Cross-cutting | offline, slow network, expired session mid-use, screen-reader pass, remaining pages' axe scans | — / M |

## Startup / migration (found while testing)
Existing dev databases: tenant migration 0003 on a DB that already has `avatar_name`; platform/tenant `env.py` under SQLAlchemy 2.1.5. See B-003, B-004.

## Added in the complete pass
| Flow | Cases | How |
|---|---|---|
| F01 | H3 session survives tabs/refresh, no token readable by the page; H5 session copied to another browser rejected; H6 two browsers, two accounts | A |
| F09 | platform admin deletes a company (type-the-slug); duplicate slug 409 | A |
| F10 | every reachable screen for founder, HR, manager, employee, board member, platform admin: renders, no 5xx/console errors, axe, no horizontal scroll at 375px (79 combos) | A |
| F12 | tasks: lifecycle, non-member blocked, bad input, self-dependency | A |
| F13 | teams: create, leader/member rights, one team per person, employee cannot create | A |
| F14 | escalations: raise → escalate → resolve, raiser cannot resolve, privacy | A |
| F15 | chat: DM manager, unread, founder-DM block + exception, blank/oversize, outsiders | A |
| F16 | webhooks: HTTPS ok, secret shown once, SSRF guard (http/localhost/private/metadata/ftp/js), founders only | A |
| F17 | notifications created and read, not readable by others | A |
| F18 | leave reject/cancel, past date refused | A |
| F19 | profile edit (UI), change password, weak/wrong password, profile cannot change role/email, HR reset | A |
| F20 | offboard locks out immediately, last founder protected, HR cannot touch founder, history blocks delete | A |
| F21 | branches (dup code, delete with people), non-founders refused, board sees aggregates only, manager permission off → 403 | A |
| F22 | CSV export + formula injection, employees blocked from CSVs, paging/SQL/unicode never 500, XSS rendered as text, HTML upload refused, security headers | A |
| F23 | manager reviews update, one update per day, attendance double check-in/out | A |
| Backend pytest | browser-bound session (8), dev-login bypass regression (2) | A |

Still not automated: WebRTC meetings, real email, Postgres mode, backup/restore, two-tab edit conflicts, offline/slow network, DST/time zones, screen-reader pass by hand.

## Added for the profile, department/branch and project/task enhancements
| Flow | Cases | How |
|---|---|---|
| F25 | project/task fields: type, labels, hours round-trip; changes need a comment; invalid input never 500; restricted vs company visibility | A (API) |
| F26 | HR saves employment details (persist, axe); employee edits own restricted details and manager never sees them; upload a document with type and expiry, owner cannot verify, HR verifies; invalid values and foreign profiles refused; unlisted sort column refused | A (UI + API) |
| F27 | HR creates a department with code, marks inactive (axe); duplicate code error stays in dialog; cycles and non-HR writes refused; founder fixes a bad timezone beside the field; branch manager must be in the branch | A (UI + API) |

Result of the last full run: backend 206, frontend 29, e2e 205 (all passed). Bugs this pass: B-011 (S2), B-012 (S3), B-013 (S3), all fixed. Open: B-006.
Still not covered: Postgres, Docker/Nginx, two-tab conflicts, offline/slow network, DST, WebRTC, real email, screen-reader pass.

## Edge cases on the new screens (F28, second pass)
| Case | What | How |
|---|---|---|
| F28-E1 | 375px: employee page (all 5 tabs), departments, branches and the branch dialog have no sideways scroll; axe | A |
| F28-E2 | keyboard only: Enter opens a list row; arrow keys / End move between profile tabs | A |
| F28-E3 | offline save: message shown, typed value kept, saving works after reconnecting (B-014) | A |
| F28-E4 | session expires mid-edit: next save goes to sign-in, no 5xx, nothing saved | A |
| F28-E5 | two tabs: different sections both persist; the same field is last-write-wins, no errors | A |
| F28-E6 | double-click Save: exactly one change and one audit event (B-015) | A |
| F28-N1 | emoji, accents and CJK stored intact; 5000-character value refused with 422 | A |
| B-006 | wrong ENCRYPTION_KEY: error outside development, recovery only in development | A (backend) |

Last full run: backend 210, frontend 29, e2e 212, all passed. Bugs this pass: B-014, B-015 (S3), B-006 fixed. No S1 or S2 open.
Still not covered: Postgres, Docker/Nginx, daylight saving / time zones, WebRTC, real email, a hand screen-reader pass, optimistic-lock conflicts (two tabs are last-write-wins by design today).
