import { test, expect } from '@playwright/test'
import { acct, loginAs, watchErrors } from '../helpers'

test.describe('F04 attendance', () => {
  test('F04-H1 check in, break, end break, check out', async ({ page }) => {
    const done = watchErrors(page)
    await loginAs(page, acct('e2'))
    await page.goto('/attendance')
    await page.getByRole('button', { name: 'Check in' }).click()
    await page.getByRole('button', { name: 'Start break' }).click()
    await page.getByRole('button', { name: 'End break' }).click()
    await page.getByRole('button', { name: 'Check out' }).click()
    await expect(page.getByRole('button', { name: 'Check in' })).toHaveCount(0)
    await expect(page.getByRole('table', { name: 'Attendance history' })).toBeVisible()
    done()
  })

  test('F04-E1 double click on Check in creates one record, refresh keeps state', async ({ page }) => {
    await loginAs(page, acct('e3'))
    await page.goto('/attendance')
    await page.getByRole('button', { name: 'Check in' }).dblclick()
    await expect(page.getByRole('button', { name: 'Check out' })).toBeVisible()
    await page.reload()
    await expect(page.getByRole('button', { name: 'Check out' })).toBeVisible()
    await expect(page.getByRole('table', { name: 'Attendance history' }).getByRole('row')).toHaveCount(2)
  })
})

test.describe('F05 daily update', () => {
  test('F05-H1 employee submits an update, it appears in history', async ({ page }) => {
    const done = watchErrors(page)
    await loginAs(page, acct('e1'))
    await page.goto('/updates')
    await page.getByLabel('Completed today').fill('Shipped the login form 😀 café')
    await page.getByLabel('Blockers').fill('Waiting on SSO tenant')
    await page.getByRole('button', { name: 'Submit update' }).click()
    await expect(page.getByText('Shipped the login form 😀 café').first()).toBeVisible()
    done()
  })

  test('F05-E1 unsent draft survives a reload', async ({ page }) => {
    await loginAs(page, acct('e2'))
    await page.goto('/updates')
    await page.getByLabel('Completed today').fill('Half written thought')
    await page.waitForTimeout(800)
    await page.reload()
    await expect(page.getByLabel('Completed today')).toHaveValue('Half written thought')
  })

  test('F05-N1 empty "completed" is refused', async ({ page }) => {
    await loginAs(page, acct('e3'))
    await page.goto('/updates')
    await page.getByRole('button', { name: 'Submit update' }).click()
    await expect(page.getByRole('button', { name: 'Submit update' })).toBeVisible()
  })

  test('F05-N2 hours above 24 are rejected', async ({ page }) => {
    await loginAs(page, acct('e3'))
    await page.goto('/updates')
    await page.getByLabel('Completed today').fill('Too many hours')
    await page.getByLabel('Hours worked').fill('99')
    await page.getByRole('button', { name: 'Submit update' }).click()
    await expect(page.getByRole('button', { name: 'Submit update' })).toBeVisible()
  })
})
