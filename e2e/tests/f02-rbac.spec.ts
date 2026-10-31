import { test, expect } from '@playwright/test'
import { acct, api, token, loginAs, watchErrors } from '../helpers'

const NAV: Record<string, { has: string[]; lacks: string[] }> = {
  founder: { has: ['My Tasks', 'Employees', 'Branches', 'Webhooks', 'Administration'], lacks: ['Leave', 'Projects'] },
  hr: { has: ['Employees', 'Leave Approvals', 'Administration'], lacks: ['Branches', 'Webhooks', 'Companies'] },
  mgr: { has: ['Employees', 'Projects', 'Leave Approvals'], lacks: ['Branches', 'Webhooks', 'Administration'] },
  e1: { has: ['My Tasks', 'Leave', 'Daily Updates', 'Attendance', 'Employees'], lacks: ['Branches', 'Webhooks', 'Leave Approvals', 'Administration'] },
}

test.describe('F02 role based navigation and API permissions', () => {
  for (const [key, n] of Object.entries(NAV)) {
    test(`F02-H ${key} sees the right menu`, async ({ page }) => {
      const done = watchErrors(page)
      await loginAs(page, acct(key))
      const nav = page.getByRole('navigation', { name: 'Main' })
      await expect(nav).toBeVisible()
      for (const l of n.has) await expect(nav.getByRole('link', { name: l, exact: true })).toBeVisible()
      for (const l of n.lacks) await expect(nav.getByRole('link', { name: l, exact: true })).toHaveCount(0)
      done()
    })
  }

  test('F02-N1 employee typing /webhooks in the URL gets no webhook controls', async ({ page }) => {
    await loginAs(page, acct('e1'))
    await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible()
    await page.goto('/webhooks')
    await expect(page.getByRole('button', { name: /add webhook|new webhook/i })).toHaveCount(0)
  })

  test('F02-N2 API refuses employee on privileged endpoints', async () => {
    const t = await token(acct('e1'))
    const cases: [string, string, unknown?][] = [
      ['POST', '/employees', { email: 'x@acme.com', full_name: 'X Y', password: 'Abcd1234!', role: 'employee' }],
      ['GET', '/webhooks'], ['POST', '/departments', { name: 'Hax' }], ['GET', '/platform/companies'],
    ]
    for (const [m, u, body] of cases) {
      const r = await api(m, u, t, body)
      expect([403, 404], `${m} ${u} -> ${r.status}`).toContain(r.status)
    }
  })

  test('F02-N3 HR cannot create a founder', async () => {
    const hr = await token(acct('hr'))
    const r = await api('POST', '/employees', hr, { email: 'f2@acme.com', full_name: 'Fake Founder', password: 'Abcd1234!', role: 'founder' })
    expect(r.status).toBeGreaterThanOrEqual(400)
    expect(r.status).toBeLessThan(500)
  })

  test('F02-N4 requests without or with a garbage token get 401', async () => {
    expect((await api('GET', '/dashboard')).status).toBe(401)
    expect((await api('GET', '/dashboard', 'garbage.token.value')).status).toBe(401)
  })

  test('F02-N5 refresh token cannot be used as an access token', async () => {
    const r = await api('POST', '/auth/login', undefined, { email: acct('e2'), password: 'Demo-Pw0rd!' })
    expect((await api('GET', '/dashboard', r.body.refresh_token)).status).toBe(401)
  })
})
