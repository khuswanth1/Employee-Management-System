import { test, expect } from '@playwright/test'
import { a11y, acct, api, loginAs, token, watchErrors } from '../helpers'

test.describe('F27 departments and branches', () => {
  test('F27-H1 HR creates a department with a code, then marks it inactive (UI)', async ({ page }) => {
    const done = watchErrors(page)
    await loginAs(page, acct('hr'))
    await page.goto('/departments')
    await page.getByRole('button', { name: 'New department' }).first().click()
    const dlg = page.getByRole('dialog')
    await dlg.getByLabel('Department name').fill('Quality Assurance')
    await dlg.getByLabel('Department code').fill('qa-1')
    await a11y(page, 'new department dialog')
    await dlg.getByRole('button', { name: 'Create department' }).click()
    const row = page.getByRole('row', { name: /Quality Assurance/ })
    await expect(row).toBeVisible()
    await expect(row.getByText('QA-1')).toBeVisible()
    await row.getByRole('button', { name: 'Edit' }).click()
    await page.getByRole('dialog').getByLabel('Status').selectOption('inactive')
    await page.getByRole('dialog').getByRole('button', { name: 'Save changes' }).click()
    await expect(page.getByRole('row', { name: /Quality Assurance/ }).getByText('Inactive')).toBeVisible()
    await a11y(page, 'departments page')
    done()
  })

  test('F27-N1 a duplicate department code keeps the dialog open and saves nothing', async ({ page }) => {
    const hr = await token(acct('hr'))
    await api('POST', '/departments', hr, { name: 'Dup Source', code: 'DUPX' })
    await loginAs(page, acct('hr'))
    await page.goto('/departments')
    await page.getByRole('button', { name: 'New department' }).first().click()
    const dlg = page.getByRole('dialog')
    await dlg.getByLabel('Department name').fill('Dup Target')
    await dlg.getByLabel('Department code').fill('dupx')
    await dlg.getByRole('button', { name: 'Create department' }).click()
    await expect(dlg.getByRole('alert')).toContainText('A department with this code already exists')
    await expect(dlg).toBeVisible()
  })

  test('F27-N2 department cycles and non-HR writes are refused', async () => {
    const hr = await token(acct('hr')); const e1 = await token(acct('e1'))
    const a = (await api('POST', '/departments', hr, { name: 'Cycle A' })).body
    const b = (await api('POST', '/departments', hr, { name: 'Cycle B', parent_id: a.id })).body
    expect((await api('PATCH', `/departments/${a.id}`, hr, { parent_id: b.id })).status).toBe(400)
    expect((await api('POST', '/departments', e1, { name: 'Nope' })).status).toBe(403)
  })

  test('F27-H2 founder gets a timezone error beside the field, then saves a valid branch schedule (UI)', async ({ page }) => {
    const done = watchErrors(page)
    await loginAs(page, acct('founder'))
    await page.goto('/branches')
    await page.getByRole('button', { name: 'Edit Headquarters' }).click()
    const dlg = page.getByRole('dialog')
    await dlg.getByLabel('Timezone').fill('Mars/Base')
    await dlg.getByRole('button', { name: 'Save changes' }).click()
    await expect(dlg.getByText(/Unknown timezone/)).toBeVisible()
    await dlg.getByLabel('Timezone').fill('Asia/Kolkata')
    await dlg.getByRole('button', { name: 'Save changes' }).click()
    await expect(dlg).toBeHidden()
    await expect(page.getByText(/Asia\/Kolkata/)).toBeVisible()
    await a11y(page, 'branches page')
    done()
  })

  test('F27-N3 only a founder edits branches; a branch manager must be in that branch', async () => {
    const hr = await token(acct('hr')); const f = await token(acct('founder'))
    const hq = (await api('GET', '/branches', f)).body.items.find((b: any) => b.code === 'HQ')
    expect((await api('PATCH', `/branches/${hq.id}`, hr, { timezone: 'UTC' })).status).toBe(403)
    const e1 = (await api('GET', '/employees/directory', f)).body.items.find((u: any) => u.email === acct('e1'))
    expect((await api('PATCH', `/branches/${hq.id}`, f, { manager_id: e1.id })).status).toBe(400)
  })
})
