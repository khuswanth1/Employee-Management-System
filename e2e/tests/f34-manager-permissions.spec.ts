import { test, expect } from '@playwright/test'
import { acct, api, loginAs, PW, token, watchErrors } from '../helpers'

test('F34-P1 a manager without attendance.approve neither sees the requests page nor triggers a 403 by opening it', async ({ page }) => {
  const f = await token(acct('founder'))
  const email = acct('noattmgr')
  const made = await api('POST', '/employees', f, { email, full_name: 'No Attendance Manager', password: PW, role: 'manager' })
  expect(made.status).toBe(201)
  expect((await api('PATCH', `/managers/${made.body.id}`, f, { permissions: ['leave.approve'] })).status).toBe(200)

  const forbidden: string[] = []
  page.on('response', (r) => { if (r.status() === 403) forbidden.push(r.url()) })
  const done = watchErrors(page)
  await loginAs(page, email)
  await expect(page.getByRole('link', { name: 'Leave Approvals' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Attendance Requests' })).toHaveCount(0)
  await page.goto('/attendance/corrections')
  await expect(page.getByRole('heading', { name: 'Attendance corrections' })).toHaveCount(0)
  expect(forbidden.filter((u) => u.includes('/attendance/corrections'))).toEqual([])

  // granting it makes the page appear and work
  expect((await api('PATCH', `/managers/${made.body.id}`, f, { permissions: ['leave.approve', 'attendance.approve'] })).status).toBe(200)
  await page.goto('/attendance/corrections')
  await expect(page.getByRole('heading', { name: 'Attendance corrections' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Attendance Requests' })).toBeVisible()
  done()
})
