import { test, expect, type Browser } from '@playwright/test'
import { a11y, acct, api, loginAs, token, watchErrors } from '../helpers'

test.describe.configure({ mode: 'serial' })
// a fake microphone and camera, so voice recording and calls really run
test.use({ launchOptions: { args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'] }, permissions: ['camera', 'microphone'] })

const WEB = 'http://localhost:5273'
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==', 'base64')
const PDF = Buffer.from('%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF')
function wav(seconds = 0.3) {                                   // a valid, silent 8 kHz mono WAV
  const n = Math.floor(8000 * seconds), data = Buffer.alloc(n)
  const h = Buffer.alloc(44)
  h.write('RIFF', 0); h.writeUInt32LE(36 + n, 4); h.write('WAVEfmt ', 8); h.writeUInt32LE(16, 16); h.writeUInt16LE(1, 20); h.writeUInt16LE(1, 22)
  h.writeUInt32LE(8000, 24); h.writeUInt32LE(8000, 28); h.writeUInt16LE(1, 32); h.writeUInt16LE(8, 34); h.write('data', 36); h.writeUInt32LE(n, 40)
  return Buffer.concat([h, data])
}
const ctxPage = async (browser: Browser, email: string) => {
  const c = await browser.newContext({ baseURL: WEB, permissions: ['camera', 'microphone'] })
  const p = await c.newPage()
  await loginAs(p, email)
  return p
}

test.describe('F38 chat: emoji, files, music, stickers, reactions, voice messages and calls', () => {
  let mgrName = '', e1Name = '', mgrId = 0, e1Id = 0

  test.beforeAll(async () => {
    const f = await token(acct('founder'))
    const dir = (await api('GET', '/employees/directory', f)).body.items
    const mgr = dir.find((u: any) => u.email === acct('mgr')), e1 = dir.find((u: any) => u.email === acct('e1'))
    mgrName = mgr.full_name; e1Name = e1.full_name; mgrId = mgr.id; e1Id = e1.id
    expect((await api('POST', '/chat/conversations', await token(acct('e1')), { user_id: mgrId })).status).toBe(201)
  })

  test('F38-C1 send emoji, a photo, a document, music and a sticker; the other person sees and plays them', async ({ page, browser }) => {
    const done = watchErrors(page)
    await loginAs(page, acct('e1'))
    await page.goto('/chat')
    await page.getByRole('button', { name: new RegExp(mgrName) }).first().click()
    const box = page.getByRole('textbox', { name: 'Message', exact: true })

    await box.pressSequentially('Look ')
    await page.getByRole('button', { name: 'Emoji' }).click()
    await page.getByRole('tab', { name: 'Hearts' }).click()
    await page.getByRole('group', { name: 'Emoji' }).getByRole('button', { name: '🎉' }).click()
    await expect(box).toHaveValue('Look 🎉')
    await page.keyboard.press('Enter')
    await expect(page.getByRole('log').getByText('Look 🎉')).toBeVisible()

    await page.getByRole('button', { name: 'Attach a file' }).click()
    await page.getByLabel('Choose photo').setInputFiles({ name: 'sunset.png', mimeType: 'image/png', buffer: PNG })
    await box.fill('Sunset')
    await page.getByRole('button', { name: 'Send', exact: true }).click()
    await expect(page.getByRole('log').getByAltText('sunset.png')).toBeVisible()

    await page.getByLabel('Choose document').setInputFiles({ name: 'agenda.pdf', mimeType: 'application/pdf', buffer: PDF })
    await page.getByRole('button', { name: 'Send', exact: true }).click()
    await expect(page.getByRole('log').getByRole('button', { name: /agenda\.pdf/ })).toBeVisible()

    await page.getByLabel('Choose audio').setInputFiles({ name: 'song.wav', mimeType: 'audio/wav', buffer: wav() })
    await page.getByRole('button', { name: 'Send', exact: true }).click()
    await expect(page.getByRole('log').getByRole('group', { name: 'Audio song.wav' })).toBeVisible()

    await page.getByRole('button', { name: 'Stickers' }).click()
    await page.getByRole('button', { name: 'Send sticker: Celebrate' }).click()
    await expect(page.getByRole('log').getByRole('img', { name: 'Sticker: Celebrate' })).toBeVisible()
    await a11y(page, 'chat with media')

    // the manager receives all of it, the picture really decodes, the audio is playable, the document downloads
    const m = await ctxPage(browser, acct('mgr'))
    await m.goto('/chat')
    await m.getByRole('button', { name: new RegExp(e1Name) }).first().click()
    const log = m.getByRole('log')
    await expect(log.getByText('Sunset')).toBeVisible()
    const img = log.getByAltText('sunset.png')
    await expect(img).toBeVisible()
    await expect.poll(() => img.evaluate((el: HTMLImageElement) => el.naturalWidth)).toBeGreaterThan(0)
    const audio = log.getByRole('group', { name: 'Audio song.wav' }).locator('audio')
    await expect.poll(() => audio.evaluate((el: HTMLAudioElement) => el.readyState)).toBeGreaterThan(0)
    const [dl] = await Promise.all([m.waitForEvent('download'), log.getByRole('button', { name: /agenda\.pdf/ }).click()])
    expect(dl.suggestedFilename()).toBe('agenda.pdf')
    await expect(log.getByRole('img', { name: 'Sticker: Celebrate' })).toBeVisible()
    await expect(m.getByRole('list', { name: 'Conversations' }).getByText(/Sticker/)).toBeVisible()      // list preview, not raw ids
    done()
  })

  test('F38-C2 reactions: both people react, counts show, a second tap takes it back', async ({ page, browser }) => {
    const done = watchErrors(page)
    await loginAs(page, acct('e1'))
    await page.goto('/chat')
    await page.getByRole('button', { name: new RegExp(mgrName) }).first().click()
    await page.getByRole('textbox', { name: 'Message', exact: true }).fill('React to this one')
    await page.keyboard.press('Enter')
    const bubble = page.getByRole('log').locator('div.group', { hasText: 'React to this one' })
    await bubble.getByRole('button', { name: 'Add reaction' }).click()
    await bubble.getByRole('button', { name: 'React 👍' }).click()
    await expect(bubble.getByRole('button', { name: '👍 1, you reacted' })).toBeVisible()

    const m = await ctxPage(browser, acct('mgr'))
    await m.goto('/chat')
    await m.getByRole('button', { name: new RegExp(e1Name) }).first().click()
    const theirs = m.getByRole('log').locator('div.group', { hasText: 'React to this one' })
    await expect(theirs.getByRole('button', { name: '👍 1' })).toBeVisible()                           // arrived live or on load
    await theirs.getByRole('button', { name: '👍 1' }).click()
    await expect(theirs.getByRole('button', { name: '👍 2, you reacted' })).toBeVisible()
    await expect(bubble.getByRole('button', { name: '👍 2, you reacted' })).toBeVisible()               // pushed to the first browser
    await bubble.getByRole('button', { name: '👍 2, you reacted' }).click()                            // take mine back
    await expect(bubble.getByRole('button', { name: '👍 1' })).toBeVisible()
    done()
  })

  test('F38-C3 record and send a voice message; the other person can play it', async ({ page, browser }) => {
    const done = watchErrors(page)
    await loginAs(page, acct('e1'))
    await page.goto('/chat')
    await page.getByRole('button', { name: new RegExp(mgrName) }).first().click()
    await page.getByRole('button', { name: 'Record a voice message' }).click()
    await expect(page.getByRole('group', { name: 'Recording a voice message' })).toBeVisible()
    await page.waitForTimeout(1600)
    await page.getByRole('button', { name: 'Stop' }).click()                                              // recording ends in a preview, nothing is sent yet
    const preview = page.getByRole('group', { name: 'Voice message ready to send' })
    await expect(preview).toBeVisible()
    await expect(preview.getByRole('button', { name: 'Play', exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Send voice message' }).click()
    await expect(page.getByRole('log').getByText(/0:0[1-9]/).first()).toBeVisible()
    await expect(page.getByRole('textbox', { name: 'Message', exact: true })).toBeVisible()                // back to the normal composer

    await page.getByRole('button', { name: 'Record a voice message' }).click()                           // a second one is thrown away from the preview
    await page.waitForTimeout(700)
    await page.getByRole('button', { name: 'Stop' }).click()
    await page.getByRole('group', { name: 'Voice message ready to send' }).getByRole('button', { name: 'Delete' }).click()
    await expect(page.getByRole('textbox', { name: 'Message', exact: true })).toBeVisible()

    const m = await ctxPage(browser, acct('mgr'))
    await m.goto('/chat')
    await m.getByRole('button', { name: new RegExp(e1Name) }).first().click()
    const voice = m.getByRole('log').getByRole('group', { name: 'Voice message' }).last().locator('audio')
    await expect(voice).toBeAttached()                                                                    // the player's own <audio> element
    await expect(m.getByRole('log').getByRole('group', { name: 'Voice message' }).last().getByRole('button', { name: 'Play', exact: true })).toBeVisible()
    await expect.poll(() => voice.evaluate((el: HTMLAudioElement) => el.readyState)).toBeGreaterThan(0)
    const msgs = (await api('GET', `/chat/conversations/${(await api('GET', '/chat/conversations', await token(acct('e1')))).body.items.find((c: any) => c.members.some((x: any) => x.id === mgrId)).id}/messages`, await token(acct('e1')))).body.items
    const v = msgs.filter((x: any) => x.kind === 'audio' && x.file.name.startsWith('voice-')).pop()
    expect(v.file.mime).toMatch(/^audio\//)
    expect(v.file.duration_s).toBeGreaterThanOrEqual(1)
    done()
  })

  test('F38-C4 voice call and video call from the chat open a private room; the voice call joins without a camera', async ({ page, browser }) => {
    const done = watchErrors(page)
    await loginAs(page, acct('e1'))
    await page.goto('/chat')
    await page.getByRole('button', { name: new RegExp(mgrName) }).first().click()
    await page.getByRole('button', { name: `Voice call ${mgrName}` }).click()
    await page.waitForURL(/\/meetings\/[\w-]+\?audio=1$/)
    const room = new URL(page.url()).pathname.split('/').pop()!
    await expect(page.getByText('Call between')).toBeVisible()
    await expect(page.getByRole('button', { name: 'No camera' })).toBeDisabled()

    const m = await ctxPage(browser, acct('mgr'))
    await m.goto('/notifications')
    await expect(m.getByText('Incoming call').first()).toBeVisible()
    await m.goto(`/meetings/${room}`)
    await expect(page.locator('figcaption', { hasText: mgrName })).toBeVisible({ timeout: 20_000 })       // the two of them are connected
    await expect(m.locator('figcaption', { hasText: e1Name })).toBeVisible({ timeout: 20_000 })
    await expect(m.getByRole('button', { name: 'No camera' })).toBeDisabled()                              // a voice call opens no camera, even through a plain link

    await page.getByRole('button', { name: 'End call' }).click()                                             // the voice call is over for both people before the next call starts
    await page.waitForURL(/\/chat$/)
    await page.getByRole('button', { name: new RegExp(mgrName) }).first().click()
    await page.getByRole('button', { name: `Video call ${mgrName}` }).click()
    await page.waitForURL(/\/meetings\/[\w-]+$/)
    await expect(page.getByRole('button', { name: 'Camera off' })).toBeVisible({ timeout: 15_000 })
    done()
  })

  test('F38-C5 files that are not allowed are refused with a reason; strangers cannot read a file', async ({ page }) => {
    await loginAs(page, acct('e1'))
    await page.goto('/chat')
    await page.getByRole('button', { name: new RegExp(mgrName) }).first().click()
    await page.getByLabel('Choose document').setInputFiles({ name: 'evil.pdf', mimeType: 'application/pdf', buffer: Buffer.from('<script>alert(1)</script>') })
    await page.getByRole('button', { name: 'Send', exact: true }).click()
    await expect(page.getByRole('status', { name: /evil\.pdf, error/ })).toContainText(/does not match/i)   // the reason is shown on the file, with Retry and remove
    await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible()
    const t = await token(acct('e2'))
    const e1 = await token(acct('e1'))
    const conv = (await api('GET', '/chat/conversations', e1)).body.items.find((c: any) => c.members.some((x: any) => x.id === mgrId))
    const file = (await api('GET', `/chat/conversations/${conv.id}/messages`, e1)).body.items.find((x: any) => x.kind === 'image')
    expect((await api('GET', file.file.url, t)).status).toBe(404)
  })
})
