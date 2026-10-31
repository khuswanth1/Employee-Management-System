import { test, expect } from '@playwright/test'
import { acct, api, iso, loginAs, token, watchErrors } from '../helpers'

test.describe.configure({ mode: 'serial' })

test.describe('F31 performance review end to end', () => {
  test('F31-H1 HR starts a cycle, the employee and manager complete it, the employee acknowledges', async ({ page, browser }) => {
    const done = watchErrors(page)
    const today = new Date(); const end = new Date(); end.setDate(end.getDate() + 90)

    // HR creates and starts the cycle in the browser
    await loginAs(page, acct('hr'))
    await page.goto('/performance')
    await page.getByRole('tab', { name: 'Cycles' }).click()
    await page.getByRole('button', { name: 'New cycle' }).click()
    let dlg = page.getByRole('dialog')
    await dlg.getByLabel('Name').fill('E2E annual review')
    await dlg.getByLabel('Starts').fill(iso(today))
    await dlg.getByLabel('Ends').fill(iso(end))
    await dlg.getByLabel('Competencies on the form').fill('Quality, Teamwork')
    await dlg.getByRole('button', { name: 'Create' }).click()
    await expect(dlg).toBeHidden()
    page.once('dialog', (d) => d.accept())
    await page.getByRole('row', { name: /E2E annual review/ }).getByRole('button', { name: 'Start' }).click()
    await expect(page.getByRole('row', { name: /E2E annual review/ })).toContainText('active')

    // the employee proposes a goal
    const e = await (await browser.newContext({ baseURL: 'http://localhost:5273' })).newPage()
    await loginAs(e, acct('e1'))
    await e.goto('/performance')
    await e.getByRole('button', { name: 'Add goal' }).click()
    dlg = e.getByRole('dialog')
    await dlg.getByLabel('Title').fill('Deliver the customer portal')
    await dlg.getByLabel(/Weight/).fill('100')
    await dlg.getByRole('button', { name: 'Add' }).click()
    await expect(dlg).toBeHidden()
    await expect(e.getByText('waiting to be agreed')).toBeVisible()

    // the manager agrees it
    const m = await (await browser.newContext({ baseURL: 'http://localhost:5273' })).newPage()
    await loginAs(m, acct('mgr'))
    await m.goto('/performance')
    await m.getByRole('tab', { name: 'Team' }).click()
    await m.getByRole('row', { name: /Elena Engineer/ }).getByRole('button', { name: 'Goals' }).click()
    await m.getByRole('button', { name: 'Agree' }).click()
    await expect(m.getByText('waiting to be agreed')).toHaveCount(0)
    await m.keyboard.press('Escape')

    // the employee writes and submits the self review
    await e.reload()
    await e.getByRole('button', { name: 'Write self review' }).click()
    dlg = e.getByRole('dialog')
    await dlg.getByLabel('Overall self rating').selectOption('4')
    await dlg.getByLabel('Self rating for Quality').selectOption('4')
    await dlg.getByLabel('Self rating for Teamwork').selectOption('5')
    await dlg.getByLabel('Self rating for goal Deliver the customer portal').selectOption('4')
    await dlg.getByLabel(/How did the cycle go/).fill('I delivered the portal on time.')
    await dlg.getByRole('button', { name: 'Submit self review' }).click()
    await expect(dlg).toBeHidden()

    // the manager reviews; until submitted the employee sees nothing of it
    await m.reload()
    await m.getByRole('tab', { name: 'Team' }).click()
    await m.getByRole('row', { name: /Elena Engineer/ }).getByRole('button', { name: 'Review' }).click()
    dlg = m.getByRole('dialog')
    await expect(dlg.getByText('I delivered the portal on time.')).toBeVisible()
    await dlg.getByLabel('Overall manager rating').selectOption('3')
    await dlg.getByLabel('Manager rating for Quality').selectOption('3')
    await dlg.getByLabel('Manager rating for Teamwork').selectOption('4')
    await dlg.getByLabel(/^Assessment/).fill('Reliable delivery with room to grow.')
    await dlg.getByRole('button', { name: 'Save draft' }).click()
    const t1 = await token(acct('e1'))
    const mine = (await api('GET', '/performance/reviews/mine', t1)).body.items[0]
    const seen = (await api('GET', `/performance/reviews/${mine.id}`, t1)).body
    expect(seen.manager_rating).toBeNull()
    expect(seen.manager_comments).toBeNull()
    await dlg.getByRole('button', { name: 'Submit review' }).click()
    await expect(dlg).toBeHidden()

    // the employee reads it and acknowledges
    await e.reload()
    await expect(e.getByText("Your manager's review is ready to read.")).toBeVisible()
    await e.getByRole('button', { name: 'Open' }).click()
    dlg = e.getByRole('dialog')
    await expect(dlg.getByText('Reliable delivery with room to grow.')).toBeVisible()
    await dlg.getByRole('button', { name: 'Acknowledge' }).click()
    await expect(dlg).toBeHidden()
    await e.reload()
    await expect(e.getByText('Acknowledged').first()).toBeVisible()
    done()
  })

  test('F31-N1 colleagues, other managers and the board cannot read someone else\'s review or goals', async () => {
    const t = { e1: await token(acct('e1')), e2: await token(acct('e2')), board: await token(acct('board')) }
    const cyc = (await api('GET', '/performance/cycles', t.e1)).body.items[0]
    const rid = (await api('GET', '/performance/reviews/mine', t.e1)).body.items[0].id
    const e1id = (await api('GET', '/auth/me', t.e1)).body.id
    for (const who of ['e2', 'board'] as const) {
      expect((await api('GET', `/performance/reviews/${rid}`, t[who])).status).toBe(404)
      expect((await api('GET', `/performance/goals?cycle_id=${cyc.id}&user_id=${e1id}`, t[who])).status).toBe(404)
      expect((await api('GET', `/performance/history/${e1id}`, t[who])).status).toBe(404)
    }
    expect((await api('GET', `/performance/cycles/${cyc.id}/summary`, t.e2)).status).toBe(403)
    expect((await api('POST', '/performance/cycles', t.e2, { name: 'x', start_date: '2026-01-01', end_date: '2026-12-31' })).status).toBe(403)
  })
})
