import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../../components/ui'

const get = vi.fn(), post = vi.fn(), patch = vi.fn(), upload = vi.fn(), downloadFn = vi.fn(), fetchBlob = vi.fn(), sendTyping = vi.fn()
const recorder = { supported: true, canPause: true, state: 'idle', seconds: 0, error: null, result: null, start: vi.fn(), pause: vi.fn(), resume: vi.fn(), stop: vi.fn(), discard: vi.fn() }
vi.mock('../../lib/api', async (orig) => ({ ...(await orig()), api: { get: (...a) => get(...a), post: (...a) => post(...a), patch: (...a) => patch(...a), del: vi.fn(), put: vi.fn() }, download: (...a) => downloadFn(...a), fetchBlobUrl: (...a) => fetchBlob(...a), uploadWithProgress: (...a) => upload(...a) }))
vi.mock('./useVoiceRecorder', () => ({ useVoiceRecorder: () => recorder, MAX_RECORD_SECONDS: 300 }))
vi.mock('../notifications/NotificationsProvider', () => ({ useRealtime: () => ({ sendTyping, presence: {}, typing: {}, connected: true }) }))

import AudioPlayer from './AudioPlayer'
import { Composer, MessageBubble } from './ChatParts'
import ImageViewer from './ImageViewer'
import { EmojiPicker, StickerPicker } from './Pickers'
import { checkFile, fmtDuration, fmtSize, frequentEmoji, insertAtCursor, recentEmoji, recordEmoji, searchEmoji } from './emoji'

const wrap = (ui) => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ToastProvider>{ui}</ToastProvider></QueryClientProvider>)
const base = { id: 1, conversation_id: 5, sender_id: 9, sender_name: 'Zoe', body: '', created_at: '2030-01-02T10:00:00Z', kind: 'text', reactions: [], deleted: false, edited_at: null, reply_to: null }
const handlers = () => ({ onReact: vi.fn(), onReply: vi.fn(), onEdit: vi.fn(), onDelete: vi.fn(), onOpenImage: vi.fn(), onJump: vi.fn() })

beforeEach(() => {
  vi.clearAllMocks(); localStorage.clear()
  Object.assign(recorder, { supported: true, canPause: true, state: 'idle', seconds: 0, error: null, result: null })
  get.mockResolvedValue({ items: [{ id: 'party', emoji: '🎉', label: 'Celebrate', category: 'Celebrate' }, { id: 'heart', emoji: '❤️', label: 'Love', category: 'Reactions' }, { id: 'thumbs_up', emoji: '👍', label: 'Thumbs up', category: 'Reactions' }], reactions: [] })
  fetchBlob.mockResolvedValue('blob:test')
  URL.createObjectURL = vi.fn(() => 'blob:preview'); URL.revokeObjectURL = vi.fn()
})

describe('helpers', () => {
  it('formats durations and sizes and inserts text at the caret', () => {
    expect(fmtDuration(75)).toBe('1:15'); expect(fmtSize(2048)).toBe('2 KB'); expect(fmtSize(3 * 1048576)).toBe('3.0 MB')
    expect(insertAtCursor({ selectionStart: 2, selectionEnd: 4 }, 'abcdef', '😀')).toEqual({ value: 'ab😀ef', cursor: 4 })
    expect(insertAtCursor(null, 'hi', '😀').value).toBe('hi😀')
  })
  it('finds emoji by name, keyword and category, and tracks recent and frequent use per person', () => {
    expect(searchEmoji('heart')).toContain('❤️'); expect(searchEmoji('party')).toContain('🎉'); expect(searchEmoji('coffee')).toContain('☕'); expect(searchEmoji('zzzz')).toEqual([]); expect(searchEmoji('  ')).toEqual([])
    recordEmoji(1, '😀'); recordEmoji(1, '🎉'); recordEmoji(1, '😀'); recordEmoji(2, '🔥')
    expect(recentEmoji(1)).toEqual(['😀', '🎉']); expect(frequentEmoji(1)[0]).toBe('😀'); expect(recentEmoji(2)).toEqual(['🔥'])
  })
  it('refuses files the server would refuse, before uploading', () => {
    expect(checkFile(new File(['x'], 'ok.png'))).toBeNull()
    expect(checkFile(new File(['x'], 'page.html'))).toMatch(/not allowed/)
    expect(checkFile(new File([], 'empty.pdf'))).toMatch(/empty/)
    const big = new File(['x'], 'big.mp3'); Object.defineProperty(big, 'size', { value: 26 * 1048576 })
    expect(checkFile(big)).toMatch(/larger than 25 MB/)
  })
})

describe('MessageBubble', () => {
  const mount = (m, props = {}) => wrap(<MessageBubble m={{ ...base, ...m }} me={2} mine={false} showSender={false} {...handlers()} {...props} />)

  it('shows text, edited marker, and read receipts on my own messages', () => {
    mount({ body: 'Hello', edited_at: '2030-01-02T11:00:00Z', sender_id: 2 }, { mine: true, receipt: 'read' })
    expect(screen.getByText('Hello')).toBeInTheDocument(); expect(screen.getByText('edited')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Read' })).toBeInTheDocument()
  })
  it.each([['sent', 'Sent'], ['delivered', 'Delivered']])('shows the %s state', (receipt, label) => {
    mount({ body: 'x', sender_id: 2 }, { mine: true, receipt })
    expect(screen.getByRole('img', { name: label })).toBeInTheDocument()
  })
  it('shows a quoted reply and jumps to the original when it is clicked', async () => {
    const h = handlers()
    mount({ body: 'Sure', reply_to: { id: 7, sender_name: 'Mia', preview: 'Can you send it?', kind: 'text' } }, h)
    await userEvent.click(screen.getByRole('button', { name: 'Replying to Mia: Can you send it?' }))
    expect(h.onJump).toHaveBeenCalledWith(7)
  })
  it('shows a deleted message as a placeholder with no content or actions', () => {
    mount({ deleted: true, body: '' })
    expect(screen.getByText(/This message was deleted/)).toBeInTheDocument()
    expect(screen.queryByRole('toolbar', { name: 'Message actions' })).not.toBeInTheDocument()
    mount({ id: 2, deleted: true, sender_id: 2 }, { mine: true })
    expect(screen.getByText(/You deleted this message/)).toBeInTheDocument()
  })
  it('offers reply, copy and react to everyone, but edit and delete only on my own messages', () => {
    mount({ body: 'theirs' })
    const bar = within(screen.getByRole('toolbar', { name: 'Message actions' }))
    expect(bar.getByRole('button', { name: 'Reply' })).toBeInTheDocument(); expect(bar.getByRole('button', { name: 'Copy text' })).toBeInTheDocument()
    expect(bar.queryByRole('button', { name: 'Edit message' })).not.toBeInTheDocument(); expect(bar.queryByRole('button', { name: 'Delete message' })).not.toBeInTheDocument()
  })
  it('lets me edit, and asks before deleting for everyone', async () => {
    const h = handlers()
    mount({ id: 4, body: 'mine', sender_id: 2 }, { mine: true, ...h })
    await userEvent.click(screen.getByRole('button', { name: 'Edit message' }))
    expect(h.onEdit).toHaveBeenCalledWith(expect.objectContaining({ id: 4, body: 'mine' }))
    await userEvent.click(screen.getByRole('button', { name: 'Delete message' }))
    expect(h.onDelete).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Keep' }))
    await userEvent.click(screen.getByRole('button', { name: 'Delete message' }))
    await userEvent.click(screen.getByRole('button', { name: 'Yes, delete' }))
    expect(h.onDelete).toHaveBeenCalledWith(4)
  })
  it('replies and reacts, and marks my own reaction (one tap removes it)', async () => {
    const h = handlers()
    mount({ id: 3, body: 'hi', reactions: [{ emoji: '👍', user_ids: [2, 7] }, { emoji: '❤️', user_ids: [7] }] }, h)
    await userEvent.click(screen.getByRole('button', { name: 'Reply' })); expect(h.onReply).toHaveBeenCalled()
    const mine = screen.getByRole('button', { name: '👍 2, you reacted' })
    expect(mine).toHaveAttribute('aria-pressed', 'true'); expect(screen.getByRole('button', { name: '❤️ 1' })).toHaveAttribute('aria-pressed', 'false')
    await userEvent.click(mine); expect(h.onReact).toHaveBeenCalledWith(3, '👍')
    await userEvent.click(screen.getByRole('button', { name: 'Add reaction' }))
    await userEvent.click(within(screen.getByRole('group', { name: 'Choose a reaction' })).getByRole('button', { name: 'React 🎉' }))
    expect(h.onReact).toHaveBeenLastCalledWith(3, '🎉')
  })
  it('shows a sticker large, a photo thumbnail that opens the viewer, and a document that downloads', async () => {
    const h = handlers()
    const { unmount } = mount({ kind: 'sticker', body: 'party', sticker: { id: 'party', emoji: '🎉', label: 'Celebrate' } }, h)
    expect(screen.getByRole('img', { name: 'Sticker: Celebrate' })).toHaveTextContent('🎉'); unmount()
    const { unmount: u2 } = mount({ id: 8, kind: 'image', file: { name: 'sun.png', size: 10, url: '/chat/messages/8/file' } }, h)
    await userEvent.click(await screen.findByRole('button', { name: 'Open photo sun.png' }))
    expect(h.onOpenImage).toHaveBeenCalledWith(8); expect(await screen.findByAltText('sun.png')).toHaveAttribute('src', 'blob:test'); u2()
    mount({ id: 9, kind: 'file', file: { name: 'plan.pdf', size: 4096, url: '/chat/messages/9/file' } }, h)
    expect(screen.getByText(/PDF · 4 KB · Tap to download/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /plan\.pdf/ }))
    expect(downloadFn).toHaveBeenCalledWith('/chat/messages/9/file', 'plan.pdf'); expect(await screen.findByText(/Downloaded/)).toBeInTheDocument()
  })
  it('reports a failed document download and lets the person retry', async () => {
    downloadFn.mockRejectedValueOnce(new Error('x'))
    mount({ kind: 'file', file: { name: 'a.docx', size: 10, url: '/chat/messages/1/file' } })
    await userEvent.click(screen.getByRole('button', { name: /a\.docx/ }))
    expect(await screen.findByText(/Failed, tap to retry/)).toBeInTheDocument()
  })
})

describe('AudioPlayer', () => {
  const stubMedia = () => {
    const played = []
    const paused = (el, v) => Object.defineProperty(el, 'paused', { value: v, configurable: true })   // jsdom never changes it by itself
    HTMLMediaElement.prototype.play = vi.fn(function () { played.push(this); paused(this, false); this.dispatchEvent(new Event('play')); return Promise.resolve() })
    HTMLMediaElement.prototype.pause = vi.fn(function () { paused(this, true); this.dispatchEvent(new Event('pause')) })
    return played
  }
  it('plays and pauses, shows elapsed and total time, changes speed, seeks and sets the volume', async () => {
    stubMedia()
    wrap(<AudioPlayer src="blob:a" name="song.mp3" duration={185} onDownload={vi.fn()} />)
    expect(screen.getByText('0:00 / 3:05')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Play' })); expect(screen.getByRole('button', { name: 'Pause' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Pause' })); expect(screen.getByRole('button', { name: 'Play' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Playback speed 1x' })); expect(screen.getByRole('button', { name: 'Playback speed 1.5x' })).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Seek'), { target: { value: '60' } }); expect(screen.getByText('1:00 / 3:05')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Volume'), { target: { value: '0' } }); expect(screen.getByLabelText('Volume')).toHaveValue('0')
    expect(screen.getByRole('button', { name: 'Download song.mp3' })).toBeInTheDocument()
  })
  it('lets only one player make sound at a time', async () => {
    stubMedia()
    wrap(<><AudioPlayer src="blob:a" name="one.mp3" duration={10} /><AudioPlayer src="blob:b" name="two.mp3" duration={10} /></>)
    const [first, second] = screen.getAllByRole('button', { name: 'Play' })
    await userEvent.click(first); expect(screen.getAllByRole('button', { name: 'Pause' })).toHaveLength(1)
    await userEvent.click(second)
    expect(screen.getAllByRole('button', { name: 'Pause' })).toHaveLength(1)   // the first one was paused by the second
    expect(screen.getAllByRole('button', { name: 'Play' })).toHaveLength(1)
  })
  it('voice messages have speed but no volume slider, and say so when the audio cannot be played', async () => {
    HTMLMediaElement.prototype.play = vi.fn(() => Promise.reject(new Error('blocked')))
    wrap(<AudioPlayer src="blob:v" name="voice-1.webm" duration={7} voice />)
    expect(screen.queryByLabelText('Volume')).not.toBeInTheDocument(); expect(screen.getByRole('group', { name: 'Voice message' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Play' }))
    expect(await screen.findByText(/could not be played/)).toBeInTheDocument()
  })
})

describe('pickers', () => {
  it('searches emoji, remembers what you pick, and closes on Escape', async () => {
    const onPick = vi.fn(), onClose = vi.fn()
    wrap(<EmojiPicker userId={1} onPick={onPick} onClose={onClose} />)
    await userEvent.type(screen.getByLabelText('Search emoji'), 'coffee')
    await userEvent.click(within(screen.getByLabelText('Search results')).getByRole('button', { name: '☕' }))
    expect(onPick).toHaveBeenCalledWith('☕')
    await userEvent.clear(screen.getByLabelText('Search emoji')); await userEvent.type(screen.getByLabelText('Search emoji'), 'qqqq')
    expect(screen.getByText(/No emoji match/)).toBeInTheDocument()
    await userEvent.keyboard('{Escape}'); expect(onClose).toHaveBeenCalled()
  })
  it('shows recently and frequently used emoji first, and switches categories', async () => {
    recordEmoji(1, '🔥'); recordEmoji(1, '🔥')
    wrap(<EmojiPicker userId={1} onPick={vi.fn()} onClose={vi.fn()} />)
    expect(screen.getByRole('region', { name: 'Frequently used' })).toHaveTextContent('🔥'); expect(screen.getByRole('region', { name: 'Recently used' })).toHaveTextContent('🔥')
    await userEvent.click(screen.getByRole('tab', { name: 'Hearts' })); expect(screen.getByRole('button', { name: /💔/ })).toBeInTheDocument()
  })
  it('stickers: categories, search, and favourites that persist', async () => {
    const onPick = vi.fn()
    wrap(<StickerPicker userId={1} onPick={onPick} onClose={vi.fn()} />)
    expect(await screen.findByRole('button', { name: 'Send sticker: Celebrate' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: 'Reactions' }))
    expect(screen.queryByRole('button', { name: 'Send sticker: Celebrate' })).not.toBeInTheDocument(); expect(screen.getByRole('button', { name: 'Send sticker: Love' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Add Love to favourites' }))
    await userEvent.click(screen.getByRole('tab', { name: 'Favourites' })); expect(screen.getByRole('button', { name: 'Send sticker: Love' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: 'All' })); await userEvent.type(screen.getByLabelText('Search stickers'), 'celeb')
    await userEvent.click(screen.getByRole('button', { name: 'Send sticker: Celebrate' })); expect(onPick).toHaveBeenCalledWith('party')
    expect(JSON.parse(localStorage.getItem('ws.chat.1.sticker.fav'))).toEqual(['heart'])
  })
})

describe('ImageViewer', () => {
  const items = [1, 2, 3].map((i) => ({ id: i, sender_name: 'Zoe', created_at: '2030-01-02T10:00:00Z', file: { name: `p${i}.png`, url: `/f/${i}` } }))
  it('moves between photos with buttons and arrow keys, downloads, and closes on Escape', async () => {
    const onIndex = vi.fn(), onClose = vi.fn()
    wrap(<ImageViewer items={items} index={1} onIndex={onIndex} onClose={onClose} />)
    expect(screen.getByRole('dialog', { name: 'Photo 2 of 3' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Next photo' })); expect(onIndex).toHaveBeenCalledWith(2)
    await userEvent.keyboard('{ArrowLeft}'); expect(onIndex).toHaveBeenCalledWith(0)
    await userEvent.click(screen.getByRole('button', { name: 'Download' })); expect(downloadFn).toHaveBeenCalledWith('/f/2', 'p2.png')
    await userEvent.keyboard('{Escape}'); expect(onClose).toHaveBeenCalled()
  })
})

describe('Composer', () => {
  const mount = (props = {}) => wrap(<Composer convId={5} me={1} {...props} />)
  const box = () => screen.getByRole('textbox', { name: 'Message' })

  it('sends text on Enter, tells the others it is typing, and inserts emoji at the caret', async () => {
    post.mockResolvedValue({})
    mount()
    await userEvent.type(box(), 'Hi '); expect(sendTyping).toHaveBeenCalledWith(5)
    await userEvent.click(screen.getByRole('button', { name: 'Emoji' }))
    await userEvent.click(within(screen.getByRole('group', { name: 'Emoji' })).getAllByRole('button', { name: /^😀/ })[0])
    expect(box()).toHaveValue('Hi 😀')
    await userEvent.type(box(), '{Enter}')
    await waitFor(() => expect(post).toHaveBeenCalledWith('/chat/conversations/5/messages', { body: 'Hi 😀' }))
  })
  it('shows a like button while the box is empty, and sends a thumbs-up sticker', async () => {
    post.mockResolvedValue({})
    mount()
    expect(screen.queryByRole('button', { name: 'Send' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Send a like' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/chat/conversations/5/stickers', { sticker: 'thumbs_up' }))
    await userEvent.type(box(), 'x'); expect(screen.queryByRole('button', { name: 'Send a like' })).not.toBeInTheDocument(); expect(screen.getByRole('button', { name: 'Send' })).toBeInTheDocument()
  })
  it('sends a sticker and remembers it as recent', async () => {
    post.mockResolvedValue({})
    mount()
    await userEvent.click(screen.getByRole('button', { name: 'Stickers' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Send sticker: Celebrate' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/chat/conversations/5/stickers', { sticker: 'party' }))
    expect(JSON.parse(localStorage.getItem('ws.chat.1.sticker.recent'))).toEqual(['party'])
  })
  it('sends a reply with the original id, and clears the reply banner', async () => {
    post.mockResolvedValue({})
    const onClearReply = vi.fn()
    mount({ replyTo: { id: 11, sender_name: 'Mia', preview: 'Question?' }, onClearReply })
    expect(screen.getByText('Replying to Mia')).toBeInTheDocument()
    await userEvent.type(box(), 'Answer{Enter}')
    await waitFor(() => expect(post).toHaveBeenCalledWith('/chat/conversations/5/messages', { body: 'Answer', reply_to_id: 11 }))
    expect(onClearReply).toHaveBeenCalled()
  })
  it('edits a message: pre-fills the text, saves with PATCH, and can be cancelled', async () => {
    patch.mockResolvedValue({})
    const onClearEdit = vi.fn()
    mount({ editing: { id: 4, body: 'old text' }, onClearEdit })
    expect(box()).toHaveValue('old text'); expect(screen.getByText('Editing message')).toBeInTheDocument()
    await userEvent.clear(box()); await userEvent.type(box(), 'new text')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(patch).toHaveBeenCalledWith('/chat/messages/4', { body: 'new text' }))
    expect(onClearEdit).toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Cancel edit' })); expect(onClearEdit).toHaveBeenCalledTimes(2)
  })
  it('lets me change or remove the caption of a photo, voice message or file (an empty box is allowed there)', async () => {
    patch.mockResolvedValue({})
    const onClearEdit = vi.fn()
    mount({ editing: { id: 8, body: 'old caption', kind: 'image' }, onClearEdit })
    await userEvent.clear(box())
    expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled()
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(patch).toHaveBeenCalledWith('/chat/messages/8', { body: '' }))
    expect(onClearEdit).toHaveBeenCalled()
  })
  it('a text message cannot be saved empty, and saving the same words just closes the editor without a request', async () => {
    const onClearEdit = vi.fn()
    mount({ editing: { id: 4, body: 'same words', kind: 'text' }, onClearEdit })
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(patch).not.toHaveBeenCalled(); expect(onClearEdit).toHaveBeenCalled()
  })
  it('an emptied text message cannot be saved', async () => {
    mount({ editing: { id: 4, body: 'x', kind: 'text' } })
    await userEvent.clear(box())
    expect(screen.getByRole('button', { name: 'Send a like' })).toBeInTheDocument()          // nothing to save: the box is empty
    expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument()
  })
  it('while editing it shows the original text, blocks attachments, and does not announce typing', async () => {
    mount({ editing: { id: 4, body: 'the original words', kind: 'text' } })
    expect(screen.getByText('Editing message')).toBeInTheDocument(); expect(screen.getAllByText('the original words').length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: 'Attach a file' })).toBeDisabled(); expect(screen.getByRole('button', { name: 'Stickers' })).toBeDisabled()
    await userEvent.type(box(), '!')
    expect(sendTyping).not.toHaveBeenCalled()
  })
  it('files queued before pressing Edit are not sent as part of the edit', async () => {
    patch.mockResolvedValue({})
    mount({ editing: { id: 4, body: 'a', kind: 'text' }, incoming: [new File(['x'], 'dropped.png')], onIncomingHandled: vi.fn() })
    await userEvent.type(box(), 'b')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(patch).toHaveBeenCalledWith('/chat/messages/4', { body: 'ab' }))
    expect(upload).not.toHaveBeenCalled()
  })
  it('queues several files with previews, refuses bad ones with a reason, and sends them one by one with progress', async () => {
    let progress
    upload.mockImplementation((path, file, fields, opts) => { progress = opts.onProgress; return Promise.resolve({}) })
    mount()
    const png = new File(['x'], 'cat.png', { type: 'image/png' }), pdf = new File(['x'], 'plan.pdf', { type: 'application/pdf' }), html = new File(['x'], 'evil.html')
    fireEvent.change(screen.getByLabelText('Choose photo'), { target: { files: [png, pdf, html] } })
    expect(screen.getByRole('alert')).toHaveTextContent(/evil\.html: this file type is not allowed/)
    const list = screen.getByRole('list', { name: 'Attachments to send' })
    expect(within(list).getAllByRole('status')).toHaveLength(2); expect(list.querySelector('img')).toHaveAttribute('src', 'blob:preview')
    await userEvent.type(box(), 'Both files')
    await userEvent.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(2))
    expect(upload).toHaveBeenNthCalledWith(1, '/chat/conversations/5/attachments', png, { caption: 'Both files' }, expect.objectContaining({ onProgress: expect.any(Function), signal: expect.anything() }))
    expect(upload).toHaveBeenNthCalledWith(2, '/chat/conversations/5/attachments', pdf, { caption: '' }, expect.anything())
    expect(typeof progress).toBe('function')
    await waitFor(() => expect(screen.queryByRole('list', { name: 'Attachments to send' })).not.toBeInTheDocument())
  })
  it('shows upload progress, lets me cancel it, and keeps the file so I can try again', async () => {
    let onProgress, signal
    upload.mockImplementation((p, f, fields, opts) => { onProgress = opts.onProgress; signal = opts.signal; return new Promise((_, rej) => opts.signal.addEventListener('abort', () => rej(Object.assign(new Error('cancelled'), { name: 'AbortError' })))) })
    mount()
    fireEvent.change(screen.getByLabelText('Choose document'), { target: { files: [new File(['x'], 'big.pdf')] } })
    await userEvent.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => expect(upload).toHaveBeenCalled())
    act(() => onProgress(40))
    expect(await screen.findByRole('progressbar', { name: 'Uploading big.pdf' })).toHaveAttribute('aria-valuenow', '40')
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(signal.aborted).toBe(true))
    await waitFor(() => expect(screen.queryByRole('progressbar')).not.toBeInTheDocument())
    expect(screen.getByRole('status', { name: /big\.pdf, ready/ })).toBeInTheDocument()
  })
  it('shows the server reason when an upload fails and offers a retry', async () => {
    upload.mockRejectedValueOnce(Object.assign(new Error('The file content does not match its type'), { name: 'ApiError' })).mockResolvedValueOnce({})
    mount()
    fireEvent.change(screen.getByLabelText('Choose document'), { target: { files: [new File(['x'], 'a.pdf')] } })
    await userEvent.click(screen.getByRole('button', { name: 'Send' }))
    expect(await screen.findByText('The file content does not match its type')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await userEvent.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(2))
  })
  it('takes files dropped onto the chat', async () => {
    const onHandled = vi.fn()
    mount({ incoming: [new File(['x'], 'dropped.png')], onIncomingHandled: onHandled })
    expect(await screen.findByRole('status', { name: /dropped\.png/ })).toBeInTheDocument(); expect(onHandled).toHaveBeenCalled()
  })
  it('records: pause, resume, stop; then previews, sends or deletes the voice message', async () => {
    recorder.state = 'recording'; recorder.seconds = 5
    const { unmount } = mount()
    expect(screen.getByRole('group', { name: 'Recording a voice message' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Pause' })); expect(recorder.pause).toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Stop' })); expect(recorder.stop).toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' })); expect(recorder.discard).toHaveBeenCalled(); unmount()
    recorder.state = 'paused'; mount(); expect(screen.getByRole('button', { name: 'Resume' })).toBeInTheDocument()
  })
  it('previews a recording and uploads the real file with its length', async () => {
    const file = new File(['a'], 'recording.webm', { type: 'audio/webm' })
    Object.assign(recorder, { state: 'preview', result: { file, seconds: 7, url: 'blob:rec' } })
    upload.mockResolvedValue({})
    mount()
    expect(screen.getByRole('group', { name: 'Voice message ready to send' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Send voice message' }))
    await waitFor(() => expect(upload).toHaveBeenCalledWith('/chat/conversations/5/attachments', file, { voice: 'true', duration: '7', caption: '' }, expect.anything()))
    await waitFor(() => expect(recorder.discard).toHaveBeenCalled())
  })
  it('keeps the recording when sending fails, shows why, and lets me retry or delete it', async () => {
    Object.assign(recorder, { state: 'preview', result: { file: new File(['a'], 'recording.webm'), seconds: 3, url: 'blob:rec' } })
    upload.mockRejectedValue(new Error('Upload failed: cannot reach the server.'))
    mount()
    recorder.discard.mockClear() // the composer resets itself once when it opens
    await userEvent.click(screen.getByRole('button', { name: 'Send voice message' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/cannot reach the server/)
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument(); expect(screen.getByRole('button', { name: 'Delete' })).toBeInTheDocument()
    expect(recorder.discard).not.toHaveBeenCalled()
  })
  it('shows recorder errors such as a blocked microphone, and has no mic button without support', () => {
    recorder.error = 'Microphone access was blocked. Allow it in the browser to record.'
    mount(); expect(screen.getByRole('alert')).toHaveTextContent(/Microphone access was blocked/)
  })
  it('has no microphone button when the browser cannot record', () => {
    recorder.supported = false
    mount(); expect(screen.queryByRole('button', { name: 'Record a voice message' })).not.toBeInTheDocument(); expect(screen.getByRole('button', { name: 'Send a like' })).toBeInTheDocument()
  })
  it('disables everything when the rules no longer allow messaging', () => {
    mount({ disabled: true })
    expect(box()).toBeDisabled(); expect(screen.getByRole('button', { name: 'Emoji' })).toBeDisabled(); expect(screen.getByRole('button', { name: 'Attach a file' })).toBeDisabled(); expect(screen.getByRole('button', { name: 'Send a like' })).toBeDisabled()
  })
})
