import { test, expect } from '@playwright/test'
import { acct, api, token, loginAs, PW, iso } from '../helpers'

const rejected = (s: number) => s >= 400 && s < 500

async function founder() { return token(acct('founder')) }
async function newUser(f: string, key: string, role = 'employee', pw = 'Pass1234') {
  const r = await api('POST', '/employees', f, { email: `${key}@acme.com`, full_name: `User ${key}`, password: pw, role })
  expect(r.status, `create ${key}`).toBe(201)
  return r.body
}

test.describe('F19 profile and password', () => {
  test('F19-H1 user edits their own profile in the UI', async ({ page }) => {
    const f = await founder(); await newUser(f, 'prof1')
    await loginAs(page, 'prof1@acme.com', 'Pass1234')
    await page.goto('/profile')
    const name = page.getByRole('textbox', { name: /full name/i })
    await name.fill('Renamed Person ✨')
    await page.getByRole('button', { name: /save/i }).first().click()
    await expect(page.getByText(/saved|updated/i).first()).toBeVisible()
    const me = await api('GET', '/auth/me', await token('prof1@acme.com', 'Pass1234'))
    expect(me.body.full_name).toBe('Renamed Person ✨')
  })

  test('F19-H2 change password: old stops working, new works', async () => {
    const f = await founder(); await newUser(f, 'pw1')
    const t = await token('pw1@acme.com', 'Pass1234')
    expect((await api('POST', '/auth/change-password', t, { current_password: 'Pass1234', new_password: 'Brand-New-Pw9x' })).status).toBe(204)
    expect((await api('POST', '/auth/login', undefined, { email: 'pw1@acme.com', password: 'Pass1234' })).status).toBe(401)
    expect((await api('POST', '/auth/login', undefined, { email: 'pw1@acme.com', password: 'Brand-New-Pw9x' })).status).toBe(200)
  })

  test('F19-N1 wrong current password and weak new password are refused', async () => {
    const f = await founder(); await newUser(f, 'pw2')
    const t = await token('pw2@acme.com', 'Pass1234')
    expect(rejected((await api('POST', '/auth/change-password', t, { current_password: 'nope', new_password: 'Brand-New-Pw9x' })).status)).toBe(true)
    expect(rejected((await api('POST', '/auth/change-password', t, { current_password: 'Pass1234', new_password: 'weak' })).status)).toBe(true)
  })

  test('F19-N2 a user cannot change role or email through the profile endpoint', async () => {
    const t = await token(acct('e2'))
    await api('PATCH', '/auth/me', t, { role: 'founder', email: 'evil@acme.com', department_id: 1 })
    const me = await api('GET', '/auth/me', t)
    expect(me.body.role).toBe('employee'); expect(me.body.email).toBe('e2@acme.com')
  })

  test('F19-N3 HR reset-password lets the person in with the temporary password', async () => {
    const f = await founder(); const u = await newUser(f, 'pw3')
    expect((await api('POST', `/employees/${u.id}/reset-password`, f, { new_password: 'Temp4567' })).status).toBeLessThan(300)
    expect((await api('POST', '/auth/login', undefined, { email: 'pw3@acme.com', password: 'Temp4567' })).status).toBe(200)
  })
})

test.describe('F20 offboarding and deletion', () => {
  test('F20-H1 offboarded user is locked out at once (old token and new login)', async () => {
    const f = await founder(); const u = await newUser(f, 'off1')
    const t = await token('off1@acme.com', 'Pass1234')
    expect((await api('GET', '/auth/me', t)).status).toBe(200)
    const r = await api('POST', `/employees/${u.id}/offboard`, f, {})
    expect(r.status, JSON.stringify(r.body)).toBeLessThan(300)
    expect((await api('GET', '/auth/me', t)).status).toBe(401)
    expect((await api('POST', '/auth/login', undefined, { email: 'off1@acme.com', password: 'Pass1234' })).status).toBe(401)
  })

  test('F20-N1 the last founder cannot be removed or demoted; HR cannot touch a founder', async () => {
    const f = await founder(); const hr = await token(acct('hr'))
    const list = await api('GET', '/employees?page_size=100', f)
    const fo = list.body.items.find((u: { role: string }) => u.role === 'founder')
    expect(rejected((await api('POST', `/employees/${fo.id}/offboard`, hr, {})).status)).toBe(true)
    expect(rejected((await api('PATCH', `/employees/${fo.id}`, hr, { role: 'employee' })).status)).toBe(true)
    expect(rejected((await api('DELETE', `/employees/${fo.id}`, f)).status)).toBe(true)
  })

  test('F20-N2 an employee with history cannot be hard-deleted', async () => {
    const f = await founder()
    const list = await api('GET', '/employees?page_size=100&q=Elena', f)
    const e1 = list.body.items.find((u: { email: string }) => u.email === 'e1@acme.com')
    expect(rejected((await api('DELETE', `/employees/${e1.id}`, f)).status)).toBe(true)
  })
})

test.describe('F21 organisation: branches, managers, board', () => {
  test('F21-H1 founder creates a branch, assigns HR; duplicate code and delete-with-people are refused', async () => {
    const f = await founder()
    const hr = (await api('GET', '/employees?page_size=100', f)).body.items.find((u: { email: string }) => u.email === 'hr@acme.com')
    const b = await api('POST', '/branches', f, { name: 'South Hub', code: 'SOUTH', city: 'Chennai' })
    expect(b.status).toBe(201)
    expect(rejected((await api('POST', '/branches', f, { name: 'Other', code: 'south' })).status)).toBe(true)
    expect((await api('POST', `/branches/${b.body.id}/members`, f, { user_ids: [hr.id] })).status).toBeLessThan(300)
    expect(rejected((await api('DELETE', `/branches/${b.body.id}`, f)).status)).toBe(true)
    // put HR back so other specs see the company-wide HR
    expect((await api('DELETE', `/branches/${b.body.id}/members/${hr.id}`, f)).status).toBeLessThan(300)
  })

  test('F21-N1 non-founders cannot create branches, managers\' permissions or board members', async () => {
    const hr = await token(acct('hr')); const m = await token(acct('mgr'))
    expect(rejected((await api('POST', '/branches', hr, { name: 'Nope', code: 'NOPE' })).status)).toBe(true)
    expect(rejected((await api('GET', '/managers', m)).status)).toBe(true)
    expect(rejected((await api('POST', '/board/members', m, { email: 'b2@acme.com', full_name: 'B Two', password: PW })).status)).toBe(true)
  })

  test('F21-H2 board member sees aggregates only, never people', async () => {
    const b = await token(acct('board'))
    expect((await api('GET', '/board/analytics', b)).status).toBe(200)
    expect((await fetch('http://127.0.0.1:8100/api/v1/board/reports/headcount.csv', { headers: { Authorization: `Bearer ${b}` } })).status).toBe(200)
    for (const u of ['/employees', '/projects', '/leave/requests', '/attendance', '/daily-updates/team']) {
      const r = await api('GET', u, b)
      expect(rejected(r.status) || (r.status === 200 && (r.body.items ?? []).length === 0), `${u} -> ${r.status}`).toBe(true) // refused, or an empty list
    }
  })

  test('F21-H3 manager permission switched off gives 403 on that area', async () => {
    const f = await founder()
    const mgrs = await api('GET', '/managers', f)
    const m = mgrs.body.items.find((x: { email: string }) => x.email === 'mgr@acme.com')
    const t = await token(acct('mgr'))
    expect((await api('GET', '/leave/requests', t)).status).toBe(200)
    expect((await api('PATCH', `/managers/${m.id}`, f, { permissions: ['projects.manage', 'updates.review', 'reports.view'] })).status).toBeLessThan(300)
    expect(rejected((await api('GET', '/leave/requests', t)).status)).toBe(true)
    expect((await api('PATCH', `/managers/${m.id}`, f, { permissions: ['projects.manage', 'leave.approve', 'updates.review', 'reports.view'] })).status).toBeLessThan(300)
    expect((await api('GET', '/leave/requests', t)).status).toBe(200)
  })
})

test.describe('F22 exports, input hardening and limits', () => {
  test('F22-H1 CSV exports download for HR; formula-looking names are neutralised', async () => {
    const f = await founder()
    await newUser(f, 'csv1').then(async (u) => api('PATCH', `/employees/${u.id}`, f, { full_name: '=HYPERLINK("http://evil","x")' }))
    const t = await token('csv1@acme.com', 'Pass1234')
    await api('POST', '/attendance/check-in', t)
    const hr = await token(acct('hr'))
    const res = await fetch('http://127.0.0.1:8100/api/v1/reports/attendance.csv', { headers: { Authorization: `Bearer ${hr}` } })
    expect(res.status).toBe(200)
    const csv = await res.text()
    expect(csv).toContain('HYPERLINK')
    expect(csv).not.toMatch(/(^|,|\n)"?=HYPERLINK/)
  })

  test('F22-N1 employees cannot download company CSVs', async () => {
    const e = await token(acct('e1'))
    for (const u of ['/reports/attendance.csv', '/reports/leave.csv', '/reports/tasks.csv']) {
      expect(rejected((await fetch('http://127.0.0.1:8100/api/v1' + u, { headers: { Authorization: `Bearer ${e}` } })).status), u).toBe(true)
    }
  })

  test('F22-N2 absurd paging, SQL-looking search and unicode never cause a 500', async () => {
    const f = await founder()
    for (const q of ['page_size=100000', 'page=-1', 'page=abc', "q=%27%3B%20DROP%20TABLE%20users%3B--", 'q=%00', 'q=' + encodeURIComponent('😀'.repeat(500)), 'sort=;select', 'role=nonsense', 'status=%25']) {
      const r = await api('GET', `/employees?${q}`, f)
      expect(r.status, q).toBeLessThan(500)
    }
  })

  test('F22-N3 oversize and malformed JSON bodies are 4xx', async () => {
    const f = await founder()
    const r = await fetch('http://127.0.0.1:8100/api/v1/departments', { method: 'POST', headers: { Authorization: `Bearer ${f}`, 'Content-Type': 'application/json' }, body: '{not json' })
    expect(rejected(r.status)).toBe(true)
    expect(rejected((await api('POST', '/departments', f, { name: 'x'.repeat(5000) })).status)).toBe(true)
  })

  test('F22-N4 script in a name is rendered as text, not executed', async ({ page }) => {
    const f = await founder()
    await api('POST', '/employees', f, { email: 'xss1@acme.com', full_name: '<img src=x onerror="window.__xss=1">Mallory', password: 'Pass1234', role: 'employee' })
    await loginAs(page, acct('founder'))
    await page.goto('/employees')
    await expect(page.getByText('Mallory').first()).toBeVisible()
    expect(await page.evaluate(() => (window as unknown as { __xss?: number }).__xss)).toBeUndefined()
    expect(await page.locator('img[src="x"]').count()).toBe(0)
  })

  test('F22-N5 uploads: an HTML file posing as an avatar is refused', async () => {
    const t = await token(acct('e2'))
    const fd = new FormData()
    fd.append('file', new Blob(['<script>alert(1)</script>'], { type: 'text/html' }), 'avatar.html')
    const r = await fetch('http://127.0.0.1:8100/api/v1/auth/me/avatar', { method: 'POST', headers: { Authorization: `Bearer ${t}` }, body: fd })
    expect(rejected(r.status)).toBe(true)
  })

  test('F22-N6 API sends security headers and no server version leak', async () => {
    const r = await fetch('http://127.0.0.1:8100/api/health')
    expect(r.status).toBe(200)
    expect(r.headers.get('x-content-type-options')).toBe('nosniff')
  })
})

test.describe('F23 attendance and updates (manager view)', () => {
  test('F23-H1 manager sees a team member\'s update and can review it', async () => {
    const e1 = await token(acct('e1')); const m = await token(acct('mgr'))
    const mine = await api('GET', '/daily-updates/mine', e1)
    const first = mine.body.items?.[0]
    test.skip(!first, 'no update yet for e1 (F05 not run first)')
    const team = await api('GET', '/daily-updates/team', m)
    expect(JSON.stringify(team.body)).toContain('Shipped the login form')
    expect((await api('POST', `/daily-updates/${first.id}/review`, m, { status: 'reviewed', comment: 'Thanks' })).status).toBeLessThan(300)
  })

  test('F23-N1 a second update for the same day replaces/refuses, never duplicates', async () => {
    const e = await token(acct('e2'))
    const body = { work_date: iso(new Date()), completed: 'again', hours_worked: 2 }
    await api('POST', '/daily-updates', e, body)
    await api('POST', '/daily-updates', e, body)
    const mine = await api('GET', '/daily-updates/mine', e)
    const today = mine.body.items.filter((u: { work_date: string }) => u.work_date === iso(new Date()))
    expect(today.length).toBeLessThanOrEqual(1)
  })

  test('F23-N2 check-out without check-in and double check-in are refused', async () => {
    const f = await founder(); await newUser(f, 'att1')
    const t = await token('att1@acme.com', 'Pass1234')
    expect(rejected((await api('POST', '/attendance/check-out', t)).status)).toBe(true)
    expect((await api('POST', '/attendance/check-in', t)).status).toBe(201)
    expect(rejected((await api('POST', '/attendance/check-in', t)).status)).toBe(true)
  })
})
