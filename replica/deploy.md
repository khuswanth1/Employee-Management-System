# Deploy preflight — WorkSphere

Nothing was deployed. No domain, host, key or account was touched. This is the checklist result as of the last test run (2026-10-21).

## Automated checks
| Check | Result |
|---|---|
| End-to-end (`cd e2e && npx playwright test`) | 174 cases, all pass (one flaky layout check fixed) |
| Backend (`cd backend && pytest`) | 121 pass |
| Frontend unit (`npm test`) | 16 pass |
| Production build (`npm run build`) | passes |
| `npm audit` (frontend, e2e) | 0 vulnerabilities |
| Python dependency audit | **not run** (`pip-audit` not installed) |
| Brand sweep / feature parity / store listing | **N/A**: no original app, web only, no store listing |
| Docker images and compose stack | **not built**: Docker is not installed on this machine |

## Bugs
No open S1 or S2. Open S3: B-006 (undecryptable tenant URL silently replaced by a guessed SQLite path; in production that could point a company at the wrong database). Fix before relying on it.

## Compatibility with the production stack (read from the files, not run)
- Cookie sessions use `Secure` when the request is HTTPS; nginx sends `X-Forwarded-Proto` and the backend runs with `--proxy-headers`, so this should work behind nginx.
- WebSocket Origin check uses `CORS_ORIGINS`, which compose sets to `PUBLIC_ORIGIN`. It must be exactly the public `https://` origin users type, or notifications and meetings will not connect.
- Nginx's login rate limit applies to `/auth/login`; `/auth/refresh` falls under the general API limit.
- The CSP (`script-src 'self'`) matches the build: no inline scripts were added.

## Before you go live (yours to do)
1. Create `.env` from `.env.example` with strong, unique values: three DB passwords, `SECRET_KEY`, `ENCRYPTION_KEY` (**back it up separately**), `PUBLIC_ORIGIN=https://your.domain`, `BOOTSTRAP_ADMIN_*`.
2. Put TLS certificates in `nginx/certs/` (`fullchain.pem`, `privkey.pem`).
3. `docker compose -f docker-compose.prod.yml up -d --build` on a host with Docker.
4. Sign in as the platform admin, create the first company, then remove `BOOTSTRAP_ADMIN_PASSWORD` from `.env`.
5. Check `ENVIRONMENT=production` is set (compose sets it).
6. Back up the Postgres volume, the `appdata` volume and the `ENCRYPTION_KEY`; try one restore (restore is untested).
7. Run one real flow on the live site: sign in, check in, apply for leave, approve it, and open a second browser to confirm it is not signed in.
8. Set up uptime and error monitoring, and an SMTP account if you want email notifications (untested).
9. Add a privacy policy and terms pages if the site is public.

## Not decided
Domain, host, DNS records and monitoring depend on where you deploy; tell me the host and domain and I will write the exact records and commands.
