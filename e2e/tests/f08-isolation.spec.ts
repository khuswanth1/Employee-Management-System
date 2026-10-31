import { test, expect } from '@playwright/test'
import { acct, api, token, loginAs } from '../helpers'

test.describe('F08 tenant isolation', () => {
  test('F08-N1 Globex founder cannot see Acme people', async () => {
    const g = await token(acct('founder', 'globex'))
    const r = await api('GET', '/employees?page_size=100', g)
    const emails = (r.body.items ?? []).map((u: { email: string }) => u.email)
    expect(emails.some((e: string) => e.endsWith('@acme.com'))).toBe(false)
    expect(emails).toContain('spy@globex.com')
  })

  test('F08-N2 an Acme employee id looked up from Globex is not Acme data', async () => {
    const g = await token(acct('founder', 'globex'))
    const a = await token(acct('founder'))
    const acme = await api('GET', '/employees?page_size=100', a)
    const target = acme.body.items.find((u: { email: string }) => u.email === 'e1@acme.com')
    const r = await api('GET', `/employees/${target.id}`, g)
    if (r.status === 200) expect(r.body.email).not.toBe('e1@acme.com')
    else expect([403, 404]).toContain(r.status)
  })

  test('F08-N3 forged tenant hints are ignored', async () => {
    const g = await token(acct('founder', 'globex'))
    const r = await fetch('http://127.0.0.1:8100/api/v1/employees?page_size=100&tenant_id=1&company_slug=acme', {
      headers: { Authorization: `Bearer ${g}`, 'X-Tenant-ID': '1', 'X-Company': 'acme' } })
    const body = await r.json()
    expect((body.items ?? []).some((u: { email: string }) => u.email.endsWith('@acme.com'))).toBe(false)
  })

  test('F08-N4 UI: Globex founder never sees Acme names', async ({ page }) => {
    await loginAs(page, acct('founder', 'globex'))
    await page.goto('/employees')
    await expect(page.getByText('Globex Secret Person').first()).toBeVisible()
    await expect(page.getByText('Elena Engineer')).toHaveCount(0)
  })
})
