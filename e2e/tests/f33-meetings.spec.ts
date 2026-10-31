import { test, expect, type Browser } from '@playwright/test'
import { a11y, acct, api, loginAs, PW, token, watchErrors } from '../helpers'

test.describe.configure({ mode: 'serial' })
// real (fake-device) camera and microphone so two browsers can actually meet
test.use({ launchOptions: { args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'] }, permissions: ['camera', 'microphone'] })

const WEB = 'http://localhost:5273'
const ctxPage = async (browser: Browser, email: string) => {
  const c = await browser.newContext({ baseURL: WEB, permissions: ['camera', 'microphone'] })
  const p = await c.newPage()
  await loginAs(p, email)
  return p
}

test.describe('F33 private meetings and calls', () => {
  const ids: Record<string, { id: number; name: string }> = {}
  let room = ''

  test.beforeAll(async () => {
    const f = await token(acct('founder'))
    const dir = (await api('GET', '/employees/directory', f)).body.items
    for (const k of ['mgr', 'e1', 'e2', 'e3']) {
      const u = dir.find((x: any) => x.email === acct(k))
      ids[k] = { id: u.id, name: u.full_name }
    }
  })

  test('F33-M1 a meeting goes only to the people chosen, not to everyone', async ({ page, browser }) => {
    const done = watchErrors(page)
    await loginAs(page, acct('mgr'))
    await page.goto('/meetings')
    await a11y(page, '/meetings')
    await page.getByRole('button', { name: 'New meeting' }).click()
    const dlg = page.getByRole('dialog')
    await expect(dlg.getByText('Only you can join until you invite someone.')).toBeVisible()
    await dlg.getByLabel(/Title/).pressSequentially('Design review') // real keystrokes: focus must stay in the field
    await expect(dlg.getByLabel(/Title/)).toHaveValue('Design review')
    await dlg.getByLabel('Date & time').fill('2031-05-04T10:00')
    await dlg.getByRole('searchbox', { name: 'Search people' }).fill(ids.e1.name.split(' ')[0])
    await dlg.getByText(ids.e1.name, { exact: true }).click()
    await expect(dlg.getByText('1 people, 0 teams, 0 groups selected')).toBeVisible()
    await a11y(page, 'new meeting dialog')
    await dlg.getByRole('button', { name: 'Schedule' }).click()
    await expect(dlg).toBeHidden()
    const row = page.getByRole('row', { name: /Design review/ })
    await expect(row).toContainText(ids.e1.name)
    room = (await api('GET', '/meetings', await token(acct('mgr')))).body.items.find((m: any) => m.title === 'Design review').room_id

    const e1 = await ctxPage(browser, acct('e1'))
    await e1.goto('/meetings')
    await expect(e1.getByRole('row', { name: /Design review/ })).toContainText(ids.mgr.name)
    const e2 = await ctxPage(browser, acct('e2'))
    await e2.goto('/meetings')
    await expect(e2.getByRole('heading', { name: 'Meetings' })).toBeVisible()
    await expect(e2.getByRole('row', { name: /Design review/ })).toHaveCount(0)
    expect((await api('GET', `/meetings/${room}`, await token(acct('e2')))).status).toBe(404)
    expect((await api('GET', `/meetings/${room}`, await token(acct('hr')))).status).toBe(404)
    done()
  })

  test('F33-M2 a chat group can be invited as a whole, but only by its members', async ({ page }) => {
    const done = watchErrors(page)
    const m = await token(acct('mgr'))
    const g = await api('POST', '/chat/conversations', m, { name: 'Launch crew', member_ids: [ids.e1.id, ids.e2.id] })
    expect(g.status).toBe(201)
    expect((await api('POST', '/meetings', await token(acct('e3')), { title: 'Not my group', group_ids: [g.body.id] })).status).toBe(404)
    await loginAs(page, acct('mgr'))
    await page.goto('/meetings')
    await page.getByRole('button', { name: 'New meeting' }).click()
    const dlg = page.getByRole('dialog')
    await dlg.getByLabel(/Title/).fill('Launch sync')
    await dlg.getByText('Launch crew').click()
    await dlg.getByRole('button', { name: 'Schedule' }).or(dlg.getByRole('button', { name: 'Start now' })).click()
    await page.waitForURL(/\/meetings\/[\w-]+$/)
    await expect(page.getByRole('region', { name: 'Invited people' })).toContainText(ids.e1.name)
    await expect(page.getByRole('region', { name: 'Invited people' })).toContainText(ids.e2.name)
    await expect(page.getByRole('region', { name: 'Invited people' })).not.toContainText(ids.e3.name)
    done()
  })

  test('F33-M3 call one person: two browsers meet in a private room and nobody else can enter', async ({ page, browser }) => {
    const done = watchErrors(page)
    await loginAs(page, acct('mgr'))
    await page.goto('/meetings')
    await page.getByRole('button', { name: 'Call someone' }).click()
    const dlg = page.getByRole('dialog')
    await expect(dlg.getByRole('button', { name: 'Call' })).toBeDisabled()
    await dlg.getByText(ids.e2.name, { exact: true }).click()
    await dlg.getByRole('button', { name: 'Call' }).click()
    await page.waitForURL(/\/meetings\/[\w-]+$/)
    const callRoom = page.url().split('/').pop()!
    await expect(page.getByText('Call between')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Invite more' })).toHaveCount(0)

    const e2 = await ctxPage(browser, acct('e2'))
    await e2.goto('/notifications')
    await expect(e2.getByText('Incoming call')).toBeVisible()
    await e2.goto(`/meetings/${callRoom}`)
    await expect(e2.getByText(ids.mgr.name, { exact: false }).first()).toBeVisible()
    // both sides see the other's tile once the peer connection is up
    await expect(page.locator('figcaption', { hasText: ids.e2.name })).toBeVisible({ timeout: 20_000 })
    await expect(e2.locator('figcaption', { hasText: ids.mgr.name })).toBeVisible({ timeout: 20_000 })
    await expect.poll(() => page.evaluate(() => [...document.querySelectorAll('video')].filter((v) => (v as HTMLVideoElement).videoWidth > 0).length), { timeout: 20_000 }).toBeGreaterThanOrEqual(2)

    const e3 = await ctxPage(browser, acct('e3'))
    await e3.goto(`/meetings/${callRoom}`)
    await expect(e3.getByRole('alert')).toContainText(/not found|not been invited/i)
    expect((await api('POST', '/meetings/call', await token(acct('e3')), { user_id: ids.mgr.id })).status).toBe(201) // e3 can call their own manager, a separate room
    done()
  })

  test('F33-M4 the host removes a guest who is in the room; guests cannot manage the list', async ({ page, browser }) => {
    const done = watchErrors(page)
    const m = await token(acct('mgr'))
    const made = await api('POST', '/meetings', m, { title: 'Standup', invitee_ids: [ids.e1.id, ids.e2.id] })
    expect(made.status).toBe(201)
    const r = made.body.room_id
    await loginAs(page, acct('mgr'))
    await page.goto(`/meetings/${r}`)
    const e1 = await ctxPage(browser, acct('e1'))
    await e1.goto(`/meetings/${r}`)
    await expect(e1.getByRole('region', { name: 'Invited people' })).toContainText(ids.e2.name)
    await expect(e1.getByRole('button', { name: /Invite more|Remove|End meeting/ })).toHaveCount(0)
    await expect(page.locator('figcaption', { hasText: ids.e1.name })).toBeVisible({ timeout: 20_000 })

    await page.getByRole('button', { name: `Remove ${ids.e1.name}` }).click()
    await expect(e1.getByRole('alert')).toContainText('You were removed from this meeting')
    await expect(page.getByRole('region', { name: 'Invited people' })).not.toContainText(ids.e1.name)
    expect((await api('GET', `/meetings/${r}`, await token(acct('e1')))).status).toBe(404)

    await page.getByRole('button', { name: 'Invite more' }).click()
    const dlg = page.getByRole('dialog')
    await expect(dlg.getByText(ids.e2.name, { exact: true })).toHaveCount(0) // already invited
    await dlg.getByText(ids.e3.name, { exact: true }).click()
    await dlg.getByRole('button', { name: 'Invite' }).click()
    await expect(dlg).toBeHidden()
    await expect(page.getByRole('region', { name: 'Invited people' })).toContainText(ids.e3.name)
    expect((await api('GET', `/meetings/${r}`, await token(acct('e3')))).status).toBe(200)
    done()
  })

  test('F33-M5 employees cannot reach people the hierarchy forbids', async () => {
    const e1 = await token(acct('e1'))
    const founder = (await api('GET', '/auth/me', await token(acct('founder')))).body.id
    const r = await api('POST', '/meetings', e1, { title: 'Straight to the top', invitee_ids: [founder] })
    expect(r.status).toBe(403)
    expect((await api('POST', '/meetings/call', e1, { user_id: founder })).status).toBe(403)
    expect(PW).toBeTruthy()
  })
})
