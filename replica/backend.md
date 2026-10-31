# Backend audit — WorkSphere

`replica/architecture.md` doesn't exist and the backend is already built (FastAPI, per-company databases), so this is an audit against the replica-backend checklist, not a build. Nothing was changed for it.

## Auth
| Item | State |
|---|---|
| Email sign-up + verification | **N/A by design**: accounts are created by founder/HR with a temporary password (4–12 chars). No self sign-up. |
| Password reset | **Missing for self-service.** HR/founder can reset (`/employees/{id}/reset-password`); a user who forgot it must ask. A reset-by-email flow needs SMTP configured (settings exist: `SMTP_*`). |
| Sessions in httpOnly secure cookies | **Done** (browser-bound, SameSite=Strict, Secure over HTTPS). |
| Sign out | Done on this browser. **No "sign out everywhere"**: tokens are stateless; a server-side session version per user would add it. |
| One authorisation function | Done (`app/access.py` + route guards), tested with second users and a second tenant. |
| Account deletion | Offboard always; hard delete only for accounts without history (by design, keeps audit trail). |
| Login lockout | Done (5 failures / 15 min per email+IP). In-process only. |

## Database
| Item | State |
|---|---|
| Migrations checked in | Done (`alembic_platform`, `alembic_tenant` 0001–0005). Fixed this session: 0003 idempotent, `env.py` under SQLAlchemy 2.1. |
| Access rules | Tenant isolation by separate databases + JWT tenant; verified by pytest and e2e F08. |
| Seed script | `scripts/seed_demo.py` (demo password is hard-coded and printed: dev only). |
| Backups | Per-tenant backup endpoint exists; **restore is not tested**. Host-level backups are up to you. |

## Payments, email, jobs, integrations
- Payments: none (no billing in this product).
- Email: SMTP configured via env; used for notifications. **Not covered by tests** (real send).
- Jobs: webhook delivery worker with retry/backoff, in-process (one replica only, noted in README).
- Integrations: outgoing webhooks (SSRF-guarded, signed). WebRTC meetings need TURN for strict NATs.

## Security checklist
- [x] secrets only in env vars; `.env` is in `.gitignore`; `.env.example` has names only
- [x] server-side input validation (Pydantic) on routes; malformed/oversize input returns 4xx (e2e F22)
- [x] authorisation on reads and writes, tested with a second user and tenant
- [x] rate limits on login (not on other email-sending actions: there are none besides notifications)
- [x] webhooks signed (HMAC) and SSRF-guarded
- [x] uploads: size/type limits, random names, `nosniff`, served as attachments to authorised users
- [x] CSV formula injection neutralised (e2e F22-H1)
- [x] dependencies: `npm audit` 0 vulnerabilities (frontend, e2e); versions pinned in `requirements.txt`. **`pip-audit` not installed, Python dependencies not audited.**
- [x] fixed this session: dev-mode login bypass and plaintext `auth_activity.log` (B-002, B-005)
- [ ] tenant database URL that can't be decrypted is replaced by a guessed SQLite path (B-006, open)
- [ ] `POST /projects` has a test-only name check in production code
- [ ] privacy policy listing processors: not in the repo
- [ ] `.env` was edited by hand during this session: confirm `ENVIRONMENT=production`, strong `SECRET_KEY`, and `BOOTSTRAP_ADMIN_PASSWORD` removed after first start before deploying

## Next
`/replica-test` (already run: see `test-plan.md`, `bugs.md`).
