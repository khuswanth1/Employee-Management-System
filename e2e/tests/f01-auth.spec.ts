import { test, expect } from '@playwright/test'
import { acct, PW, PLATFORM, uiLogin, watchErrors, a11y, api } from '../helpers'

test.describe('F01 sign in / sign out', () => {
  test('F01-H1 founder signs in and lands on the dashboard', async ({ page }) => {
    const done = watchErrors(page)
    await uiLogin(page, acct('founder'), PW)
    await expect(page).toHaveURL(/\/$/)
    await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible()
    await a11y(page, 'dashboard (founder)') // KNOWN BUG B-001: progressbar without name
    done()
  })

  test('F01-H2 platform admin lands on /platform', async ({ page }) => {
    await uiLogin(page, PLATFORM.email, PLATFORM.password)
    await expect(page).toHaveURL(/\/platform$/)
    await expect(page.getByText('Acme Corporation').first()).toBeVisible()
  })

  test('F01-H3 session survives refresh and a new tab; no token is readable by the page', async ({ page, context }) => {
    await uiLogin(page, acct('e1'))
    await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible()
    await page.reload()
    await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible()
    const second = await context.newPage()
    await second.goto('/')
    await expect(second.getByRole('navigation', { name: 'Main' })).toBeVisible() // same browser, same URL: still signed in
    const seen = await page.evaluate(() => ({ cookie: document.cookie, s: JSON.stringify(sessionStorage), l: JSON.stringify(localStorage) }))
    expect(seen.cookie).not.toMatch(/ws_access|ws_refresh|ws_device/)
    expect(seen.s + seen.l).not.toMatch(/eyJ|access_token|refresh_token/)
    const cookies = await context.cookies()
    for (const n of ['ws_access', 'ws_refresh', 'ws_device']) expect(cookies.find((c) => c.name === n)?.httpOnly, n).toBe(true)
  })

  test('F01-H5 a session copied to another browser does not work there', async ({ page, browser }) => {
    await uiLogin(page, acct('e1'))
    await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible()
    const access = (await page.context().cookies()).find((c) => c.name === 'ws_access')!
    const other = await browser.newContext({ baseURL: 'http://localhost:5273' })
    await other.addCookies([{ ...access }])
    const p2 = await other.newPage()
    await p2.goto('/')
    await expect(p2).toHaveURL(/\/login/)
    const r = await other.request.get('http://localhost:5273/api/v1/auth/me')
    expect(r.status()).toBe(401)
    await other.close()
  })

  test('F01-H6 two browsers hold two different accounts', async ({ page, browser }) => {
    await uiLogin(page, acct('e1'))
    await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible()
    const other = await browser.newContext({ baseURL: 'http://localhost:5273' })
    const p2 = await other.newPage()
    await uiLogin(p2, acct('mgr'))
    await expect(p2.getByRole('navigation', { name: 'Main' })).toBeVisible()
    const who = async (p: typeof page) => (await p.request.get('http://localhost:5273/api/v1/auth/me')).json()
    expect((await who(page)).email).toBe(acct('e1'))
    expect((await who(p2)).email).toBe(acct('mgr'))
    await other.close()
  })

  test('F01-H4 sign out returns to /login and protects pages', async ({ page }) => {
    await uiLogin(page, acct('e1'))
    await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible()
    await page.getByRole('button', { name: /Elena Engineer/ }).click()
    await page.getByRole('button', { name: 'Sign out' }).click()
    await expect(page).toHaveURL(/\/login/)
    await page.goto('/my-tasks')
    await expect(page).toHaveURL(/\/login/)
  })

  test('F01-E1 unauthenticated deep link redirects to login then back', async ({ page }) => {
    await page.goto('/leave')
    await expect(page).toHaveURL(/\/login/)
    await page.getByRole('textbox', { name: 'Email' }).fill(acct('e1'))
    await page.getByRole('textbox', { name: 'Password' }).fill(PW)
    await page.getByRole('button', { name: 'Sign in' }).click()
    await expect(page).toHaveURL(/\/leave$/)
  })

  test('F01-E2 emoji / very long input in email does not crash', async ({ page }) => {
    const done = watchErrors(page)
    await uiLogin(page, '😀'.repeat(10) + 'a'.repeat(300) + '@x.com', PW)
    await expect(page.getByRole('alert').first()).toBeVisible()
    await expect(page).toHaveURL(/\/login/)
    done()
  })

  test('F01-E3 double click on Sign in sends one successful login', async ({ page }) => {
    await page.goto('/login')
    await page.getByRole('textbox', { name: 'Email' }).fill(acct('e2'))
    await page.getByRole('textbox', { name: 'Password' }).fill(PW)
    await page.getByRole('button', { name: 'Sign in' }).dblclick()
    await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible()
  })

  test('F01-E4 keyboard only: tab to fields, Enter submits', async ({ page }) => {
    await page.goto('/login')
    await page.getByRole('textbox', { name: 'Email' }).focus()
    await page.keyboard.type(acct('e2'))
    await page.keyboard.press('Tab')
    await page.keyboard.type(PW)
    await page.keyboard.press('Enter')
    await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible()
  })

  test('F01-E5 login page passes axe and has no horizontal scroll at phone width', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 })
    await page.goto('/login')
    await a11y(page, 'login')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  })

  test('F01-N1 wrong password shows an error and stays on /login', async ({ page }) => {
    await uiLogin(page, acct('e1'), 'Wrong-Pw0rd!')
    await expect(page.getByRole('alert').first()).toBeVisible()
    await expect(page).toHaveURL(/\/login/)
  })

  test('F01-N2 empty form does not log in', async ({ page }) => {
    await page.goto('/login')
    await page.getByRole('button', { name: 'Sign in' }).click()
    await expect(page).toHaveURL(/\/login/)
  })

  test('F01-N3 unknown user and wrong password give the same message', async ({ page }) => {
    await uiLogin(page, 'nobody@acme.com', 'Wrong-Pw0rd!')
    const a = await page.getByRole('alert').first().innerText()
    await uiLogin(page, acct('e1'), 'Wrong-Pw0rd!')
    const b = await page.getByRole('alert').first().innerText()
    expect(a).toBe(b)
  })

  test('F01-N4 five bad logins lock the account (429)', async () => {
    const email = 'lockme@acme.com'
    let last = 0
    for (let i = 0; i < 7; i++) last = (await api('POST', '/auth/login', undefined, { email, password: 'bad-pass-' + i })).status
    expect(last).toBe(429)
  })

  test('F01-N5 a platform password under production settings is verified for real', async () => {
    const r = await api('POST', '/auth/login', undefined, { email: PLATFORM.email, password: 'abc' })
    expect(r.status).toBe(401)
    const r2 = await api('POST', '/auth/login', undefined, { email: 'admin', password: 'abc' })
    expect(r2.status).toBe(401)
  })
})
