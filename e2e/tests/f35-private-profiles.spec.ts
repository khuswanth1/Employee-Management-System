import { test, expect } from '@playwright/test'
import { a11y, acct, api, loginAs, token, watchErrors } from '../helpers'

async function people() {
  const f = await token(acct('founder'))
  const dir = (await api('GET', '/employees/directory', f)).body.items
  return { me: dir.find((u: any) => u.email === acct('e1')), other: dir.find((u: any) => u.email === acct('e2')) }
}

test('F35-P1 an employee opens a colleague from the directory and gets a card, never the personal record', async ({ page }) => {
  const { me, other } = await people()
  const done = watchErrors(page)
  await loginAs(page, acct('e1'))
  await page.goto('/employees')
  await expect(page.getByRole('heading', { name: 'People' })).toBeVisible()
  await expect(page.getByRole('button', { name: /add employee/i })).toHaveCount(0)
  await page.getByRole('searchbox').fill(other.full_name)
  await page.getByRole('row', { name: new RegExp(other.full_name) }).click()
  await expect(page).toHaveURL(new RegExp(`/employees/${other.id}$`))
  await expect(page.getByRole('heading', { name: other.full_name })).toBeVisible()
  await expect(page.getByLabel(`About ${other.full_name}`)).toBeVisible()
  await expect(page.getByText(acct('e2'))).toHaveCount(0)                      // no e-mail for a colleague
  await expect(page.getByRole('tab')).toHaveCount(0)                            // no Personal / Documents / History tabs
  await expect(page.getByText(/visible only to the person, their manager and HR/)).toBeVisible()
  await a11y(page, 'colleague card')

  await page.goto(`/employees/${me.id}`)                                       // their own record is still the full page
  await expect(page.getByRole('tab', { name: 'Documents' })).toBeVisible()
  done()
})

test('F35-P2 org chart names open the card; staff who may open the record get the full page', async ({ page, browser }) => {
  const { other } = await people()
  const done = watchErrors(page)
  await loginAs(page, acct('e1'))
  await page.goto('/org-chart')
  const tree = page.getByRole('tree', { name: 'Organisation chart' })
  await tree.getByRole('link', { name: other.full_name }).click()
  await expect(page.getByLabel(`About ${other.full_name}`)).toBeVisible()
  await expect(page.getByRole('tab')).toHaveCount(0)

  const f = await (await browser.newContext({ baseURL: 'http://localhost:5273' })).newPage()
  await loginAs(f, acct('founder'))
  await f.goto('/org-chart')
  await f.getByRole('tree', { name: 'Organisation chart' }).getByRole('link', { name: other.full_name }).click()
  await expect(f.getByRole('tab', { name: 'Documents' })).toBeVisible()          // the full record
  done()
})
