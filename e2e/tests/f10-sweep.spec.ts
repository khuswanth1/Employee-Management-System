import { test, expect } from '@playwright/test'
import { watchErrors, a11y } from '../helpers'

// Every screen a role can reach: it renders, makes no 5xx, logs no console errors, passes axe (serious/critical)
// and has no horizontal scroll at phone width.
const COMMON = ['/', '/teams', '/attendance', '/holidays', '/departments', '/chat', '/meetings', '/notifications', '/profile', '/payslips', '/performance', '/org-chart']
const ROUTES: Record<string, string[]> = {
  founder: [...COMMON, '/my-tasks', '/teams/analytics', '/updates/team', '/attendance/team', '/attendance/corrections', '/attendance/setup', '/leave/approvals', '/leave/balances', '/payroll', '/lifecycle', '/employees', '/branches', '/managers', '/board-members', '/board', '/webhooks', '/admin'],
  hr: [...COMMON, '/my-tasks', '/projects', '/updates', '/updates/team', '/attendance/team', '/attendance/corrections', '/attendance/setup', '/leave', '/leave/approvals', '/leave/balances', '/payroll', '/lifecycle', '/employees', '/escalations', '/admin', '/teams/analytics'],
  mgr: [...COMMON, '/my-tasks', '/projects', '/updates', '/updates/team', '/attendance/team', '/attendance/corrections', '/leave', '/leave/approvals', '/leave/balances', '/employees', '/escalations', '/teams/analytics'],
  e1: [...COMMON, '/my-tasks', '/projects', '/updates', '/leave', '/escalations'],
  board: ['/chat', '/board', '/profile', '/notifications'],
  platform: ['/platform'],
}

for (const [role, routes] of Object.entries(ROUTES)) {
  test.describe(`F10 sweep as ${role}`, () => {
    test.use({ storageState: `.auth/${role}.json` })
    for (const route of routes) {
      test(`F10 ${role} ${route}`, async ({ page }) => {
        const done = watchErrors(page)
        await page.goto(route)
        await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible()
        await expect(page.getByText('Page not found')).toHaveCount(0)
        await page.waitForLoadState('networkidle')
        await expect(page.getByText(/something went wrong|unexpected error/i)).toHaveCount(0)
        await a11y(page, `${role} ${route}`)
        await page.setViewportSize({ width: 375, height: 812 })
        await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), { message: 'no horizontal scroll at 375px (after charts reflow)', timeout: 5000 }).toBe(true)
        done()
      })
    }
  })
}
