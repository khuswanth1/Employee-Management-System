import { expect, type Page } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

export const API = 'http://127.0.0.1:8100/api/v1'
export const PW = 'Demo-Pw0rd!'
export const PLATFORM = { email: 'platform@example.com', password: 'E2e-Platform-Pw1!' }
export const acct = (key: string, slug = 'acme') => `${key}@${slug}.com`

export async function api(method: string, url: string, token?: string, body?: unknown) {
  const r = await fetch(API + url, {
    method,
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const text = await r.text()
  return { status: r.status, body: text ? JSON.parse(text) : null }
}

export async function token(email: string, password = PW) {
  const r = await api('POST', '/auth/login', undefined, { email, password })
  if (r.status !== 200) throw new Error(`login ${email} -> ${r.status} ${JSON.stringify(r.body)}`)
  return r.body.access_token as string
}

export async function uiLogin(page: Page, email: string, password = PW) {
  await page.goto('/login')
  await page.getByRole('textbox', { name: 'Email' }).fill(email)
  await page.getByRole('textbox', { name: 'Password' }).fill(password)
  await page.getByRole('button', { name: 'Sign in' }).click()
}

/** Fail the test on console errors and 5xx responses. Call at the start of a test. */
export function watchErrors(page: Page) {
  const problems: string[] = []
  page.on('console', (m) => {
    if (m.type() !== 'error') return
    const t = m.text()
    // 4xx are exercised on purpose by negative cases; browsers log them as console errors
    if (/status of 4\d\d/.test(t)) return
    problems.push(`console: ${t}`)
  })
  page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`))
  page.on('response', (r) => { if (r.status() >= 500) problems.push(`${r.status()} ${r.url()}`) })
  return () => expect(problems, 'console errors / 5xx').toEqual([])
}

export async function a11y(page: Page, label: string) {
  const res = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze()
  const serious = res.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
  expect(serious.map((v) => `${v.id} (${v.nodes.length})`), `axe on ${label}`).toEqual([])
}

// local calendar date: nextWeekday() works in local time, so formatting in UTC shifted the day for anyone east of UTC after midnight
export const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
export function nextWeekday(offset: number) {
  const d = new Date(); d.setDate(d.getDate() + offset)
  while (d.getDay() === 0 || d.getDay() === 6) d.setDate(d.getDate() + 1)
  return d
}

/** Sign in and wait until the app shell is up (tokens are stored), so a following page.goto keeps the session. */
export async function loginAs(page: Page, email: string, password = PW) {
  await uiLogin(page, email, password)
  await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible()
}
