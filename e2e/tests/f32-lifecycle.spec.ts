import { test, expect } from '@playwright/test'
import { acct, api, iso, loginAs, PW, token, watchErrors } from '../helpers'

test.describe.configure({ mode: 'serial' })

test.describe('F32 employee lifecycle', () => {
  let empId = 0
  const email = acct('lena')

  test('F32-H1 HR promotes, suspends and reinstates someone; suspension blocks sign-in at once', async ({ page, browser }) => {
    const done = watchErrors(page)
    const f = await token(acct('founder'))
    const mgrId = (await api('GET', '/employees/directory', f)).body.items.find((u: any) => u.email === acct('mgr')).id
    const made = await api('POST', '/employees', f, { email, full_name: 'Lena Lifecycle', password: PW, role: 'employee', manager_id: mgrId, designation: 'Analyst' })
    expect(made.status).toBe(201)
    empId = made.body.id
    expect((await api('PATCH', `/employees/${empId}`, f, { hire_date: '2025-01-01' })).status).toBe(200)

    await loginAs(page, acct('hr'))
    await page.goto(`/employees/${empId}`)
    await page.getByRole('tab', { name: 'History' }).click()
    await expect(page.getByRole('list', { name: 'Employment history' })).toContainText('Joined')
    await page.getByRole('button', { name: 'Promote' }).click()
    let dlg = page.getByRole('dialog')
    await dlg.getByLabel('New title').fill('Senior Analyst')
    await dlg.getByLabel('Job level').fill('L4')
    await dlg.getByLabel('Note').fill('Excellent first year')
    await dlg.getByRole('button', { name: 'Record' }).click()
    await expect(dlg).toBeHidden()
    const first = page.getByRole('list', { name: 'Employment history' }).getByRole('listitem').first()
    await expect(first).toContainText('Promotion')
    await expect(first).toContainText('Analyst → Senior Analyst (L4)')
    await expect(first).toContainText('Excellent first year')

    // the employee is signed in elsewhere; suspension ends that session and blocks a new one
    const e = await (await browser.newContext({ baseURL: 'http://localhost:5273' })).newPage()
    await loginAs(e, email)
    await e.goto('/profile')
    await expect(e.getByRole('heading', { name: 'My profile' })).toBeVisible()
    await page.getByRole('button', { name: 'Suspend' }).click()
    dlg = page.getByRole('dialog')
    await dlg.getByLabel('Reason').fill('Pending a review of access rights')
    await dlg.getByRole('button', { name: 'Suspend' }).click()
    await expect(dlg).toBeHidden()
    await expect(page.getByRole('button', { name: 'Reinstate' })).toBeVisible()
    expect((await api('POST', '/auth/login', undefined, { email, password: PW })).status).toBe(401)
    await e.reload()
    await expect(e).toHaveURL(/login/)

    await page.getByRole('button', { name: 'Reinstate' }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Reinstate' }).click()
    await expect(page.getByRole('button', { name: 'Suspend' })).toBeVisible()
    expect((await api('POST', '/auth/login', undefined, { email, password: PW })).status).toBe(200)
    // the manager reads the history but not the suspension
    const m = await (await browser.newContext({ baseURL: 'http://localhost:5273' })).newPage()
    await loginAs(m, acct('mgr'))
    await m.goto(`/employees/${empId}`)
    await m.getByRole('tab', { name: 'History' }).click()
    const list = m.getByRole('list', { name: 'Employment history' })
    await expect(list).toContainText('Promotion')
    await expect(list).not.toContainText('Suspended')
    await expect(m.getByRole('button', { name: 'Promote' })).toHaveCount(0)
    done()
  })

  test('F32-H2 the employee resigns from My profile, HR sees it on the worklist, then it is withdrawn', async ({ page, browser }) => {
    const done = watchErrors(page)
    const last = new Date(); last.setDate(last.getDate() + 20)
    await loginAs(page, email)
    await page.goto('/profile')
    await page.getByRole('button', { name: 'Submit resignation' }).click()
    const dlg = page.getByRole('dialog')
    await dlg.getByLabel('Last working day').fill(iso(last))
    await dlg.getByRole('button', { name: 'Submit resignation' }).click()
    await expect(dlg).toBeHidden()
    await expect(page.getByText('Your resignation is on record.')).toBeVisible()

    const hr = await (await browser.newContext({ baseURL: 'http://localhost:5273' })).newPage()
    await loginAs(hr, acct('hr'))
    await hr.goto('/lifecycle')
    await expect(hr.getByRole('table', { name: 'Departures' }).getByRole('link', { name: 'Lena Lifecycle' })).toBeVisible()

    page.once('dialog', (d) => d.accept())
    await page.getByRole('button', { name: 'Withdraw resignation' }).click()
    await expect(page.getByRole('button', { name: 'Submit resignation' })).toBeVisible()
    await hr.reload()
    await expect(hr.getByRole('table', { name: 'Departures' }).getByRole('link', { name: 'Lena Lifecycle' })).toHaveCount(0)
    done()
  })

  test('F32-H3 the org chart shows the reporting line, and offboarding removes the person from it', async ({ page }) => {
    const done = watchErrors(page)
    await loginAs(page, acct('e1'))
    await page.goto('/org-chart')
    const tree = page.getByRole('tree', { name: 'Organisation chart' })
    await page.getByRole('button', { name: 'Expand all' }).click()
    await expect(tree.getByText('Lena Lifecycle', { exact: true })).toBeVisible()      // shown, but not a link: an employee cannot open others' records
    await expect(tree.getByText('Marcus Manager', { exact: true })).toBeVisible()
    const f = await token(acct('founder'))
    expect((await api('POST', `/employees/${empId}/offboard`, f, { reason: 'End of e2e' })).status).toBe(200)
    await page.reload()
    await page.getByRole('button', { name: 'Expand all' }).click()
    await expect(page.getByRole('tree', { name: 'Organisation chart' }).getByText('Lena Lifecycle', { exact: true })).toHaveCount(0)
    done()
  })

  test('F32-N1 employees, managers and the board cannot run lifecycle actions or read others\' history', async () => {
    const t = { e2: await token(acct('e2')), mgr: await token(acct('mgr')), board: await token(acct('board')) }
    for (const who of ['e2', 'mgr'] as const) {
      expect((await api('POST', `/employees/${empId}/lifecycle/promotion`, t[who], { designation: 'Chief' })).status).toBe(403)
      expect((await api('POST', `/employees/${empId}/lifecycle/suspend`, t[who], { reason: 'no right' })).status).toBe(403)
    }
    expect((await api('GET', `/employees/${empId}/lifecycle`, t.e2)).status).toBeGreaterThanOrEqual(403)
    expect((await api('GET', `/employees/${empId}/lifecycle`, t.board)).status).toBeGreaterThanOrEqual(403)
    expect((await api('GET', '/lifecycle/due', t.mgr)).status).toBe(403)
    expect((await api('GET', '/org/chart', t.board)).status).toBe(403)
  })
})
