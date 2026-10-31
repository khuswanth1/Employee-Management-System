import { test, expect } from '@playwright/test'
import { acct, loginAs, watchErrors, iso, nextWeekday, api, token } from '../helpers'

test.describe('F06 leave request and approval', () => {
  const from = iso(nextWeekday(20))
  const to = iso(nextWeekday(21))

  test('F06-H1 employee applies, manager approves, employee sees Approved', async ({ page, browser }) => {
    const done = watchErrors(page)
    await loginAs(page, acct('e2'))
    await page.goto('/leave')
    await page.getByRole('button', { name: 'Apply for leave' }).first().click()
    const dlg = page.getByRole('dialog')
    await dlg.getByLabel('Leave type').selectOption({ index: 1 })
    await dlg.getByLabel('From').fill(from)
    await dlg.getByLabel('To').fill(to)
    await dlg.getByLabel('Reason').fill('Family trip')
    await dlg.getByRole('button', { name: 'Submit request' }).click()
    await expect(dlg).toBeHidden()
    await expect(page.getByRole('table', { name: 'My leave requests' }).getByText(/pending/i).first()).toBeVisible()

    const m = await (await browser.newContext({ baseURL: 'http://localhost:5273' })).newPage()
    await loginAs(m, acct('mgr'))
    await m.goto('/leave/approvals')
    await m.getByRole('row', { name: /Ethan Engineer/ }).getByRole('button', { name: 'Approve' }).click()
    await m.getByRole('dialog').getByRole('button', { name: /Approve/ }).click()
    await expect(m.getByRole('dialog')).toBeHidden()

    await page.reload()
    await expect(page.getByRole('table', { name: 'My leave requests' }).getByText(/approved/i).first()).toBeVisible()
    done()
  })

  test('F06-N1 end date before start date is refused by the API', async () => {
    const t = await token(acct('e1'))
    const types = await api('GET', '/leave/types', t)
    const r = await api('POST', '/leave/requests', t, { leave_type_id: types.body.items[0].id, start_date: iso(nextWeekday(40)), end_date: iso(nextWeekday(30)), reason: 'x' })  // always a week apart, whatever weekday today is
    expect(r.status).toBeGreaterThanOrEqual(400); expect(r.status).toBeLessThan(500)
  })

  test('F06-N2 employee cannot approve their own leave', async () => {
    const t = await token(acct('e1'))
    const types = await api('GET', '/leave/types', t)
    const d = iso(nextWeekday(60))
    const mine = await api('POST', '/leave/requests', t, { leave_type_id: types.body.items[0].id, start_date: d, end_date: d, reason: 'self' })
    expect(mine.status).toBeLessThan(300)
    const r = await api('POST', `/leave/requests/${mine.body.id}/decision`, t, { approved: true, note: '' })
    expect([403, 404]).toContain(r.status)
  })

  test('F06-N3 overlapping request is refused', async () => {
    const t = await token(acct('e1'))
    const types = await api('GET', '/leave/types', t)
    const d = iso(nextWeekday(60))
    const r = await api('POST', '/leave/requests', t, { leave_type_id: types.body.items[0].id, start_date: d, end_date: d, reason: 'dup' })
    expect(r.status).toBeGreaterThanOrEqual(400); expect(r.status).toBeLessThan(500)
  })
})
