# WorkSphere — multi-tenant employee & project management

WorkSphere lets many companies run on one platform, each with an **isolated PostgreSQL database**. It covers employees, projects and tasks, daily work updates, leave, attendance, dashboards, real-time notifications, signed webhooks and WebRTC meetings.

- **Frontend:** React 19, Vite, Tailwind CSS 4, React Router, TanStack Query, Recharts
- **Backend:** FastAPI, SQLAlchemy 2, Alembic, Pydantic 2, PyJWT, bcrypt
- **Data:** one central *platform* database plus one database per company
- **Infra:** Docker Compose, Nginx (TLS, WebSocket proxy), Uvicorn

> Read [CHECKLIST.md](CHECKLIST.md) for what is implemented, what is tested, and what is **not** verified yet.

## Repository layout

```
backend/
  app/
    core/        config, security (JWT, bcrypt, Fernet), errors, logging, rate limiting
    db/          models: platform_models.py (registry) and tenant_models.py (per-company)
    tenancy/     TenantManager (provision, migrate, engine cache) and tenant seeding
    modules/     auth, platform, employees, projects, updates, leave, attendance,
                 dashboard, notifications, webhooks, meetings, admin  (router + schemas [+ service])
    deps.py      request context: tenant + user resolved from the JWT, role guards
    realtime.py  WebSocket fan-out and WebRTC signaling rooms
  alembic_platform/  migrations for the registry DB
  alembic_tenant/    migrations applied to every company DB
  tests/       102 tests: auth, permissions, tenant isolation, workflows, realtime, migrations, chat, organisation, teams
  scripts/seed_demo.py
frontend/src/
  features/    auth, layout, dashboard, employees, projects, updates, attendance, leave,
               meetings (WebRTC), webhooks, admin, notifications, platform
  components/  UI kit (Button, Table, Modal, Pagination, Toasts, …)
  lib/         api client, hooks, role-based navigation
nginx/nginx.conf      production edge config      docker-compose.yml        local dev stack
docker/postgres/      role + database bootstrap   docker-compose.prod.yml   production-style stack
```

## Architecture

```
Browser ──HTTPS──> Nginx ──> static React build
                      └────> FastAPI (REST /api/v1, WS /api/v1/ws, WS /api/v1/meetings/ws/{room})
                                 │
                 ┌───────────────┴────────────────┐
          Platform DB (registry)           Company DBs (one per tenant)
          companies, platform admins       users, projects, tasks, leave, …
          Fernet-encrypted tenant DB URLs  own Postgres role + database
```

### How tenant isolation works

1. **The tenant comes only from the signed JWT** (`tid` claim). No header, query string or body field can select a tenant; the frontend never sends one.
2. On **every request** `deps.get_ctx` decodes the token, re-reads the company from the platform DB (so suspension is immediate), opens a session on *that company's* engine, and loads the user from *that* database. The user's role is read from the DB, not the token, so demotions and offboarding take effect at once.
3. Tenant DB URLs are **Fernet-encrypted** in the platform DB, decrypted only inside `TenantManager`, and never serialized into any API response.
4. In Postgres mode each tenant gets its **own role and database** (`REVOKE ALL … FROM PUBLIC`), so even a bug in application code cannot reach another tenant's tables with that connection.
5. WebSocket rooms and connections are keyed by `(company_id, …)`; WebSocket auth is a first message (`{"type":"auth","token":…}`), so tokens never appear in URLs or logs.
6. Tests (`tests/test_tenant_isolation.py`) prove it: identical numeric IDs in two companies never cross, forged tenant hints are ignored, the same email can exist in two companies, suspension affects only one tenant, and WebSocket/webhook/notification data stays inside its tenant.

### Database configuration & migrations

| Setting | Meaning |
|---|---|
| `PLATFORM_DATABASE_URL` | central registry DB |
| `TENANT_DB_MODE` | `postgres` (production) or `sqlite` (local dev and the test-suite) |
| `POSTGRES_ADMIN_URL` | role with `CREATEDB` + `CREATEROLE` — used **only** to provision tenants (not a superuser in the bundled compose files) |
| `ENCRYPTION_KEY` | Fernet key protecting tenant DB URLs. **Back it up**: without it tenants cannot be opened |

- The platform schema is migrated automatically at startup (`alembic_platform`).
- A new company is provisioned by `POST /api/v1/platform/companies`: generate names → create role + DB → run `alembic_tenant` → seed founder, leave types and settings → register. Any failure rolls back and drops the new database.
- After a deploy that adds a tenant migration run `POST /api/v1/platform/migrate` (UI: **Companies → Run migrations**) to upgrade all tenants.
- After editing models, generate the next revision (review it before committing):
  `python scripts/new_migration.py tenant "add task labels"` (or `platform`).
  `tests/test_realtime_integrations.py::test_tenant_schema_matches_models_and_is_at_head` fails if models and migrations drift apart.

### Browser storage

`frontend/src/lib/storage.js` wraps both stores (guarded, JSON, never throws; the app works without storage). **sessionStorage** (dies with the tab): per-tab view state such as the open tab of a team page. **localStorage** (survives closing the browser): list filters (teams, projects, employees) and unsent daily-update drafts, keyed per user (`ws.pref.<id>.*`, `ws.draft.<id>.*`). Drafts are removed after submitting and on an explicit sign-out; a session that merely expires keeps them so work is not lost. `usePersistentState` is the hook for new preferences.

## Local setup (no Docker, SQLite tenants)

Prerequisites: Python 3.12+ and Node 20+.

```bash
# 1. Backend
cd backend
python -m venv .venv
.venv/Scripts/activate            # Windows (use: source .venv/bin/activate on macOS/Linux)
pip install -r requirements-dev.txt
cp .env.example .env              # then fill SECRET_KEY, ENCRYPTION_KEY, BOOTSTRAP_ADMIN_* (commands are inside the file)
uvicorn app.main:app --reload --port 8000

# 2. Frontend (new terminal)
cd frontend
npm install
npm run dev                       # http://localhost:5173 (proxies /api and WebSockets to :8000)

# 3. Optional demo data
cd backend && python scripts/seed_demo.py --admin-email <BOOTSTRAP_ADMIN_EMAIL> --admin-password <BOOTSTRAP_ADMIN_PASSWORD>
```

Sign in at <http://localhost:5173>:

- **Platform admin:** click *Platform administrator?* and use the bootstrap credentials → create companies.
- **Company user:** company URL name (e.g. `acme`) + email + password. The seed script prints the demo accounts.

API docs: <http://localhost:8000/api/docs> (Swagger) and `/api/redoc`.

## Local setup with Docker (Postgres tenants)

```bash
cp .env.example .env     # fill every blank (commands to generate keys are in the file)
docker compose up --build
```

Frontend: <http://localhost:5173> · API: <http://localhost:8000/api/docs>. Postgres is bound to localhost only. `docker/postgres/init.sh` creates a platform role and a non-superuser provisioning role on first start.

## API usage

```bash
API=http://localhost:8000/api/v1

# platform admin: create a company (provisions its database)
TOKEN=$(curl -s $API/auth/platform/login -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"…"}' | jq -r .access_token)
curl -s $API/platform/companies -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"Acme","slug":"acme","founder_name":"Fiona","founder_email":"fiona@acme.com","founder_password":"Str0ng-Passw0rd"}'

# company user
T=$(curl -s $API/auth/login -H 'Content-Type: application/json' \
  -d '{"company_slug":"acme","email":"fiona@acme.com","password":"Str0ng-Passw0rd"}' | jq -r .access_token)
curl -s $API/dashboard -H "Authorization: Bearer $T"
```

Conventions: JSON bodies; list endpoints take `page`/`page_size` and return `{items,total,page,page_size}`; errors always look like `{"error":{"code","message","details"}}`; CSV exports under `/reports/*.csv`; refresh with `POST /auth/refresh`.

### Roles

| Capability | Platform admin | Founder | HR | Manager | Employee | Board member |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| Companies, tenant provisioning, backups, usage | ✔ | | | | | |
| Company-wide dashboard, projects (read), workload | | ✔ | | | | |
| Branches, branch managers (create, configure, permissions, teams), board members, chat exceptions | | ✔ | | | | |
| Employees (add, edit, delete, photo), departments, onboarding/offboarding, leave policy, holidays | | ✔ | ✔ (own branch if assigned) | | | |
| Create projects / tasks, approve tasks, review daily updates | | | | ✔ (`projects.manage`, `updates.review`) | | |
| Approve leave | | ✔ (any) | ✔ (own branch) | ✔ (direct reports, `leave.approve`) | | |
| Team attendance / update reports and CSV exports | | ✔ | ✔ (own branch) | ✔ (`reports.view`) | | |
| Aggregated company analytics + headcount summary | | ✔ | | | | ✔ (`analytics.view`, `reports.view`) |
| Webhooks, company settings | | ✔ | | | | |
| Audit logs | | ✔ | ✔ (own branch) | | | |
| Create teams, appoint the leader, allocate projects (own teams / own projects) | | ✔ | | ✔ (`teams.manage`) | | |
| Team memberships and transfers between teams (and branches: founder only) | | ✔ | ✔ (own branch) | | | |
| Distribute tasks, review daily updates, report to the manager (as the team's leader) | | | ✔ | ✔ | ✔ | |
| Raise escalations | | | | ✔ (to HR) | ✔ (to manager / HR) | |
| Handle escalations | | ✔ API only (no founder page, see note) | ✔ | ✔ (own team) | | |
| Tasks, daily updates, attendance, leave requests, meetings (own) | | ✔ | ✔ | ✔ | ✔ | |

**Teams** (`/teams`): a team belongs to a branch (optional) and to a *managing manager*; a person is in at most one team. The **team leader** is not a separate role: it is an employee or manager named on the team, so leadership can be reassigned without touching accounts. Allocating a project to a team gives every member and the leader access to it (they become project members), lets the leader create and re-assign tasks for the team's own members (never mark them done: the manager still approves) and shows the team's progress, milestones, overdue and blocked work. Members flag blockers on their tasks, the leader sees daily updates and blockers, files progress reports (`on track / at risk / blocked`) that notify the manager, and `/teams/analytics` compares team productivity. Moving someone to another team (HR/founder) frees their open tasks in the old team's projects and notifies both leaders; moving across branches is founder-only. Offboarding, branch changes and deleting a team keep everything consistent (leader slot cleared, project access trimmed). All changes are written to the audit log (`team.*`). **New project dialog:** a manager can create the project's team in the same step (leader + members, or pick an existing team); it is one transaction, so any validation failure creates nothing. Only people who are not in an *active* team are offered (`GET /teams/available`); a person's membership of an *inactive* team is dropped when they join another. One team per person is enforced by a unique constraint on `team_members.user_id`, not only in code. The leader can also add/remove members (same branch rules) but cannot replace or remove the leader slot, reassign or delete the team. Migration `0005` adds the tables: after deploying run **Companies → Run migrations**.

Everyone can view the company holidays on the **Holiday calendar** page (`/holidays`, month calendar + list); founders and HR can edit it there. The founder UI intentionally has no Daily Updates, Projects, Leave or Escalations pages (the API still allows the founder to read projects and to resolve escalations that reach them, but nothing in the UI offers it). HR cannot grant, modify or offboard a founder or a board member, and a company always keeps at least one founder. Only a founder can grant the founder, HR or manager role.

### Organisation: branches, managers, board members

All of this is enforced in the API (`app/access.py` plus the module routers); the UI only mirrors it.

- **Branches** (`/branches` page is founder-only in the UI; the API lets other roles read the list so forms and the employee branch filter work): name, unique code, address, city, country, active flag. Deleting is refused while people are assigned (deactivate instead). Founders assign employees, HR and managers with `POST /branches/{id}/members`; founders and board members are company-wide. Moving someone to another branch releases any line-manager relationship that would cross branches (recorded in the audit log). A reporting manager must be in the same branch as the employee.
- **Branch scope**: an HR user or manager with a branch only sees and manages people of that branch. That covers employee lists/details/edits/documents/photos/delete, leave requests and decisions, attendance and update reports, CSV exports, dashboard figures, project membership and audit logs. Branch HR hires into their own branch; only founders choose branches.
- **Employees**: employee ID (`EMP-0001`, or a custom unique ID), name, email, phone, designation, department, branch, work location (defaults to the branch city), joining date and reporting manager. `DELETE /employees/{id}` only succeeds for accounts without history (attendance, updates, leave, tasks, projects, messages, audit events); everyone else is offboarded. HR and founders can upload, replace and remove an employee's photo, including an optional photo when adding the employee (the UI previews the cropped image before saving); employees manage their own under *My profile*.
- **Managers** (`/managers`, founder only): branch, department, reporting line, team (`PUT /managers/{id}/team`) and permissions `projects.manage`, `leave.approve`, `updates.review`, `reports.view`. A manager without a permission gets `403` from the matching endpoints. By default managers have all four.
- **Board members** (`/board/members`, founder only): profile, designation, responsibilities, term start and permissions `analytics.view` / `reports.view`. Board members only see aggregated figures at `GET /board/analytics` and `GET /board/reports/headcount.csv`; every employee-level endpoint answers `403`/`404` for them. There is no financial data in WorkSphere, so the analytics page states that no financial summary is available instead of showing invented numbers.
- **Audit log** records employee changes (create, update, delete, offboard, photo upload/removal), profile edits, branch changes and assignments, manager and permission changes, board member changes, chat exceptions and escalation steps.

### Communication hierarchy

`app/access.can_message` decides who may chat: employees talk to the managers and HR of their branch (and to peers of the same branch); managers and HR talk to each other and to the founder; the founder talks to managers, HR and board members; board members talk only to the founder and other board members. **Employee ⇄ founder direct messages are blocked by default.** The founder can grant individual exceptions (*Chat → Direct lines*; `PUT/DELETE /chat/exceptions/{user_id}`). Rules are re-checked on every send, so revoking an exception closes the line (history stays readable) and groups cannot contain a forbidden pair.

The sanctioned way up is an **escalation** (`/escalations`): an employee raises it with their line manager or HR, the handler resolves it or escalates it to the founder with a note, and the founder resolves it. Each step notifies the people involved. Managers escalate to HR. Branch HR only sees escalations from their branch.

Existing companies need `POST /api/v1/platform/migrate` after upgrading to get the new tables and columns (`alembic_tenant` revisions 0002–0004).

### My tasks (personal task manager)

`/my-tasks` is a private to-do list for each person (founder, HR, managers and employees; the founder sees only the to-do list, the **Project tasks** tab is for people who get project work assigned): main tasks with subtasks (one level), a priority (High / Medium / Low), an estimated time (hours and minutes) and a status (To do / In progress / Completed). Tasks and subtasks are created, edited and deleted the same way, can be filtered and searched, and are reordered by dragging (grab a card by its handle; drop on the top or bottom edge to place it before or after another card, in the middle to make it a subtask of that card; subtasks can move between tasks or be promoted) or with the up/down buttons. A task shows the time needed (its own estimate plus its subtasks') and what is left. Finishing the last subtask completes the task, completing a task completes its subtasks, and reopening a subtask reopens the task. Everything is saved on the server (`/api/v1/todos`, table `todos`, tenant migration 0006: run **Companies → Run migrations** after deploying). The tasks assigned to you inside projects are on the second tab, **Project tasks**.

### Webhooks

Founders register endpoints in **Webhooks**. Each request carries `X-WorkSphere-Event`, `X-WorkSphere-Delivery`, `X-WorkSphere-Timestamp` and `X-WorkSphere-Signature: sha256=HMAC_SHA256(secret, timestamp + "." + rawBody)`. Verify the signature in constant time and reject stale timestamps. Events are written in the same DB transaction as the change (outbox), delivered by a background worker, retried with exponential backoff (30 s, 1 m, 2 m, 4 m; 5 attempts), and visible in the delivery log with manual retry. Targets must be public HTTPS URLs (SSRF guard; redirects are not followed). The secret is shown once and can be rotated.

### Chat

Company-scoped direct messages and groups, limited by the communication hierarchy above. REST under `/api/v1/chat/*` (`users`, `conversations`, `conversations/{id}/messages`, `conversations/{id}/read`, `unread-count`, `exceptions`); new messages are pushed as `{"type":"chat"}` frames on the same `/api/v1/ws` socket.

### Meetings (WebRTC)

Signaling is a WebSocket relay (`/api/v1/meetings/ws/{room}`) scoped to the company; media is peer-to-peer (mesh, max 8 people). `GET /meetings/ice-config` returns STUN and, when `TURN_URL` + `TURN_SECRET` are set, **short-lived** coturn credentials. Camera and screen sharing require HTTPS (or localhost).

## Tests

```bash
cd backend && pytest                 # 86 tests, ~1-2 min (bcrypt is intentionally slow)
cd frontend && npm test              # 11 unit tests
cd frontend && npm run build         # production build
```

## Deployment

1. Provision a host with Docker, a DNS name and TLS certificates; copy them to `nginx/certs/fullchain.pem` and `privkey.pem`.
2. `cp .env.example .env`, set strong unique values, set `PUBLIC_ORIGIN=https://your.domain`.
3. `docker compose -f docker-compose.prod.yml up -d --build`.
4. Sign in as the bootstrap platform admin, create the first company, then **remove `BOOTSTRAP_ADMIN_PASSWORD` from `.env`**. The server creates this admin only when none exists and never overwrites it afterwards; in production the first password must meet the password policy. To reset it later run `python scripts/reset_platform_admin_password.py <email>` on the server.
5. Back up: Postgres volumes (or use **Create backup** per tenant), the `appdata` volume (uploads) and — separately — `ENCRYPTION_KEY`.
6. TURN: set `TURN_URL`, `TURN_SECRET`, `TURN_EXTERNAL_IP` in `.env` and start the bundled coturn with `docker compose --profile turn up -d` (open UDP/TCP 3478 and UDP 49160-49200). Users behind strict NATs then relay through it; the API issues 1-hour credentials.

### Scaling limits to know about

The WebSocket fan-out, login rate limiter and webhook worker live **in one process**, so run a single backend replica until you move those to Redis (the seams are `realtime.publish_threadsafe`, `core/ratelimit.py` and `main._webhook_worker`). File uploads use local disk (`UPLOAD_DIR`); swap `app/storage.py` for S3/MinIO when running more than one host.

## Security notes

- Passwords: bcrypt with SHA-256 pre-hash (no 72-byte truncation), strength policy, constant-time-ish login for unknown users, per-user/IP lockout (5 failures / 15 min) plus Nginx rate limits.
- JWT: HS256, issuer/expiry/type enforced; access (30 min) and refresh (7 d) tokens are not interchangeable; platform and tenant tokens are not interchangeable.
- **Browser-bound sessions:** the SPA never sees its tokens. Login (header `X-WS-Client: web`) sets httpOnly, SameSite=Strict cookies `ws_access`, `ws_refresh` and `ws_device` (a random per-browser id); every token carries a hash of that id, so a token copied to another browser, a script or curl is rejected. The session survives tabs and restarts in the same browser on the same URL, and different browsers hold different accounts. Cookie-authenticated writes require the `X-WS-Client` header (CSRF), WebSockets check `Origin` and authenticate from the cookie. API clients (no header) still receive bearer tokens in the response body. Cookies are `Secure` over HTTPS.
- Uploads: size limit, blocked executable/HTML types, random server-side names, `nosniff`, served only as attachments to authorised users.
- CSV exports neutralise spreadsheet formula injection. All SQL goes through SQLAlchemy bound parameters; DB/role names are generated server-side.
- Audit log records who did what, from which IP.
