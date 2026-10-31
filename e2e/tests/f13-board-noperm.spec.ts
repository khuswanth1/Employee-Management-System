import { test, expect } from '@playwright/test'
import { acct, api, token, loginAs, PW, watchErrors } from '../helpers'

test('F13-N4 board member without analytics permission sees a clear message, not a broken page', async ({ page }) => {
  const f = await token(acct('founder'))
  const made = await api('POST', '/board/members', f, { email: 'board2@acme.com', full_name: 'Noah NoAccess', password: PW, permissions: [] })
  expect(made.status).toBe(201)
  expect((await api('GET', '/board/analytics', await token('board2@acme.com'))).status).toBe(403)
  const done = watchErrors(page)
  await loginAs(page, 'board2@acme.com')
  await page.goto('/board')
  await expect(page.getByText('No analytics access')).toBeVisible()
  await expect(page.getByText(/analytics.view/)).toBeVisible()
  await expect(page.getByRole('button', { name: /retry|try again/i })).toHaveCount(0)
  done()
})
