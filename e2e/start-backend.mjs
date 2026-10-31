// Starts an isolated backend for the tests: fresh SQLite databases under e2e/.tmp, no SMTP, no TURN.
// Environment variables beat backend/.env, so the real Postgres/SMTP settings are never used.
import { spawn } from 'node:child_process'
import { rmSync, mkdirSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const backend = path.resolve(here, '..', 'backend')
const data = path.join(here, process.env.E2E_TMP || '.tmp')
rmSync(data, { recursive: true, force: true })
mkdirSync(data, { recursive: true })
const py = process.platform === 'win32' ? path.join(backend, '.venv', 'Scripts', 'python.exe') : path.join(backend, '.venv', 'bin', 'python')
const u = (p) => p.split(path.sep).join('/')

const env = {
  ...process.env,
  ENVIRONMENT: process.env.E2E_ENV || 'production', // so dev-only shortcuts are off; a separate test covers the development setting
  SECRET_KEY: 'e2e-secret-key-e2e-secret-key-e2e-secret-key-0123456789',
  ENCRYPTION_KEY: 'MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=',
  PLATFORM_DATABASE_URL: `sqlite:///${u(data)}/platform.db`,
  TENANT_DB_MODE: 'sqlite',
  TENANT_SQLITE_DIR: u(path.join(data, 'tenants')),
  UPLOAD_DIR: u(path.join(data, 'uploads')),
  BACKUP_DIR: u(path.join(data, 'backups')),
  POSTGRES_ADMIN_URL: '',
  CORS_ORIGINS: 'http://localhost:5273',
  BOOTSTRAP_ADMIN_EMAIL: 'platform@example.com',
  BOOTSTRAP_ADMIN_PASSWORD: 'E2e-Platform-Pw1!',
  SMTP_HOST: '', SMTP_USER: '', SMTP_PASSWORD: '', TURN_URL: '', TURN_SECRET: '',
}
const child = spawn(py, ['-m', 'uvicorn', 'app.main:app', '--port', process.env.E2E_PORT || '8100'], { cwd: backend, env, stdio: 'inherit' })
child.on('exit', (c) => process.exit(c ?? 0))
for (const s of ['SIGINT', 'SIGTERM']) process.on(s, () => child.kill())
