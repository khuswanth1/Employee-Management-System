import { test, expect, type Page } from '@playwright/test'
import { a11y, acct, api, loginAs, token, watchErrors } from '../helpers'

async function idOf(email: string) {
  const f = await token(acct('founder'))
  const r = await api('GET', '/employees?page_size=100', f)
  return r.body.items.find((u: any) => u.email === email).id as number
}

const noSideScroll = async (page: Page, label: string) => {
  const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(over, `horizontal overflow on ${label}`).toBeLessThanOrEqual(1)
}

test.describe('F28 edge cases on the new screens', () => {
  test('F28-E1 phone width: employee page tabs, departments and branches have no sideways scroll and pass axe', async ({ page }) => {
    const done = watchErrors(page)
    const e3 = await idOf(acct('e3'))
    await loginAs(page, acct('founder')) // sign in at desktop width (the menu is a drawer on phones), then shrink
    await page.setViewportSize({ width: 375, height: 812 })
    for (const tab of ['Overview', 'Employment', 'Personal', 'Documents', 'Team & projects']) {
      await page.goto(`/employees/${e3}`)
      await page.getByRole('tab', { name: tab }).click()
      await noSideScroll(page, `employee ${tab}`)
    }
    await a11y(page, 'employee page at 375px')
    await page.goto('/departments'); await expect(page.getByRole('table', { name: 'Departments' })).toBeVisible()
    await a11y(page, 'departments at 375px')
    await page.goto('/branches'); await expect(page.getByRole('heading', { name: 'Branches & locations' })).toBeVisible()
    await noSideScroll(page, 'branches')
    await page.getByRole('button', { name: 'Edit Headquarters' }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await a11y(page, 'branch dialog at 375px')
    done()
  })

  test('F28-E2 keyboard only: Enter opens an employee row; arrow keys switch profile tabs', async ({ page }) => {
    await loginAs(page, acct('hr'))
    await page.goto('/employees')
    await page.getByRole('row', { name: /Priya Designer/ }).focus()
    await page.keyboard.press('Enter')
    await expect(page).toHaveURL(/\/employees\/\d+$/)
    const overview = page.getByRole('tab', { name: 'Overview' })
    await overview.focus()
    await page.keyboard.press('ArrowRight')
    await expect(page.getByRole('tab', { name: 'Employment' })).toHaveAttribute('aria-selected', 'true')
    await page.keyboard.press('End')
    await expect(page.getByRole('tab', { name: 'Team & projects' })).toHaveAttribute('aria-selected', 'true')
  })

  test('F28-E3 offline save keeps what was typed and works after reconnecting', async ({ page, context }) => {
    const e3 = await idOf(acct('e3'))
    await loginAs(page, acct('hr'))
    await page.goto(`/employees/${e3}`)
    await page.getByRole('tab', { name: 'Employment' }).click()
    await page.getByLabel('Employment category').fill('Offline attempt')
    await context.setOffline(true)
    await page.getByRole('button', { name: 'Save changes' }).first().click()
    await expect(page.getByRole('alert').first()).toContainText('Cannot reach the server')
    await expect(page.getByLabel('Employment category')).toHaveValue('Offline attempt')
    await context.setOffline(false)
    await page.getByRole('button', { name: 'Save changes' }).first().click()
    await expect(page.getByText('Saved', { exact: true })).toBeVisible()
    const hr = await token(acct('hr'))
    expect((await api('GET', `/employees/${e3}/profile`, hr)).body.employment_category).toBe('Offline attempt')
  })

  test('F28-E4 session expires mid-edit: the next save sends the person to sign-in, never a 5xx', async ({ page, context }) => {
    const server5xx: string[] = []
    page.on('response', (r) => { if (r.status() >= 500) server5xx.push(`${r.status()} ${r.url()}`) })
    const e3 = await idOf(acct('e3'))
    await loginAs(page, acct('hr'))
    await page.goto(`/employees/${e3}`)
    await page.getByRole('tab', { name: 'Employment' }).click()
    await page.getByLabel('Job level').fill('L9')
    await context.clearCookies()
    await page.getByRole('button', { name: 'Save changes' }).first().click()
    await expect(page).toHaveURL(/\/login/)
    expect(server5xx).toEqual([])
    const hr = await token(acct('hr'))
    expect((await api('GET', `/employees/${e3}/profile`, hr)).body.job_level).not.toBe('L9')
  })

  test('F28-E5 two tabs: different sections both persist; the same field is last-write-wins', async ({ browser }) => {
    const e3 = await idOf(acct('e3'))
    const ctx = await browser.newContext({ baseURL: 'http://localhost:5273' })
    const a = await ctx.newPage(); const b = await ctx.newPage()
    await loginAs(a, acct('hr'))
    for (const p of [a, b]) { await p.goto(`/employees/${e3}`); await p.getByRole('tab', { name: 'Employment' }).click() }
    await a.getByLabel('Notice period (days)').fill('45')
    await b.getByLabel('Display name').fill('Priya D.')
    await a.getByRole('button', { name: 'Save changes' }).first().click()
    await expect(a.getByText('Saved', { exact: true }).first()).toBeVisible()
    await b.getByRole('button', { name: 'Save changes' }).nth(1).click()
    await expect(b.getByText('Saved', { exact: true }).first()).toBeVisible()
    const hr = await token(acct('hr'))
    let p = (await api('GET', `/employees/${e3}/profile`, hr)).body
    expect(p.notice_period_days).toBe(45); expect(p.display_name).toBe('Priya D.')
    // same field from both tabs: the later save wins and nothing errors
    await a.getByLabel('Job level').fill('L5'); await a.getByRole('button', { name: 'Save changes' }).first().click()
    await expect(a.getByText('Saved', { exact: true }).first()).toBeVisible()
    await b.getByLabel('Job level').fill('L6'); await b.getByRole('button', { name: 'Save changes' }).first().click()
    await expect(b.getByText('Saved', { exact: true }).first()).toBeVisible()
    p = (await api('GET', `/employees/${e3}/profile`, hr)).body
    expect(p.job_level).toBe('L6'); expect(p.notice_period_days).toBe(45)
    await ctx.close()
  })

  test('F28-E6 double-clicking Save sends one change and shows no error', async ({ page }) => {
    const done = watchErrors(page)
    const e3 = await idOf(acct('e3'))
    const hr = await token(acct('hr'))
    const before = (await api('GET', '/admin/audit-logs?action=employee.profile_updated&page_size=100', await token(acct('founder')))).body.total
    await loginAs(page, acct('hr'))
    await page.goto(`/employees/${e3}`)
    await page.getByRole('tab', { name: 'Employment' }).click()
    await page.getByLabel('Job level').fill('L7')
    await page.getByRole('button', { name: 'Save changes' }).first().dblclick()
    await expect(page.getByText('Saved', { exact: true })).toBeVisible()
    const after = (await api('GET', '/admin/audit-logs?action=employee.profile_updated&page_size=100', await token(acct('founder')))).body.total
    expect(after - before).toBe(1)
    expect((await api('GET', `/employees/${e3}/profile`, hr)).body.job_level).toBe('L7')
    done()
  })

  test('F28-N1 emoji, accents and a very long value are stored intact or refused cleanly', async () => {
    const e3 = await idOf(acct('e3')); const hr = await token(acct('hr'))
    const ok = await api('PATCH', `/employees/${e3}/profile`, hr, { middle_name: 'Zoë 🚀', skills: ['café', 'データ'] })
    expect(ok.status).toBe(200); expect(ok.body.middle_name).toBe('Zoë 🚀'); expect(ok.body.skills).toEqual(['café', 'データ'])
    const long = await api('PATCH', `/employees/${e3}/profile`, hr, { middle_name: 'x'.repeat(5000) })
    expect(long.status).toBe(422)
  })
})
