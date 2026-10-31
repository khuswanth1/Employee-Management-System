import { test, expect } from '@playwright/test'
import { acct, loginAs, watchErrors, api, token } from '../helpers'

test.describe('F07 projects and tasks', () => {
  test('F07-H1 employee sees their project and task', async ({ page }) => {
    const done = watchErrors(page)
    await loginAs(page, acct('e1'))
    await page.goto('/projects')
    await expect(page.getByText('Customer Portal Redesign').first()).toBeVisible()
    await page.goto('/my-tasks')
    await page.getByRole('tab', { name: 'Project tasks' }).click()   // assigned project tasks live on their own tab now
    await expect(page.getByText('Wireframes').first()).toBeVisible()
    done()
  })

  test('F07-N1 employee not on the project cannot list it', async () => {
    const e3 = await token(acct('e3'))
    const list = await api('GET', '/projects', e3)
    const names = (list.body.items ?? []).map((p: { name: string }) => p.name)
    expect(names).not.toContain('Customer Portal Redesign')
  })

  test('F07-N2 employee cannot create projects', async () => {
    const e = await token(acct('e1'))
    expect([403, 404]).toContain((await api('POST', '/projects', e, { name: 'Rogue', status: 'active' })).status)
  })

  test('F07-E1 manager creates a project through the dialog (emoji name)', async ({ page }) => {
    await loginAs(page, acct('mgr'))
    await page.goto('/projects')
    await page.getByRole('button', { name: /New project/ }).first().click()
    const dlg = page.getByRole('dialog')
    await dlg.getByRole('textbox', { name: /name/i }).first().fill('Émoji Project 🚀')
    await dlg.getByRole('button', { name: /Create|Save/ }).last().click()
    await expect(page.getByText('Émoji Project 🚀').first()).toBeVisible()
  })
})
