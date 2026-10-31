import { test, expect } from '@playwright/test'
import { acct, api, loginAs, token, watchErrors } from '../helpers'

test.describe.configure({ mode: 'serial' })

test.describe('F30 payroll end to end', () => {
  const now = new Date()
  const monthLabel = now.toLocaleString('en-US', { month: 'long' })

  test('F30-H1 HR sets up pay and a run, a founder approves it, the employee reads the payslip', async ({ page, browser }) => {
    const done = watchErrors(page)
    // seed: a pay component and an earlier hire date for the employee, through the API like an admin would
    const f = await token(acct('founder'))
    const e1 = (await api('GET', '/employees/directory', f)).body.items.find((u: any) => u.email === acct('e1'))
    expect((await api('PATCH', `/employees/${e1.id}`, f, { hire_date: '2025-01-01' })).status).toBe(200)
    expect((await api('POST', '/payroll/components', f, { code: 'E2EHRA', name: 'E2E housing', kind: 'earning', calc: 'percent_of_basic', default_value: 10 })).status).toBe(201)

    await loginAs(page, acct('hr'))
    await page.goto('/payroll')
    await page.getByRole('tab', { name: 'Pay structures' }).click()
    await page.getByRole('row', { name: /Elena Engineer/ }).getByRole('button', { name: 'Set up' }).click()
    let dlg = page.getByRole('dialog')
    await dlg.getByLabel(/Monthly basic/).fill('3000')
    await dlg.getByLabel(/E2E housing/).fill('10')
    await dlg.getByRole('button', { name: 'Save new version' }).click()
    await expect(dlg).toBeHidden()
    await expect(page.getByRole('row', { name: /Elena Engineer/ })).toContainText('3,000.00')

    await page.getByRole('tab', { name: 'Runs' }).click()
    await page.getByRole('button', { name: 'New payroll run' }).first().click()
    dlg = page.getByRole('dialog')
    await dlg.getByLabel('Month').selectOption(String(now.getMonth() + 1))
    await dlg.getByLabel('Year').fill(String(now.getFullYear()))
    await dlg.getByRole('button', { name: 'Calculate' }).click()
    await expect(dlg).toBeHidden()
    await page.getByRole('link', { name: new RegExp(`${monthLabel} ${now.getFullYear()}`) }).click()
    await expect(page.getByRole('row', { name: /Elena Engineer/ })).toBeVisible()
    await expect(page.getByText('Draft')).toBeVisible()
    await page.getByRole('button', { name: 'Submit for approval' }).click()
    await expect(page.getByText('Awaiting approval').first()).toBeVisible()
    await expect(page.getByRole('button', { name: 'Approve' })).toHaveCount(0)             // not by the person who submitted it
    const runUrl = page.url()

    // the employee sees nothing yet
    const e = await (await browser.newContext({ baseURL: 'http://localhost:5273' })).newPage()
    await loginAs(e, acct('e1'))
    await e.goto('/payslips')
    await expect(e.getByText('No payslips yet')).toBeVisible()

    // a founder approves
    const fp = await (await browser.newContext({ baseURL: 'http://localhost:5273' })).newPage()
    await loginAs(fp, acct('founder'))
    await fp.goto(runUrl.replace('http://localhost:5273', ''))
    await fp.getByRole('button', { name: 'Approve' }).click()
    await fp.getByRole('dialog').getByRole('button', { name: 'Approve' }).click()
    await expect(fp.getByText('Approved').first()).toBeVisible()
    await expect(fp.getByRole('button', { name: 'Mark as paid' })).toBeVisible()

    // the employee now reads it
    await e.reload()
    const row = e.getByRole('row', { name: new RegExp(`${monthLabel} ${now.getFullYear()}`) })
    await expect(row).toBeVisible()
    await row.getByRole('button', { name: 'View' }).click()
    dlg = e.getByRole('dialog')
    await expect(dlg.getByText('E2E housing')).toBeVisible()
    await expect(dlg.getByText('Basic salary')).toBeVisible()
    await expect(dlg.getByRole('button', { name: /Print/ })).toBeEnabled()
    done()
  })

  test('F30-N1 other employees, managers and the board cannot reach payroll', async ({ page }) => {
    await loginAs(page, acct('e2'))
    await page.goto('/payroll')
    await expect(page.getByRole('heading', { name: 'Payroll' })).toHaveCount(0)
    await page.goto('/payslips')
    await expect(page.getByText('No payslips yet')).toBeVisible()                           // e2 has no pay structure, so no payslip: and sees nobody else's
    const t = { e2: await token(acct('e2')), mgr: await token(acct('mgr')) }
    for (const who of ['e2', 'mgr'] as const) {
      expect((await api('GET', '/payroll/runs', t[who])).status).toBe(403)
      expect((await api('GET', '/payroll/components', t[who])).status).toBe(403)
    }
    const f = await token(acct('founder'))
    const runs = (await api('GET', '/payroll/runs', f)).body.items
    const slips = (await api('GET', `/payroll/runs/${runs[0].id}`, f)).body.payslips
    expect((await api('GET', `/payroll/payslips/${slips[0].id}`, t.e2)).status).toBe(404)   // not someone else's payslip, even though it is approved
    expect((await api('GET', `/payroll/payslips/${slips[0].id}`, t.mgr)).status).toBe(404)
  })
})
