import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../../components/ui'

const post = vi.fn(), dismissCall = vi.fn()
const rt = { incomingCall: null, dismissCall }
vi.mock('../../lib/api', async (orig) => ({ ...(await orig()), api: { post: (...a) => post(...a), get: vi.fn() } }))
vi.mock('../notifications/NotificationsProvider', () => ({ useRealtime: () => rt }))
import IncomingCall from './IncomingCall'

const Where = () => { const l = useLocation(); return <p data-testid="where">{l.pathname + l.search}</p> }
const mount = () => render(
  <QueryClientProvider client={new QueryClient()}><ToastProvider><MemoryRouter initialEntries={['/']}><Routes><Route path="*" element={<><IncomingCall /><Where /></>} /></Routes></MemoryRouter></ToastProvider></QueryClientProvider>,
)
beforeEach(() => { vi.clearAllMocks(); rt.incomingCall = null; window.AudioContext = undefined })

describe('IncomingCall', () => {
  it('shows nothing when nobody is calling', () => {
    mount(); expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  })
  it('announces who is calling and whether it is video or voice', () => {
    rt.incomingCall = { room_id: 'abc', from_id: 3, from_name: 'Mia Manager', video: true }
    const { unmount } = mount()
    expect(screen.getByRole('alertdialog')).toHaveAccessibleName('Mia Manager'); expect(screen.getByText('Incoming video call…')).toBeInTheDocument(); unmount()
    rt.incomingCall = { room_id: 'abc', from_id: 3, from_name: 'Mia Manager', video: false }
    mount(); expect(screen.getByText('Incoming voice call…')).toBeInTheDocument()
  })
  it('Accept opens the room (voice calls without the camera) and stops ringing', async () => {
    rt.incomingCall = { room_id: 'abc', from_id: 3, from_name: 'Mia', video: false }
    mount()
    expect(screen.getByRole('button', { name: 'Accept' })).toHaveFocus()
    await userEvent.click(screen.getByRole('button', { name: 'Accept' }))
    expect(dismissCall).toHaveBeenCalled(); expect(screen.getByTestId('where')).toHaveTextContent('/meetings/abc?audio=1')
  })
  it('a video call opens the room with the camera', async () => {
    rt.incomingCall = { room_id: 'xyz', from_id: 3, from_name: 'Mia', video: true }
    mount(); await userEvent.click(screen.getByRole('button', { name: 'Accept' }))
    expect(screen.getByTestId('where')).toHaveTextContent(/^\/meetings\/xyz$/)
  })
  it('Decline tells the server, and Escape declines too', async () => {
    post.mockResolvedValue({})
    rt.incomingCall = { room_id: 'abc', from_id: 3, from_name: 'Mia', video: true }
    mount()
    await userEvent.click(screen.getByRole('button', { name: 'Decline' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/meetings/abc/decline')); await waitFor(() => expect(dismissCall).toHaveBeenCalled())
    post.mockClear()
    await userEvent.keyboard('{Escape}'); await waitFor(() => expect(post).toHaveBeenCalledWith('/meetings/abc/decline'))
  })
})
