import { test, expect, type Browser, type Page } from '@playwright/test'
import { acct, api, loginAs, token, watchErrors } from '../helpers'

test.describe.configure({ mode: 'serial' })
test.use({ launchOptions: { args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'] }, permissions: ['camera', 'microphone'] })

const WEB = 'http://localhost:5273'
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==', 'base64')
function wav(seconds = 1.2) {
  const n = Math.floor(8000 * seconds), h = Buffer.alloc(44)
  h.write('RIFF', 0); h.writeUInt32LE(36 + n, 4); h.write('WAVEfmt ', 8); h.writeUInt32LE(16, 16); h.writeUInt16LE(1, 20); h.writeUInt16LE(1, 22)
  h.writeUInt32LE(8000, 24); h.writeUInt32LE(8000, 28); h.writeUInt16LE(1, 32); h.writeUInt16LE(8, 34); h.write('data', 36); h.writeUInt32LE(n, 40)
  return Buffer.concat([h, Buffer.alloc(n)])
}
// records every camera/microphone track and every signaling socket the page creates, so the tests can check clean-up and drop a socket
const SPY = () => {
  const w = window as any
  w.__tracks = []; w.__sockets = []
  const md = navigator.mediaDevices
  const g = md.getUserMedia.bind(md)
  md.getUserMedia = async (c: MediaStreamConstraints) => { const s = await g(c); s.getTracks().forEach((t) => w.__tracks.push(t)); return s }
  const WS = window.WebSocket
  w.WebSocket = class extends WS { constructor(u: string | URL, p?: string | string[]) { super(u, p); w.__sockets.push(this) } }
}
const opened: Page[] = []
async function open(browser: Browser, email: string, spy = false): Promise<Page> {
  const c = await browser.newContext({ baseURL: WEB, permissions: ['camera', 'microphone'] })
  if (spy) await c.addInitScript(SPY)
  const p = await c.newPage()
  await loginAs(p, email)
  opened.push(p)
  return p
}
const box = (p: Page) => p.getByRole('textbox', { name: 'Message', exact: true })
const bubble = (p: Page, text: string | RegExp) => p.getByRole('log').locator('[data-mid]', { hasText: text }).first()

test.describe('F39 chat: replies, edits, receipts, typing, presence, files, players and calls', () => {
  let mgrName = '', e1Name = '', mgrId = 0, e1Id = 0

  test.afterEach(async () => { for (const p of opened.splice(0)) await p.context().close().catch(() => {}) })   // a browser left open would keep reading and answering

  test.beforeAll(async () => {
    const f = await token(acct('founder'))
    const dir = (await api('GET', '/employees/directory', f)).body.items
    const mgr = dir.find((u: any) => u.email === acct('mgr')), e1 = dir.find((u: any) => u.email === acct('e1'))
    mgrName = mgr.full_name; e1Name = e1.full_name; mgrId = mgr.id; e1Id = e1.id
    expect((await api('POST', '/chat/conversations', await token(acct('e1')), { user_id: mgrId })).status).toBe(201)
  })
  const toChat = async (p: Page, who: string) => { await p.goto('/chat'); await p.getByRole('button', { name: new RegExp(who) }).first().click(); await expect(box(p)).toBeVisible() }

  test('F39-M1 reply, edit and delete are seen by the other person immediately', async ({ page, browser }) => {
    const done = watchErrors(page)
    await loginAs(page, acct('e1'))
    const m = await open(browser, acct('mgr'))
    await toChat(page, mgrName); await toChat(m, e1Name)
    await box(m).fill('Can you send the numbers?'); await m.keyboard.press('Enter')
    await expect(bubble(page, 'Can you send the numbers?')).toBeVisible()                                // arrives live

    await bubble(page, 'Can you send the numbers?').getByRole('button', { name: 'Reply' }).click()
    await expect(page.getByText(`Replying to ${mgrName}`)).toBeVisible()
    await box(page).fill('Sending them now'); await page.keyboard.press('Enter')
    await expect(bubble(m, 'Sending them now').getByRole('button', { name: new RegExp(`Replying to ${mgrName}: Can you send`) })).toBeVisible()

    await bubble(page, 'Sending them now').getByRole('button', { name: 'Edit message' }).click()
    await expect(page.getByText('Editing message')).toBeVisible()
    await box(page).fill('Sending them in five minutes'); await page.getByRole('button', { name: 'Save' }).click()
    await expect(bubble(m, 'Sending them in five minutes')).toContainText('edited')

    await bubble(page, 'Sending them in five').getByRole('button', { name: 'Delete message' }).click()
    await bubble(page, 'Sending them in five').getByRole('button', { name: 'Yes, delete' }).click()
    await expect(m.getByText('This message was deleted')).toBeVisible()
    await expect(m.getByText('Sending them in five minutes')).toHaveCount(0)
    await expect(page.getByText('You deleted this message')).toBeVisible()
    // a deleted photo is gone from the server too
    const e1 = await token(acct('e1'))
    const conv = (await api('GET', '/chat/conversations', e1)).body.items.find((c: any) => c.members.some((x: any) => x.id === mgrId))
    const img = await (async () => { const r = await fetch('http://127.0.0.1:8100/api/v1/chat/conversations/' + conv.id + '/attachments', { method: 'POST', headers: { Authorization: `Bearer ${e1}` }, body: (() => { const f = new FormData(); f.append('file', new Blob([PNG], { type: 'image/png' }), 'gone.png'); return f })() }); return r.json() })()
    expect((await fetch('http://127.0.0.1:8100/api/v1' + img.file.url, { headers: { Authorization: `Bearer ${e1}` } })).status).toBe(200)
    expect((await api('DELETE', `/chat/messages/${img.id}`, e1)).status).toBe(200)
    expect((await fetch('http://127.0.0.1:8100/api/v1' + img.file.url, { headers: { Authorization: `Bearer ${e1}` } })).status).toBe(404)
    done()
  })

  test('F39-M2 sent, delivered and read ticks follow the other person, live', async ({ page, browser }) => {
    await loginAs(page, acct('e1'))
    await toChat(page, mgrName)
    const m = await open(browser, acct('mgr'))              // signed in, but looking at another page
    await m.goto('/my-tasks')
    await box(page).fill('Receipt check'); await page.keyboard.press('Enter')
    await expect(bubble(page, 'Receipt check').getByRole('img', { name: 'Delivered' })).toBeVisible()   // their browser received it
    await toChat(m, e1Name)                                                                               // opening the chat reads it
    await expect(bubble(page, 'Receipt check').getByRole('img', { name: 'Read' })).toBeVisible()
  })

  test('F39-M3 typing and online status are shown to the other person and clear again', async ({ page, browser }) => {
    await loginAs(page, acct('e1'))
    await toChat(page, mgrName)
    const m = await open(browser, acct('mgr'))
    await toChat(m, e1Name)
    await expect(page.getByRole('status').filter({ hasText: 'Online' }).first()).toBeVisible({ timeout: 15_000 })
    await box(m).pressSequentially('thinking about the answer', { delay: 60 })
    await expect(page.getByRole('status').filter({ hasText: 'typing…' }).first()).toBeVisible()
    await expect(page.getByRole('status').filter({ hasText: 'typing…' })).toHaveCount(0, { timeout: 10_000 })   // it expires on its own
    await m.context().close()
    await expect(page.getByRole('status').filter({ hasText: /^Last seen/ }).first()).toBeVisible({ timeout: 15_000 })
  })

  test('F39-M4 pin, search the list, and search inside the conversation', async ({ page }) => {
    await loginAs(page, acct('e1'))
    await toChat(page, mgrName)
    await page.getByRole('button', { name: 'More options' }).click()
    await page.getByRole('menuitem', { name: 'Pin this chat' }).click()
    await expect(page.getByRole('region', { name: 'Pinned conversations' }).getByText(mgrName)).toBeVisible()
    await page.reload()
    await expect(page.getByRole('region', { name: 'Pinned conversations' }).getByText(mgrName)).toBeVisible()          // it is saved, not just shown
    await page.getByLabel('Search conversations').fill('zzzz-nothing')
    await expect(page.getByText(/No chats match/)).toBeVisible()
    await page.getByLabel('Search conversations').fill(mgrName.split(' ')[0])
    await expect(page.getByRole('region', { name: 'Pinned conversations' })).toBeVisible()
    await page.getByLabel('Search conversations').fill('')
    await page.getByRole('button', { name: new RegExp(mgrName) }).first().click()
    await page.getByRole('button', { name: 'Search in conversation' }).click()
    await page.getByLabel('Search messages').fill('Receipt check')
    await expect(page.getByRole('list', { name: 'Search results' }).getByText(/Receipt check/)).toBeVisible()
    await page.getByRole('list', { name: 'Search results' }).getByRole('button').first().click()
    await expect(page.locator('[data-mid]', { hasText: 'Receipt check' }).first()).toBeInViewport()
    await page.getByRole('button', { name: 'More options' }).click()
    await page.getByRole('menuitem', { name: 'Unpin this chat' }).click()
    await expect(page.getByRole('region', { name: 'Pinned conversations' })).toHaveCount(0)
  })

  test('F39-M5 emoji search and recents, sticker favourites, and the like button', async ({ page, browser }) => {
    await loginAs(page, acct('e1'))
    await toChat(page, mgrName)
    await page.getByRole('button', { name: 'Emoji' }).click()
    await page.getByLabel('Search emoji').fill('coffee')
    await page.getByRole('group', { name: 'Emoji' }).getByLabel('Search results').getByRole('button', { name: '☕' }).click()
    await expect(box(page)).toHaveValue('☕')
    await page.keyboard.press('Enter')
    await page.keyboard.press('Escape')                                                                           // the picker stays open after a pick; close it, then open it again
    await page.getByRole('button', { name: 'Emoji' }).click()
    await expect(page.getByRole('region', { name: 'Recently used' })).toContainText('☕')
    await expect(page.getByRole('region', { name: 'Frequently used' })).toContainText('☕')
    await page.keyboard.press('Escape')

    await page.getByRole('button', { name: 'Stickers' }).click()
    await page.getByRole('tab', { name: 'Work' }).click()
    await page.getByRole('button', { name: /Add Done to favourites/ }).click({ force: true })
    await page.reload(); await page.getByRole('button', { name: new RegExp(mgrName) }).first().click()
    await page.getByRole('button', { name: 'Stickers' }).click()
    await page.getByRole('tab', { name: 'Favourites' }).click()
    await expect(page.getByRole('button', { name: 'Send sticker: Done' })).toBeVisible()                        // favourites survive a reload
    await page.keyboard.press('Escape')

    const m = await open(browser, acct('mgr')); await toChat(m, e1Name)
    await page.getByRole('button', { name: 'Send a like' }).click()
    await expect(m.getByRole('log').getByRole('img', { name: 'Sticker: Thumbs up' }).last()).toBeVisible()
  })

  test('F39-F1 drag several files in, cancel an upload, then send; photos open in a viewer, audio plays one at a time', async ({ page, browser }) => {
    const done = watchErrors(page)
    await loginAs(page, acct('e1'))
    await toChat(page, mgrName)
    const files = [{ name: 'one.png', type: 'image/png', data: PNG }, { name: 'two.png', type: 'image/png', data: PNG }, { name: 'ring1.wav', type: 'audio/wav', data: wav() }, { name: 'ring2.wav', type: 'audio/wav', data: wav() }]
    await page.getByRole('log').evaluate((el, list) => {
      const dt = new DataTransfer()
      list.forEach((f: any) => dt.items.add(new File([new Uint8Array(f.data)], f.name, { type: f.type })))
      const target = el.parentElement!
      target.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: dt }))
      target.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt }))
    }, files.map((f) => ({ ...f, data: [...f.data] })))
    const queue = page.getByRole('list', { name: 'Attachments to send' })
    await expect(queue.getByRole('status')).toHaveCount(4)
    await expect(queue.locator('img').first()).toBeVisible()                                                    // thumbnails before sending

    // cancel: the request is held back, so nothing reaches the server
    await page.route('**/chat/conversations/*/attachments', () => { /* never answered */ })
    await page.getByRole('button', { name: 'Send', exact: true }).click()
    await expect(page.getByRole('status', { name: /one\.png, uploading/ })).toBeVisible()
    await page.getByRole('status', { name: /one\.png, uploading/ }).getByRole('button', { name: 'Cancel' }).click()
    await expect(page.getByRole('status', { name: /one\.png, ready/ })).toBeVisible()
    await page.unroute('**/chat/conversations/*/attachments')
    const e1 = await token(acct('e1'))
    const conv = (await api('GET', '/chat/conversations', e1)).body.items.find((c: any) => c.members.some((x: any) => x.id === mgrId))
    expect((await api('GET', `/chat/conversations/${conv.id}/messages?limit=100`, e1)).body.items.some((x: any) => x.file?.name === 'one.png')).toBe(false)

    await page.getByRole('button', { name: 'Send', exact: true }).click()                                          // now for real: all four in order
    await expect(page.getByRole('list', { name: 'Attachments to send' })).toHaveCount(0, { timeout: 20_000 })

    const m = await open(browser, acct('mgr')); await toChat(m, e1Name)
    const log = m.getByRole('log')
    await log.getByRole('button', { name: 'Open photo two.png' }).click()
    const viewer = m.getByRole('dialog', { name: /Photo \d+ of \d+/ })
    await expect(viewer).toBeVisible()
    const count = Number(((await viewer.getAttribute('aria-label')) || '').match(/of (\d+)/)![1])
    await m.keyboard.press('ArrowLeft')
    await expect(viewer).toHaveAttribute('aria-label', new RegExp(`Photo \\d+ of ${count}`))
    const [dl] = await Promise.all([m.waitForEvent('download'), viewer.getByRole('button', { name: 'Download' }).click()])
    expect(dl.suggestedFilename()).toMatch(/\.png$/)
    await m.keyboard.press('Escape')
    await expect(viewer).toHaveCount(0)

    const p1 = log.getByRole('group', { name: 'Audio ring1.wav' }), p2 = log.getByRole('group', { name: 'Audio ring2.wav' })
    await expect(p1.getByText(/0:0\d \/ 0:0\d/)).toBeVisible()                                                  // real duration from the file
    await p1.getByRole('button', { name: 'Play', exact: true }).click()
    await expect(p1.getByRole('button', { name: 'Pause' })).toBeVisible()
    await p2.getByRole('button', { name: 'Play', exact: true }).click()
    await expect(p2.getByRole('button', { name: 'Pause' })).toBeVisible()
    await expect(p1.getByRole('button', { name: 'Play', exact: true })).toBeVisible()                           // the first one stopped
    await p2.getByRole('button', { name: /Playback speed/ }).click()
    await expect(p2.getByRole('button', { name: 'Playback speed 1.5x' })).toBeVisible()
    await p2.getByLabel('Seek').fill('0.5')
    await expect(p2.getByText(/^0:00 \//)).toBeVisible()
    done()
  })

  test('F39-M6 long conversations load a page at a time', async ({ page }) => {
    const e1 = await token(acct('e1'))
    const conv = (await api('GET', '/chat/conversations', e1)).body.items.find((c: any) => c.members.some((x: any) => x.id === mgrId))
    for (let i = 1; i <= 70; i++) await api('POST', `/chat/conversations/${conv.id}/messages`, e1, { body: `bulk line ${i}` })
    await loginAs(page, acct('e1'))
    await toChat(page, mgrName)
    await expect(bubble(page, 'bulk line 70')).toBeVisible()
    await expect(page.getByText('bulk line 40', { exact: true })).toHaveCount(0)                                // only the newest page is loaded
    await page.getByRole('button', { name: 'Load earlier messages' }).click()
    await expect(page.getByText('bulk line 45', { exact: true })).toBeVisible()
    await expect(bubble(page, 'bulk line 70')).toBeAttached()                                                   // nothing newer was lost
  })

  test('F39-C1 an incoming call rings on any page; accepting connects both sides, with real states and a running timer', async ({ page, browser }) => {
    const done = watchErrors(page)
    const caller = await open(browser, acct('e1'), true)
    const callee = await open(browser, acct('mgr'), true)
    const bystander = await open(browser, acct('e2'))
    await callee.goto('/my-tasks')
    await toChat(caller, mgrName)
    await caller.getByRole('button', { name: `Voice call ${mgrName}` }).click()
    await caller.waitForURL(/\/meetings\/[\w-]+\?audio=1$/)
    await expect(caller.getByRole('status').filter({ hasText: `Calling ${mgrName}…` })).toBeVisible()          // calling, not connected
    const ring = callee.getByRole('alertdialog')
    await expect(ring).toContainText(e1Name); await expect(ring).toContainText('Incoming voice call…')
    await expect(bystander.getByRole('alertdialog')).toHaveCount(0)                                              // nobody else is rung
    await expect(caller.getByRole('status').filter({ hasText: 'Connected' })).toHaveCount(0)

    await ring.getByRole('button', { name: 'Accept' }).click()
    await callee.waitForURL(/\/meetings\/[\w-]+\?audio=1$/)
    await expect(caller.getByRole('status').filter({ hasText: 'Connected' })).toBeVisible({ timeout: 25_000 })
    await expect(callee.getByRole('status').filter({ hasText: 'Connected' })).toBeVisible({ timeout: 25_000 })
    await expect(caller.getByLabel('Call duration')).toHaveText(/0:0[1-9]|0:[1-5]\d/, { timeout: 10_000 })
    await expect(caller.getByRole('button', { name: 'No camera' })).toBeDisabled()                             // a voice call has no camera or screen share
    await expect(caller.getByRole('button', { name: 'Share screen' })).toBeDisabled()

    await callee.getByRole('button', { name: 'Mute' }).click()                                                   // mute is seen by the other side
    await expect(caller.locator('figcaption', { hasText: mgrName }).getByText('Muted')).toBeVisible()
    await callee.getByRole('button', { name: 'Unmute' }).click()
    await expect(caller.locator('figcaption', { hasText: mgrName }).getByText('Muted')).toHaveCount(0)
    await expect(caller.getByText(/connection/i).filter({ hasText: /Good|Fair|Poor/ })).toBeVisible({ timeout: 15_000 })

    // the real media is flowing: the remote audio element has an active, unmuted track
    expect(await caller.evaluate(() => [...document.querySelectorAll('video')].some((v) => ((v as HTMLVideoElement).srcObject as MediaStream | null)?.getAudioTracks().some((t) => t.readyState === 'live' && !t.muted)))).toBe(true)

    // hanging up releases every camera and microphone track on both sides
    await callee.getByRole('button', { name: 'Leave' }).click()
    await expect(caller.getByRole('heading', { name: 'Call ended' })).toBeVisible({ timeout: 15_000 })
    await caller.getByRole('button', { name: 'Back to chat' }).click()
    for (const p of [callee, caller]) {
      await p.waitForFunction(() => (window as any).__tracks.length > 0 && (window as any).__tracks.every((t: MediaStreamTrack) => t.readyState === 'ended'))
    }
    const hist = await api('GET', '/meetings/calls/history', await token(acct('e1')))
    expect(hist.body.items[0]).toMatchObject({ direction: 'outgoing', outcome: 'answered', video: false })
    expect(hist.body.items[0].duration_s).toBeGreaterThanOrEqual(1)
    done()
  })

  test('F39-C2 declining ends the call for the caller with a clear message and is recorded', async ({ browser }) => {
    const caller = await open(browser, acct('e1'), true)
    const callee = await open(browser, acct('mgr'))
    await callee.goto('/my-tasks')
    await toChat(caller, mgrName)
    await caller.getByRole('button', { name: `Video call ${mgrName}` }).click()
    await caller.waitForURL(/\/meetings\/[\w-]+$/)
    await callee.getByRole('alertdialog').getByRole('button', { name: 'Decline' }).click()
    await expect(callee.getByRole('alertdialog')).toHaveCount(0)
    await expect(caller.getByRole('heading', { name: 'Call declined' })).toBeVisible()
    await caller.getByRole('button', { name: 'Back to chat' }).click()
    await caller.getByRole('button', { name: 'More options' }).click()
    await caller.getByRole('menuitem', { name: 'Call history' }).click()
    await expect(caller.getByRole('list', { name: 'Calls' }).getByText(/Outgoing · No answer|Outgoing · Declined/).first()).toBeVisible()
    expect((await api('GET', '/meetings/calls/history', await token(acct('mgr')))).body.items[0]).toMatchObject({ direction: 'incoming', outcome: 'declined' })
    await expect.poll(async () => caller.evaluate(() => (window as any).__tracks?.every((t: MediaStreamTrack) => t.readyState === 'ended') ?? true)).toBe(true)  // the camera stopped when the call ended
  })

  test('F39-C3 hanging up before an answer stops the ringing and leaves a missed call', async ({ browser }) => {
    const caller = await open(browser, acct('e1'))
    const callee = await open(browser, acct('mgr'))
    await callee.goto('/my-tasks')
    await toChat(caller, mgrName)
    await caller.getByRole('button', { name: `Voice call ${mgrName}` }).click()
    await caller.waitForURL(/\/meetings\/[\w-]+\?audio=1$/)
    await expect(callee.getByRole('alertdialog')).toBeVisible()
    await caller.getByRole('button', { name: 'End call' }).click()
    await expect(callee.getByRole('alertdialog')).toHaveCount(0)                                                 // the ring stopped on their screen
    const mgrTok = await token(acct('mgr'))
    expect((await api('GET', '/notifications', mgrTok)).body.items.some((n: any) => n.title === 'Missed call' && n.body.includes(e1Name))).toBe(true)
    expect((await api('GET', '/meetings/calls/history', mgrTok)).body.items[0]).toMatchObject({ direction: 'incoming', outcome: 'missed' })
  })

  test('F39-C4 a video call connects, shows both streams without covering the other person, and recovers when signaling drops', async ({ browser }) => {
    const caller = await open(browser, acct('e1'), true)
    const callee = await open(browser, acct('mgr'), true)
    await toChat(caller, mgrName)
    await caller.getByRole('button', { name: `Video call ${mgrName}` }).click()
    await caller.waitForURL(/\/meetings\/[\w-]+$/)
    await callee.getByRole('alertdialog').getByRole('button', { name: 'Accept' }).click()
    await expect(caller.getByRole('status').filter({ hasText: 'Connected' })).toBeVisible({ timeout: 25_000 })
    // remote video really decodes frames
    await expect.poll(() => caller.evaluate(() => [...document.querySelectorAll('video')].filter((v) => (v as HTMLVideoElement).videoWidth > 0).length), { timeout: 20_000 }).toBeGreaterThanOrEqual(2)
    // the local preview sits beside the remote video, not on top of it
    const boxes = await caller.locator('figure').evaluateAll((els) => els.map((e) => { const r = e.getBoundingClientRect(); return { l: r.left, r: r.right, t: r.top, b: r.bottom } }))
    const overlap = (a: any, b: any) => a.l < b.r && b.l < a.r && a.t < b.b && b.t < a.b
    expect(boxes.length).toBe(2)
    expect(overlap(boxes[0], boxes[1])).toBe(false)
    await expect(caller.getByRole('button', { name: 'Full screen' })).toBeVisible()
    await caller.getByRole('button', { name: 'Camera off' }).click()
    await expect(caller.getByRole('button', { name: 'Camera on' })).toBeVisible()
    await caller.getByRole('button', { name: 'Camera on' }).click()

    // the signaling socket is cut on the caller's side: the page says so, then the call comes back by itself
    await caller.evaluate(() => (window as any).__sockets.filter((s: WebSocket) => s.url.includes('/meetings/ws/')).forEach((s: WebSocket) => s.close()))
    await expect(caller.getByRole('status').filter({ hasText: /Reconnecting|Connecting|Waiting/ })).toBeVisible({ timeout: 10_000 })
    await expect(caller.getByRole('status').filter({ hasText: 'Connected' })).toBeVisible({ timeout: 30_000 })
    await expect(callee.getByRole('status').filter({ hasText: 'Connected' })).toBeVisible({ timeout: 30_000 })
    await expect.poll(() => caller.evaluate(() => [...document.querySelectorAll('video')].filter((v) => (v as HTMLVideoElement).videoWidth > 0).length), { timeout: 20_000 }).toBeGreaterThanOrEqual(2)

    await caller.getByRole('button', { name: 'End call' }).click()
    await caller.waitForURL(/\/chat$/)
    await caller.waitForFunction(() => (window as any).__tracks.every((t: MediaStreamTrack) => t.readyState === 'ended'))
  })

  test('F39-C5 the voice button always means a voice call: no camera for either person, even through a plain link', async ({ browser }) => {
    const caller = await open(browser, acct('e1'), true)
    const callee = await open(browser, acct('mgr'), true)
    await callee.goto('/my-tasks')
    await toChat(caller, mgrName)
    await caller.getByRole('button', { name: `Voice call ${mgrName}` }).click()
    await caller.waitForURL(/\/meetings\/[\w-]+\?audio=1$/)
    await expect(caller.getByRole('heading', { name: `Voice call with ${mgrName}` })).toBeVisible()
    await expect(callee.getByRole('alertdialog')).toContainText('Incoming voice call…')
    const room = new URL(caller.url()).pathname.split('/').pop()!
    await callee.goto(`/meetings/${room}`)                                                                    // e.g. from the notification, with no ?audio=1 in the link
    await expect(callee.getByRole('button', { name: 'No camera' })).toBeDisabled()
    await expect(caller.getByRole('status').filter({ hasText: 'Connected' })).toBeVisible({ timeout: 25_000 })
    for (const p of [caller, callee]) {
      expect(await p.evaluate(() => (window as any).__tracks.filter((t: MediaStreamTrack) => t.kind === 'video').length)).toBe(0)   // no camera was ever opened
    }
    await caller.getByRole('button', { name: 'End call' }).click()
  })

  test('F39-E1 editing: the original is shown, unchanged saves are not edits, captions can be changed or removed, and the other person sees it live', async ({ page, browser }) => {
    const done = watchErrors(page)
    await loginAs(page, acct('e1'))
    const m = await open(browser, acct('mgr'))
    await toChat(page, mgrName); await toChat(m, e1Name)
    await box(page).fill('Lunch at noon'); await page.keyboard.press('Enter')
    await expect(bubble(m, 'Lunch at noon')).toBeVisible()

    // the message being edited is marked, and its original words are shown above the box
    await bubble(page, 'Lunch at noon').getByRole('button', { name: 'Edit message' }).click()
    await expect(box(page)).toHaveValue('Lunch at noon')
    await expect(page.getByRole('status').filter({ hasText: 'Editing message' })).toContainText('Lunch at noon')
    await expect(page.getByRole('button', { name: 'Attach a file' })).toBeDisabled()
    // saving the same words changes nothing: no "edited" label for anyone
    await page.getByRole('button', { name: 'Save' }).click()
    await expect(page.getByText('Editing message')).toHaveCount(0)
    await expect(bubble(page, 'Lunch at noon')).not.toContainText('edited')
    await expect(bubble(m, 'Lunch at noon')).not.toContainText('edited')

    // a real change is seen live, marked as edited, and Escape cancels an edit without changing anything
    await bubble(page, 'Lunch at noon').getByRole('button', { name: 'Edit message' }).click()
    await box(page).fill('Lunch at one'); await page.keyboard.press('Enter')
    await expect(bubble(m, 'Lunch at one')).toContainText('edited')
    await bubble(page, 'Lunch at one').getByRole('button', { name: 'Edit message' }).click()
    await box(page).fill('never saved'); await page.keyboard.press('Escape')
    await expect(box(page)).toHaveValue('')
    await expect(bubble(page, 'Lunch at one')).toBeVisible()
    await expect(page.getByText('never saved')).toHaveCount(0)

    // a photo's caption can be changed and then removed; the photo stays
    const e1 = await token(acct('e1'))
    const conv = (await api('GET', '/chat/conversations', e1)).body.items.find((c: any) => c.members.some((x: any) => x.id === mgrId))
    const fd = new FormData(); fd.append('file', new Blob([PNG], { type: 'image/png' }), 'edit-me.png'); fd.append('caption', 'first caption')
    await fetch(`http://127.0.0.1:8100/api/v1/chat/conversations/${conv.id}/attachments`, { method: 'POST', headers: { Authorization: `Bearer ${e1}` }, body: fd })
    await expect(bubble(page, 'first caption')).toBeVisible()
    await bubble(page, 'first caption').getByRole('button', { name: 'Edit message' }).click()
    await expect(page.getByRole('textbox', { name: 'Message', exact: true })).toHaveAttribute('placeholder', 'Edit the caption')
    await box(page).fill('better caption'); await page.getByRole('button', { name: 'Save' }).click()
    await expect(bubble(m, 'better caption')).toContainText('edited')
    await bubble(page, 'better caption').getByRole('button', { name: 'Edit message' }).click()
    await box(page).fill(''); await page.getByRole('button', { name: 'Save' }).click()
    await expect(page.getByText('better caption')).toHaveCount(0)
    await expect(page.getByRole('log').getByRole('button', { name: 'Open photo edit-me.png' })).toBeVisible()
    await expect(m.getByText('better caption')).toHaveCount(0)
    done()
  })

  test('F39-S1 other people cannot join a call or see a conversation\'s files', async ({ browser }) => {
    const e1 = await token(acct('e1')), e3 = await token(acct('e3')), mgr = await token(acct('mgr'))
    const call = await api('POST', '/meetings/call', e1, { user_id: mgrId, video: false })
    const stranger = await open(browser, acct('e3'))
    await stranger.goto(`/meetings/${call.body.room_id}`)
    await expect(stranger.getByRole('alert')).toContainText(/not found|not been invited/i)
    expect((await api('POST', `/meetings/${call.body.room_id}/decline`, e3)).status).toBe(404)
    expect((await api('POST', `/meetings/${call.body.room_id}/end`, e3)).status).toBe(404)
    await api('POST', `/meetings/${call.body.room_id}/end`, e1)
    const conv = (await api('GET', '/chat/conversations', mgr)).body.items.find((c: any) => c.members.some((x: any) => x.id === e1Id))
    expect((await api('GET', `/chat/conversations/${conv.id}/messages`, e3)).status).toBe(404)
    expect((await api('PATCH', '/chat/messages/1', e3, { body: 'x' })).status).toBeGreaterThanOrEqual(403)
  })
})
