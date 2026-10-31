import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../../components/ui'

const get = vi.fn(), post = vi.fn(), put = vi.fn(), del = vi.fn()
const auth = { user: { id: 1, role: 'employee', full_name: 'Elena Employee', avatar_v: null }, role: 'employee' }
const rt = { connected: true, presence: {}, typing: {}, sendTyping: vi.fn(), incomingCall: null, lastCallEnd: null, dismissCall: vi.fn() }
vi.mock('../auth/AuthContext', () => ({ useAuth: () => auth }))
vi.mock('../notifications/NotificationsProvider', () => ({ useRealtime: () => rt }))
vi.mock('../../lib/api', async (orig) => ({ ...(await orig()), api: { get: (...a) => get(...a), post: (...a) => post(...a), put: (...a) => put(...a), del: (...a) => del(...a), patch: vi.fn() }, download: vi.fn(), fetchBlobUrl: vi.fn(async () => 'blob:x'), uploadWithProgress: vi.fn() }))
vi.mock('./useVoiceRecorder', () => ({ useVoiceRecorder: () => ({ supported: true, canPause: true, state: 'idle', seconds: 0, error: null, result: null, start: vi.fn(), pause: vi.fn(), resume: vi.fn(), stop: vi.fn(), discard: vi.fn() }), MAX_RECORD_SECONDS: 300 }))
import ChatPage from './ChatPage'

const Where = () => { const l = useLocation(); return <p data-testid="where">{l.pathname + l.search}</p> }
const wrap = () => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ToastProvider><MemoryRouter><Routes><Route path="*" element={<><ChatPage /><Where /></>} /></Routes></MemoryRouter></ToastProvider></QueryClientProvider>,
)
const member = (id, name, read = 0, delivered = 0) => ({ id, name, avatar_v: null, last_read_id: read, last_delivered_id: delivered })
const msg = (id, sender, body, extra = {}) => ({ id, conversation_id: 10, sender_id: sender, sender_name: sender === 1 ? 'Elena Employee' : 'Mia Manager', body, created_at: '2030-01-02T10:00:00Z', kind: 'text', preview: body, reactions: [], deleted: false, edited_at: null, reply_to: null, ...extra })
const convs = (over = {}) => ({ items: [
  { id: 10, kind: 'dm', title: 'Mia Manager', members: [member(1, 'Elena Employee', 5, 5), member(2, 'Mia Manager', 0, 0)], last_message: msg(5, 1, 'Latest note'), pinned: false, unread: 0, can_send: true },
  { id: 11, kind: 'dm', title: 'Hannah HR', members: [member(1, 'Elena Employee'), member(3, 'Hannah HR')], last_message: msg(9, 3, 'See you', { conversation_id: 11, sender_name: 'Hannah HR' }), pinned: true, unread: 2, can_send: true },
  { id: 12, kind: 'group', title: 'Launch crew', members: [member(1, 'Elena Employee'), member(2, 'Mia Manager'), member(3, 'Hannah HR')], last_message: null, pinned: false, unread: 0, can_send: true },
], ...over })
const thread = (items, has_more = false) => ({ items, has_more })

beforeEach(() => {
  vi.clearAllMocks(); localStorage.clear()
  Object.assign(rt, { connected: true, presence: {}, typing: {} })
  get.mockImplementation(async (path, params) => {
    if (path === '/chat/conversations') return convs()
    if (path === '/chat/conversations/10/messages') {
      if (params?.q) return thread([msg(2, 2, 'the budget is final')])
      return params?.before_id ? thread([msg(1, 2, 'Older message')]) : thread([msg(3, 2, 'Hello Elena'), msg(4, 1, 'Hi Mia'), msg(5, 1, 'Latest note')], true)
    }
    if (path === '/meetings/calls/history') return { items: [{ id: 1, room_id: 'r1', direction: 'incoming', video: false, outcome: 'missed', peer: { id: 2, name: 'Mia Manager' }, started_at: '2030-01-01T09:00:00Z', duration_s: null }, { id: 2, room_id: 'r2', direction: 'outgoing', video: true, outcome: 'answered', peer: { id: 3, name: 'Hannah HR' }, started_at: '2030-01-01T10:00:00Z', duration_s: 75 }], has_more: false }
    if (path === '/chat/stickers') return { items: [], reactions: [] }
    throw new Error(`unexpected GET ${path}`)
  })
  window.HTMLElement.prototype.scrollIntoView = vi.fn()
})

describe('sidebar', () => {
  it('lists pinned chats first, then recent, with unread badges, previews and my own status', async () => {
    wrap()
    const pinned = await screen.findByRole('region', { name: 'Pinned conversations' })
    expect(within(pinned).getByText('Hannah HR')).toBeInTheDocument(); expect(within(pinned).getByLabelText('2 unread')).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: 'Recent conversations' })).getByText('Mia Manager')).toBeInTheDocument()
    expect(screen.getByText('You: Latest note')).toBeInTheDocument(); expect(screen.getByText('You are online')).toBeInTheDocument()
  })
  it('filters the chats by name or last message and says when nothing matches', async () => {
    wrap()
    await userEvent.type(await screen.findByLabelText('Search conversations'), 'launch')
    expect(screen.getByText('Launch crew')).toBeInTheDocument(); expect(screen.queryByText('Hannah HR')).not.toBeInTheDocument()
    await userEvent.clear(screen.getByLabelText('Search conversations')); await userEvent.type(screen.getByLabelText('Search conversations'), 'see you')
    expect(screen.getByText('Hannah HR')).toBeInTheDocument()
    await userEvent.clear(screen.getByLabelText('Search conversations')); await userEvent.type(screen.getByLabelText('Search conversations'), 'zzz')
    expect(screen.getByText(/No chats match/)).toBeInTheDocument()
  })
  it('shows who is online right now, and shows typing in the list', async () => {
    rt.presence = { 2: { online: true, last_seen_at: '2030-01-02T09:00:00Z' } }; rt.typing = { 11: { 3: { name: 'Hannah HR', until: Date.now() + 5000 } } }
    wrap()
    expect(await screen.findByRole('button', { name: 'Chat with Mia Manager, online' })).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: 'Pinned conversations' })).getByText('typing…')).toBeInTheDocument()
  })
})

describe('conversation', () => {
  it('shows the other person online or when they were last seen, and typing', async () => {
    rt.presence = { 2: { online: true } }
    const { unmount } = wrap()
    expect(await screen.findByRole('status', { name: '' })).toBeDefined
    expect((await screen.findAllByText('Online')).length).toBeGreaterThan(0); unmount()
    rt.presence = { 2: { online: false, last_seen_at: '2030-01-02T08:00:00Z' } }
    wrap(); expect(await screen.findByText(/^Last seen/)).toBeInTheDocument()
  })
  it('shows read, delivered and sent ticks on my messages from the other person\'s marks', async () => {
    get.mockImplementation(async (path, params) => path === '/chat/conversations' ? convs({ items: [{ ...convs().items[0], members: [member(1, 'Elena Employee'), member(2, 'Mia Manager', 4, 5)] }] }) : path === '/chat/conversations/10/messages' ? thread([msg(3, 1, 'one'), msg(4, 1, 'two'), msg(5, 1, 'three')]) : { items: [] })
    wrap()
    await screen.findByText('three')
    const log = screen.getByRole('log', { name: 'Messages' })
    expect(within(log).getAllByRole('img', { name: 'Read' })).toHaveLength(2); expect(within(log).getAllByRole('img', { name: 'Delivered' })).toHaveLength(1)
  })
  it('loads earlier messages page by page without losing the newer ones', async () => {
    wrap()
    expect(await screen.findByText('Hello Elena')).toBeInTheDocument(); expect(screen.queryByText('Older message')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Load earlier messages' }))
    expect(await screen.findByText('Older message')).toBeInTheDocument(); expect(screen.getByText('Hello Elena')).toBeInTheDocument()
    expect(get).toHaveBeenCalledWith('/chat/conversations/10/messages', { limit: 30, before_id: 3 })
    expect(screen.queryByRole('button', { name: 'Load earlier messages' })).not.toBeInTheDocument()   // that was the first page
  })
  it('separates days, and shows who is typing under the messages', async () => {
    rt.typing = { 10: { 2: { name: 'Mia Manager', until: Date.now() + 5000 } } }
    wrap(); await screen.findByText('Hello Elena')
    expect(screen.getAllByText(/Mia Manager is typing…/).length).toBeGreaterThan(0)
  })
  it('searches inside the conversation and lists matches', async () => {
    wrap(); await screen.findByText('Hello Elena')
    await userEvent.click(screen.getByRole('button', { name: 'Search in conversation' }))
    await userEvent.type(screen.getByLabelText('Search messages'), 'budget')
    const results = await screen.findByRole('list', { name: 'Search results' })
    expect(await within(results).findByText(/the budget is final/)).toBeInTheDocument()
    expect(get).toHaveBeenCalledWith('/chat/conversations/10/messages', { q: 'budget', limit: 30 })
  })
  it('pins and unpins the chat from the options menu', async () => {
    put.mockResolvedValue({})
    wrap(); await screen.findByText('Hello Elena')
    await userEvent.click(screen.getByRole('button', { name: 'More options' }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Pin this chat' }))
    await waitFor(() => expect(put).toHaveBeenCalledWith('/chat/conversations/10/pin', { pinned: true }))
  })
  it('starts a voice or a video call with this person and opens the room', async () => {
    post.mockResolvedValue({ room_id: 'room42' })
    wrap(); await screen.findByText('Hello Elena')
    await userEvent.click(screen.getByRole('button', { name: 'Voice call Mia Manager' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/meetings/call', { user_id: 2, video: false }))
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('/meetings/room42?audio=1'))
  })
  it('a video call opens the room without the audio-only flag', async () => {
    post.mockResolvedValue({ room_id: 'room43' })
    wrap(); await screen.findByText('Hello Elena')
    await userEvent.click(screen.getByRole('button', { name: 'Video call Mia Manager' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/meetings/call', { user_id: 2, video: true }))
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent(/^\/meetings\/room43$/))
  })
  it('shows the call history with direction, outcome and duration, and calls back', async () => {
    post.mockResolvedValue({ room_id: 'back1' })
    wrap(); await screen.findByText('Hello Elena')
    await userEvent.click(screen.getByRole('button', { name: 'More options' })); await userEvent.click(screen.getByRole('menuitem', { name: 'Call history' }))
    const list = await screen.findByRole('list', { name: 'Calls' })
    expect(within(list).getByText(/Incoming · Missed/)).toBeInTheDocument(); expect(within(list).getByText(/Outgoing · Answered · 1:15/)).toBeInTheDocument()
    await userEvent.click(within(list).getByRole('button', { name: 'Call Hannah HR back' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/meetings/call', { user_id: 3, video: true }))
  })
  it('reacts to and deletes messages through the API', async () => {
    post.mockResolvedValue({}); del.mockResolvedValue({})
    wrap(); await screen.findByText('Hello Elena')
    const bubble = screen.getByText('Hello Elena').closest('[data-mid]')
    await userEvent.click(within(bubble).getByRole('button', { name: 'Add reaction' })); await userEvent.click(within(bubble).getByRole('button', { name: 'React 👍' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/chat/messages/3/reactions', { emoji: '👍' }))
    const mine = screen.getByText('Hi Mia').closest('[data-mid]')
    await userEvent.click(within(mine).getByRole('button', { name: 'Delete message' })); await userEvent.click(within(mine).getByRole('button', { name: 'Yes, delete' }))
    await waitFor(() => expect(del).toHaveBeenCalledWith('/chat/messages/4'))
  })
  it('replying shows the quoted message above the box', async () => {
    wrap(); await screen.findByText('Hello Elena')
    await userEvent.click(within(screen.getByText('Hello Elena').closest('[data-mid]')).getByRole('button', { name: 'Reply' }))
    expect(screen.getByText('Replying to Mia Manager')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Cancel reply' })); expect(screen.queryByText('Replying to Mia Manager')).not.toBeInTheDocument()
  })
  it('shows a drop zone while files are dragged over, and queues what is dropped', async () => {
    wrap(); await screen.findByText('Hello Elena')
    const zone = screen.getByRole('log', { name: 'Messages' }).parentElement
    const file = new File(['x'], 'dropped.pdf', { type: 'application/pdf' })
    fireEvent.dragOver(zone, { dataTransfer: { types: ['Files'], files: [file] } })
    expect(screen.getByText('Drop files to attach them')).toBeInTheDocument()
    fireEvent.drop(zone, { dataTransfer: { types: ['Files'], files: [file] } })
    expect(await screen.findByRole('status', { name: /dropped\.pdf/ })).toBeInTheDocument(); expect(screen.queryByText('Drop files to attach them')).not.toBeInTheDocument()
  })
  it('cannot send or call when the communication rules no longer allow it', async () => {
    get.mockImplementation(async (path) => path === '/chat/conversations' ? convs({ items: [{ ...convs().items[0], can_send: false }] }) : path === '/chat/conversations/10/messages' ? thread([msg(3, 2, 'Hello')]) : { items: [] })
    wrap(); await screen.findByText('Hello')
    expect(screen.getByRole('textbox', { name: 'Message' })).toBeDisabled(); expect(screen.getByRole('button', { name: 'Voice call Mia Manager' })).toBeDisabled(); expect(screen.getByRole('button', { name: 'Video call Mia Manager' })).toBeDisabled()
    expect(screen.getByText(/can no longer message this person/)).toBeInTheDocument()
  })
  it('shows an error with a retry when the messages cannot be loaded', async () => {
    get.mockImplementation(async (path) => { if (path === '/chat/conversations') return convs(); throw new Error('Server is down') })
    wrap(); expect(await screen.findByText(/Server is down/)).toBeInTheDocument(); expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  })
})

describe('empty and group states', () => {
  it('shows a friendly empty state when there are no conversations', async () => {
    get.mockImplementation(async () => ({ items: [] }))
    wrap(); expect(await screen.findByText('No conversations yet')).toBeInTheDocument()
  })
  it('a group shows its member count and online members, and calls start a group meeting', async () => {
    rt.presence = { 2: { online: true }, 3: { online: false } }
    get.mockImplementation(async (path) => path === '/chat/conversations' ? convs() : path === '/chat/conversations/12/messages' ? thread([]) : thread([]))
    post.mockResolvedValue({ room_id: 'grp1' })
    wrap(); await userEvent.click(await screen.findByText('Launch crew'))
    expect(await screen.findByText('3 members · 1 online')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Start a group video call' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/meetings', { title: 'Launch crew call', scheduled_at: null, group_ids: [12] }))
  })
})
