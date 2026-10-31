import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../../components/ui'

const get = vi.fn(), post = vi.fn(), del = vi.fn()
const auth = { user: { id: 1, role: 'manager', full_name: 'Mia Manager' }, role: 'manager' }
vi.mock('../auth/AuthContext', () => ({ useAuth: () => auth }))
vi.mock('../../lib/api', async (orig) => ({ ...(await orig()), api: { get: (...a) => get(...a), post: (...a) => post(...a), del: (...a) => del(...a), patch: vi.fn(), put: vi.fn() } }))
vi.mock('./useMeeting', () => ({ useMeeting: () => ({ status: 'live', callState: 'waiting', error: null, local: { getVideoTracks: () => [{}], getAudioTracks: () => [{}] }, remotes: {}, muted: false, camOff: false, sharing: false, quality: null, connectedAt: null, devices: { mics: [], cams: [], speakers: [] }, speakerId: '', setSpeakerId: vi.fn(), hasCamera: true, toggleMic: vi.fn(), toggleCam: vi.fn(), toggleShare: vi.fn(), selectMic: vi.fn(), selectCamera: vi.fn(), switchCamera: vi.fn() }) }))

import MeetingRoomPage from './MeetingRoomPage'
import MeetingsPage from './MeetingsPage'

const wrap = (ui, path = '/meetings') => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <ToastProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes><Route path="/meetings" element={ui} /><Route path="/meetings/:room" element={ui} /></Routes>
      </MemoryRouter>
    </ToastProvider>
  </QueryClientProvider>,
)
const people = [
  { id: 2, full_name: 'Eli Employee', designation: 'Engineer' },
  { id: 3, full_name: 'Zoe Zhang', designation: null },
]
const base = {
  '/chat/users': { items: people },
  '/teams/mine': { items: [{ id: 7, name: 'Mobile' }] },
  '/chat/conversations': { items: [{ id: 9, kind: 'group', title: 'Release crew', members: [{ id: 1 }, { id: 2 }, { id: 3 }] }, { id: 10, kind: 'dm', title: 'Eli', members: [{ id: 1 }, { id: 2 }] }] },
}
const respond = (map) => get.mockImplementation(async (path) => {
  if (path in { ...base, ...map }) return { ...base, ...map }[path]
  throw new Error(`unexpected GET ${path}`)
})
const mine = { id: 5, title: 'Planning', room_id: 'abc', host_id: 1, kind: 'meeting', status: 'scheduled', scheduled_at: null, is_host: true,
  participants: [{ id: 1, name: 'Mia Manager', is_host: true }, { id: 2, name: 'Eli Employee', is_host: false }] }

beforeEach(() => { vi.clearAllMocks(); auth.user = { id: 1, role: 'manager', full_name: 'Mia Manager' }; auth.role = 'manager' })

describe('MeetingsPage', () => {
  it('shows who each meeting is with and marks calls', async () => {
    respond({ '/meetings': { items: [mine, { ...mine, id: 6, title: 'Quick chat', room_id: 'c1', kind: 'call', participants: [{ id: 1, name: 'Mia Manager', is_host: true }, { id: 3, name: 'Zoe Zhang' }] }, { ...mine, id: 8, title: 'Solo', room_id: 's', participants: [{ id: 1, name: 'Mia Manager', is_host: true }] }] } })
    wrap(<MeetingsPage />)
    expect(await screen.findByText('Eli Employee')).toBeInTheDocument()
    expect(screen.getByText('Zoe Zhang')).toBeInTheDocument()
    expect(screen.getByText('Only you')).toBeInTheDocument()
    expect(screen.getByText('Call')).toBeInTheDocument()
  })

  it('calls exactly one chosen person', async () => {
    respond({ '/meetings': { items: [] } })
    post.mockResolvedValue({ ...mine, room_id: 'call1', kind: 'call' })
    wrap(<MeetingsPage />)
    await userEvent.click(await screen.findByRole('button', { name: 'Call someone' }))
    const dlg = within(await screen.findByRole('dialog'))
    expect(dlg.getByRole('button', { name: 'Call' })).toBeDisabled()
    await userEvent.type(dlg.getByRole('searchbox'), 'zoe')
    expect(dlg.queryByText('Eli Employee')).not.toBeInTheDocument()
    await userEvent.click(await dlg.findByRole('radio'))
    await userEvent.click(dlg.getByRole('button', { name: 'Call' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/meetings/call', { user_id: 3 }))
  })

  it('invites a chosen set of people, a team and a chat group, and nobody else', async () => {
    respond({ '/meetings': { items: [] } })
    post.mockResolvedValue({ ...mine, scheduled_at: '2030-01-01T10:00:00Z' })
    wrap(<MeetingsPage />)
    await userEvent.click(await screen.findByRole('button', { name: 'New meeting' }))
    const dlg = within(await screen.findByRole('dialog'))
    expect(dlg.getByText('Only you can join until you invite someone.')).toBeInTheDocument()
    expect(dlg.queryByText('Eli')).not.toBeInTheDocument() // direct messages are not offered as groups
    await userEvent.type(dlg.getByLabelText(/Title/), 'Sprint review')
    await userEvent.click(await dlg.findByText('Eli Employee'))
    await userEvent.click(dlg.getByText('Mobile'))
    await userEvent.click(dlg.getByText('Release crew'))
    expect(dlg.getByText('1 people, 1 teams, 1 groups selected')).toBeInTheDocument()
    await userEvent.click(dlg.getByRole('button', { name: 'Start now' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/meetings', { title: 'Sprint review', scheduled_at: null, invitee_ids: [2], team_ids: [7], group_ids: [9] }))
  })

  it('an instant meeting is private to the host', async () => {
    respond({ '/meetings': { items: [] } })
    post.mockResolvedValue({ ...mine, room_id: 'now' })
    wrap(<MeetingsPage />)
    await userEvent.click(await screen.findByRole('button', { name: 'Start instant meeting' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/meetings', { title: "Mia Manager's meeting", scheduled_at: null, invitee_ids: [], team_ids: [], group_ids: [] }))
  })
})

describe('MeetingRoomPage', () => {
  it('lets the host invite more people and remove an invited one', async () => {
    respond({ '/meetings/abc': mine })
    post.mockResolvedValue({ added: 1, participants: [] })
    del.mockResolvedValue(null)
    wrap(<MeetingRoomPage />, '/meetings/abc')
    expect(await screen.findByText('Invited (2)')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Remove Eli Employee' }))
    await waitFor(() => expect(del).toHaveBeenCalledWith('/meetings/abc/participants/2'))
    await userEvent.click(screen.getByRole('button', { name: 'Invite more' }))
    const dlg = within(await screen.findByRole('dialog'))
    expect(dlg.queryByText('Eli Employee')).not.toBeInTheDocument() // already invited
    await userEvent.click(await dlg.findByText('Zoe Zhang'))
    await userEvent.click(dlg.getByRole('button', { name: 'Invite' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/meetings/abc/participants', { invitee_ids: [3], team_ids: [], group_ids: [] }))
  })

  it('gives an invited guest no way to add, remove or end', async () => {
    auth.user = { id: 2, role: 'employee', full_name: 'Eli Employee' }
    auth.role = 'employee'
    respond({ '/meetings/abc': { ...mine, is_host: false } })
    wrap(<MeetingRoomPage />, '/meetings/abc')
    expect(await screen.findByText('Invited (2)')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Invite more|Remove|End meeting/ })).not.toBeInTheDocument()
  })

  it('a call is shown as private and cannot take more people', async () => {
    respond({ '/meetings/abc': { ...mine, kind: 'call' } })
    wrap(<MeetingRoomPage />, '/meetings/abc')
    expect(await screen.findByText('Call between')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Invite more|Remove/ })).not.toBeInTheDocument()
  })
})
