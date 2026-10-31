import { test, expect, type Page } from '@playwright/test'
import { acct, loginAs, watchErrors, a11y, api, token } from '../helpers'

async function fillNew(page: Page, name: string, email: string, pw = 'Pass1234') {
  await page.getByRole('button', { name: '+ Add employee' }).click()
  const dlg = page.getByRole('dialog')
  await dlg.getByLabel('Full name').fill(name)
  await dlg.getByLabel('Work email').fill(email)
  await dlg.getByLabel('Temporary password').fill(pw)
  return dlg
}

test.describe('F03 employees (HR)', () => {
  test.beforeEach(async ({ page }) => { await loginAs(page, acct('hr')); await page.goto('/employees') })

  test('F03-H1 HR adds an employee and sees them in the list', async ({ page }) => {
    const done = watchErrors(page)
    const dlg = await fillNew(page, 'Nora Newhire', 'nora@acme.com')
    await dlg.getByRole('button', { name: 'Create employee' }).click()
    await expect(dlg).toBeHidden()
    await expect(page.getByRole('heading', { name: 'Nora Newhire' })).toBeVisible() // app opens the new employee's page
    done()
  })

  test('F03-E1 emoji, accents and long names are stored intact', async ({ page }) => {
    const dlg = await fillNew(page, 'Zoë Ñandú 😀 ' + 'x'.repeat(40), 'zoe@acme.com')
    await dlg.getByRole('button', { name: 'Create employee' }).click()
    await expect(dlg).toBeHidden()
    await expect(page.getByText('Zoë Ñandú 😀').first()).toBeVisible()
  })

  test('F03-E2 double click on Create makes exactly one employee', async ({ page }) => {
    const dlg = await fillNew(page, 'Dana Double', 'dana@acme.com')
    await dlg.getByRole('button', { name: 'Create employee' }).dblclick()
    await expect(dlg).toBeHidden()
    await expect(page.getByRole('heading', { name: 'Dana Double' })).toBeVisible()
    const f = await token(acct('founder'))
    const r = await api('GET', '/employees?page_size=100&q=Dana', f)
    expect(r.body.items.filter((u: { email: string }) => u.email === 'dana@acme.com')).toHaveLength(1)
  })

  test('F03-N1 duplicate email is rejected with a visible message', async ({ page }) => {
    const dlg = await fillNew(page, 'Elena Clone', 'e1@acme.com')
    await dlg.getByRole('button', { name: 'Create employee' }).click()
    await expect(dlg).toBeVisible()
    await expect(dlg.getByRole('alert').or(dlg.getByText(/already|exists|in use/i)).first()).toBeVisible()
  })

  test('F03-N2 empty form does not close the dialog', async ({ page }) => {
    await page.getByRole('button', { name: '+ Add employee' }).click()
    const dlg = page.getByRole('dialog')
    await dlg.getByRole('button', { name: 'Create employee' }).click()
    await expect(dlg).toBeVisible()
  })

  test('F03-N3 password outside the 4-12 character rule is refused', async ({ page }) => {
    const dlg = await fillNew(page, 'Pat Pass', 'pat@acme.com', 'x'.repeat(30))
    await dlg.getByRole('button', { name: 'Create employee' }).click()
    await expect(dlg).toBeVisible()
  })

  test('F03-E3 list page passes axe and works at phone width', async ({ page }) => {
    await a11y(page, 'employees')
    await page.setViewportSize({ width: 375, height: 812 })
    await expect(page.getByRole('heading', { name: 'Employees' }).first()).toBeVisible()
  })
})
