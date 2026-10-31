import { test, expect } from '@playwright/test'
import { a11y, acct, api, loginAs, token, watchErrors } from '../helpers'

async function idOf(email: string) {
  const f = await token(acct('founder'))
  const r = await api('GET', '/employees?page_size=100', f)
  return r.body.items.find((u: any) => u.email === email).id as number
}

test.describe('F26 employee profile tabs', () => {
  test('F26-H1 HR saves employment details; they persist and the tab passes axe', async ({ page }) => {
    const done = watchErrors(page)
    const e3 = await idOf(acct('e3'))
    await loginAs(page, acct('hr'))
    await page.goto(`/employees/${e3}`)
    await page.getByRole('tab', { name: 'Employment' }).click()
    await page.getByLabel('Employment type').selectOption('full_time')
    await page.getByLabel('Notice period (days)').fill('30')
    await page.getByLabel('Job level').fill('L3')
    await page.getByRole('button', { name: 'Save changes' }).first().click()
    await expect(page.getByText('Saved', { exact: true })).toBeVisible()
    await a11y(page, 'employee employment tab')
    await page.reload()
    await page.getByRole('tab', { name: 'Employment' }).click()
    await expect(page.getByLabel('Job level')).toHaveValue('L3')
    const hr = await token(acct('hr'))
    expect((await api('GET', `/employees/${e3}/profile`, hr)).body.notice_period_days).toBe(30)
    done()
  })

  test('F26-H2 an employee edits their own restricted details; the manager never sees them or the Personal tab', async ({ page, browser }) => {
    const done = watchErrors(page)
    const e1 = await idOf(acct('e1'))
    await loginAs(page, acct('e1'))
    await page.goto(`/employees/${e1}`)
    await page.getByRole('tab', { name: 'Personal' }).click()
    await page.getByLabel('Home address').fill('12 Test Street')
    await page.getByLabel('Name', { exact: true }).fill('Sam Contact')
    await page.getByLabel('Phone').fill('+1 555 0100')
    await page.getByRole('button', { name: 'Save changes' }).first().click()
    await expect(page.getByText('Saved', { exact: true })).toBeVisible()
    await a11y(page, 'employee personal tab')

    const mgrCtx = await browser.newContext()
    const mgrPage = await mgrCtx.newPage()
    await loginAs(mgrPage, acct('mgr'))
    await mgrPage.goto(`/employees/${e1}`)
    await expect(mgrPage.getByRole('tab', { name: 'Employment' })).toBeVisible()
    await expect(mgrPage.getByRole('tab', { name: 'Personal' })).toHaveCount(0)
    const mgr = await token(acct('mgr'))
    const body = await api('GET', `/employees/${e1}/profile`, mgr)
    expect(body.status).toBe(200)
    expect(JSON.stringify(body.body)).not.toContain('12 Test Street')
    await mgrCtx.close()
    done()
  })

  test('F26-H3 employee uploads a document with a type and expiry; HR verifies it', async ({ page, browser }) => {
    const done = watchErrors(page)
    const e2 = await idOf(acct('e2'))
    await loginAs(page, acct('e2'))
    await page.goto(`/employees/${e2}`)
    await page.getByRole('tab', { name: 'Documents' }).click()
    await page.getByLabel('Type').selectOption('certification')
    await page.getByLabel('Expiry date').fill(new Date(Date.now() + 10 * 864e5).toISOString().slice(0, 10))
    await page.getByLabel('File').setInputFiles({ name: 'cert-e2e.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4 e2e') })
    await page.getByRole('button', { name: 'Upload' }).click()
    await expect(page.getByText('cert-e2e.pdf')).toBeVisible()
    await expect(page.getByText('Expires soon')).toBeVisible()
    await expect(page.getByText('Pending')).toBeVisible()
    await expect(page.getByLabel('Verification for cert-e2e.pdf')).toHaveCount(0) // owners cannot verify their own

    const hrCtx = await browser.newContext()
    const hrPage = await hrCtx.newPage()
    await loginAs(hrPage, acct('hr'))
    await hrPage.goto(`/employees/${e2}`)
    await hrPage.getByRole('tab', { name: 'Documents' }).click()
    await hrPage.getByLabel('Verification for cert-e2e.pdf').selectOption('verified')
    await expect(hrPage.getByText('Verified', { exact: true }).first()).toBeVisible()
    await a11y(hrPage, 'employee documents tab')
    await hrCtx.close()
    done()
  })

  test('F26-N1 invalid values and foreign profiles are refused with 4xx', async () => {
    const e1 = await idOf(acct('e1')); const e2tok = await token(acct('e2')); const hr = await token(acct('hr'))
    for (const bad of [{ employment_type: 'x' }, { notice_period_days: 999 }, { date_of_birth: '2999-01-01' }, { emergency_contact_phone: 'call' }]) {
      const r = await api('PATCH', `/employees/${e1}/profile`, hr, bad)
      expect(r.status).toBeGreaterThanOrEqual(400); expect(r.status).toBeLessThan(500)
    }
    expect((await api('GET', `/employees/${e1}/profile`, e2tok)).status).toBe(403)
    expect((await api('PATCH', `/employees/${e1}/profile`, e2tok, { skills: ['x'] })).status).toBe(403)
  })

  test('F26-N2 sorting the employee list by an unlisted column is refused, not a 500', async () => {
    const hr = await token(acct('hr'))
    const r = await api('GET', '/employees?sort=password_hash', hr)
    expect(r.status).toBe(422)
  })
})
