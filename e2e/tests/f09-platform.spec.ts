import { test, expect } from '@playwright/test'
import { api, PLATFORM, PW, loginAs } from '../helpers'

test('F09-H1 platform admin deletes a company after typing its URL name', async ({ page }) => {
  const admin = (await api('POST', '/auth/platform/login', undefined, PLATFORM)).body.access_token
  const made = await api('POST', '/platform/companies', admin, { name: 'Doomed Inc', slug: 'doomed', founder_name: 'Dee Doomed', founder_email: 'dee@doomed.com', founder_password: PW })
  expect(made.status).toBe(201)
  await loginAs(page, PLATFORM.email, PLATFORM.password)
  await page.goto('/platform')
  await page.getByRole('row', { name: /Doomed Inc/ }).getByRole('button', { name: 'Delete' }).click()
  const dlg = page.getByRole('dialog')
  const confirm = dlg.getByRole('button', { name: 'Delete company permanently' })
  await expect(confirm).toBeDisabled()
  await dlg.getByRole('textbox').fill('doomed')
  await confirm.click()
  await expect(page.getByRole('row', { name: /Doomed Inc/ })).toHaveCount(0)
  expect((await api('GET', `/platform/companies/${made.body.id}`, admin)).status).toBe(404)
})

test('F09-N1 duplicate company URL name returns 409', async () => {
  const admin = (await api('POST', '/auth/platform/login', undefined, PLATFORM)).body.access_token
  const r = await api('POST', '/platform/companies', admin, { name: 'Acme Again', slug: 'acme', founder_name: 'A B', founder_email: 'ab@acme2.com', founder_password: PW })
  expect(r.status).toBe(409)
})
