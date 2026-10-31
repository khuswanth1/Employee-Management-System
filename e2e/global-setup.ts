import { request } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import { api, PLATFORM, PW, token, iso, nextWeekday } from './helpers'

const WEB = 'http://localhost:5273'
export const STATE = (role: string) => `.auth/${role}.json`

/** Sign in once per role through the real login endpoint and keep the browser cookies, so specs start signed in. */
async function saveState(role: string, email: string, password = PW) {
  const ctx = await request.newContext({ baseURL: WEB, extraHTTPHeaders: { 'X-WS-Client': 'web' } })
  const r = await ctx.post('/api/v1/auth/login', { data: { email, password } })
  if (!r.ok()) throw new Error(`state login ${email} -> ${r.status()}`)
  await ctx.storageState({ path: STATE(role) })
  await ctx.dispose()
}

async function must(r: { status: number; body: any }, what: string) {
  if (r.status >= 300) throw new Error(`${what} -> ${r.status} ${JSON.stringify(r.body)}`)
  return r.body
}

export default async function globalSetup() {
  const admin = (await must(await api('POST', '/auth/platform/login', undefined, PLATFORM), 'platform login')).access_token
  for (const [slug, name] of [['acme', 'Acme Corporation'], ['globex', 'Globex']]) {
    await must(await api('POST', '/platform/companies', admin, {
      name, slug, founder_name: `${name} Founder`, founder_email: `founder@${slug}.com`, founder_password: PW }), `create ${slug}`)
  }
  const f = await token('founder@acme.com')
  const eng = await must(await api('POST', '/departments', f, { name: 'Engineering' }), 'dept')
  const mk = async (key: string, name: string, role: string, manager?: number) =>
    must(await api('POST', '/employees', f, { email: `${key}@acme.com`, full_name: name, password: PW, role,
      department_id: eng.id, manager_id: manager ?? null, designation: role }), `employee ${key}`)
  const hr = await mk('hr', 'Hannah HR', 'hr')
  const mgr = await mk('mgr', 'Marcus Manager', 'manager')
  const e1 = await mk('e1', 'Elena Engineer', 'employee', mgr.id)
  const e2 = await mk('e2', 'Ethan Engineer', 'employee', mgr.id)
  await mk('e3', 'Priya Designer', 'employee', mgr.id)

  const m = await token('mgr@acme.com')
  const proj = await must(await api('POST', '/projects', m, { name: 'Customer Portal Redesign', description: 'Portal', status: 'active',
    start_date: iso(new Date()), due_date: iso(nextWeekday(40)), member_ids: [e1.id, e2.id] }), 'project')
  await must(await api('POST', `/projects/${proj.id}/tasks`, m, { title: 'Wireframes', assignee_id: e1.id, priority: 'high', due_date: iso(nextWeekday(5)) }), 'task')

  // organisation: a branch, a board member and a team
  const branch = await must(await api('POST', '/branches', f, { name: 'Headquarters', code: 'HQ', city: 'Pune', country: 'India' }), 'branch')
  await must(await api('POST', '/board/members', f, { email: 'board@acme.com', full_name: 'Bella Board', password: PW, designation: 'Director', permissions: ['analytics.view', 'reports.view'] }), 'board')
  await must(await api('POST', '/teams', f, { name: 'Alpha Team', manager_id: mgr.id, leader_id: e1.id, member_ids: [e1.id, e2.id] }), 'team')
  void branch

  // second tenant: same numeric ids, different data, used by the isolation spec
  const g = await token('founder@globex.com')
  await must(await api('POST', '/employees', g, { email: 'spy@globex.com', full_name: 'Globex Secret Person', password: PW, role: 'employee' }), 'globex emp')

  mkdirSync('.auth', { recursive: true })
  for (const [role, email] of [['founder', 'founder@acme.com'], ['hr', 'hr@acme.com'], ['mgr', 'mgr@acme.com'], ['e1', 'e1@acme.com'], ['e2', 'e2@acme.com'], ['board', 'board@acme.com']]) await saveState(role, email)
  await saveState('platform', PLATFORM.email, PLATFORM.password)
}
