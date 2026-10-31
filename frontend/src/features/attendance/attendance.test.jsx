import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../../components/ui'
import { canAccess } from '../../lib/nav'

const get = vi.fn(), post = vi.fn(), del = vi.fn()
vi.mock('../../lib/api', async (orig) => ({ ...(await orig()), api: { get: (...a) => get(...a), post: (...a) => post(...a), del: (...a) => del(...a), patch: vi.fn(), put: vi.fn() } }))

import AttendancePage from './AttendancePage'
import CorrectionsQueuePage from './CorrectionsQueuePage'
import { hm, statusInfo } from './labels'

const wrap = (ui) => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <ToastProvider><MemoryRouter>{ui}</MemoryRouter></ToastProvider>
  </QueryClientProvider>,
)

const today = (over = {}) => ({ record: null, timezone: 'Asia/Kolkata', allow_wfh: true, geofence_required: false, shift: null, ...over })
const respond = (map) => get.mockImplementation(async (path) => {
  if (path in map) return map[path]
  throw new Error(`unexpected GET ${path}`)
})

beforeEach(() => { vi.clearAllMocks(); delete navigator.geolocation })

describe('labels', () => {
  it('formats minutes and day statuses', () => {
    expect([hm(0), hm(45), hm(60), hm(125)]).toEqual(['0 min', '45 min', '1 h', '2 h 5 min'])
    expect(statusInfo('half_day')).toEqual(['Half day', 'amber'])
    expect(statusInfo('mystery')).toEqual(['mystery', 'gray'])
  })
})

describe('AttendancePage', () => {
  const base = { '/attendance/today': today(), '/attendance/mine': { items: [], page: 1, page_size: 10, total: 0 }, '/attendance/corrections/mine': { items: [], total: 0 } }

  it('checks in from the office by default and from home when chosen', async () => {
    respond(base)
    post.mockResolvedValue({})
    wrap(<AttendancePage />)
    await userEvent.click(await screen.findByRole('button', { name: 'Check in' }))
    expect(post).toHaveBeenLastCalledWith('/attendance/check-in', { work_mode: 'office' })
    await userEvent.selectOptions(screen.getByLabelText(/working from/i), 'wfh')
    await userEvent.click(screen.getByRole('button', { name: 'Check in' }))
    expect(post).toHaveBeenLastCalledWith('/attendance/check-in', { work_mode: 'wfh' })
    expect(screen.getByText(/Asia\/Kolkata/)).toBeInTheDocument()
  })

  it('hides the work-from-home choice when the company has switched it off', async () => {
    respond({ ...base, '/attendance/today': today({ allow_wfh: false }) })
    wrap(<AttendancePage />)
    await screen.findByRole('button', { name: 'Check in' })
    expect(screen.queryByLabelText(/working from/i)).not.toBeInTheDocument()
  })

  it('sends coordinates when the branch enforces a geo-fence, and explains a denied permission', async () => {
    respond({ ...base, '/attendance/today': today({ geofence_required: true }) })
    post.mockResolvedValue({})
    navigator.geolocation = { getCurrentPosition: (ok) => ok({ coords: { latitude: 22.5, longitude: 88.3 } }) }
    wrap(<AttendancePage />)
    await userEvent.click(await screen.findByRole('button', { name: 'Check in' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/attendance/check-in', { work_mode: 'office', lat: 22.5, lng: 88.3 }))

    post.mockClear()
    navigator.geolocation = { getCurrentPosition: (_ok, fail) => fail({ code: 1 }) }
    await userEvent.click(screen.getByRole('button', { name: 'Check in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/location access was denied/i)
    expect(post).not.toHaveBeenCalled() // never checks in without the location the branch requires
  })

  it('does not ask for a location when working from home', async () => {
    respond({ ...base, '/attendance/today': today({ geofence_required: true }) })
    post.mockResolvedValue({})
    const spy = vi.fn()
    navigator.geolocation = { getCurrentPosition: spy }
    wrap(<AttendancePage />)
    await userEvent.selectOptions(await screen.findByLabelText(/working from/i), 'wfh')
    await userEvent.click(screen.getByRole('button', { name: 'Check in' }))
    expect(spy).not.toHaveBeenCalled()
    expect(post).toHaveBeenCalledWith('/attendance/check-in', { work_mode: 'wfh' })
  })

  it('shows lateness and the shift for an open session', async () => {
    const rec = { id: 1, check_in: '2026-01-05T04:00:00Z', check_out: null, breaks: [], on_break: false, worked_hours: 0, break_minutes: 0, overtime_hours: 0, late_minutes: 25, early_minutes: 0, work_mode: 'office' }
    respond({ ...base, '/attendance/today': today({ record: rec, shift: { id: 2, name: 'General', start: '09:00:00', end: '18:00:00', grace_minutes: 10, required_hours: 8 } }) })
    wrap(<AttendancePage />)
    expect(await screen.findByText('Late 25 min')).toBeInTheDocument()
    expect(screen.getByText(/Shift: General \(09:00–18:00, 10 min grace\)/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Check out' })).toBeInTheDocument()
  })

  it('submits a correction request with the typed local times', async () => {
    respond(base)
    post.mockResolvedValue({})
    wrap(<AttendancePage />)
    await userEvent.click(await screen.findByRole('button', { name: 'Request a correction' }))
    const dlg = within(await screen.findByRole('dialog'))
    const send = dlg.getByRole('button', { name: 'Send request' })
    expect(send).toBeDisabled()
    // datetime-local inputs take a whole value at once; typing character by character is timing-dependent in jsdom
    fireEvent.change(dlg.getByLabelText(/check-in/i), { target: { value: '2026-03-09T09:00' } })
    fireEvent.change(dlg.getByLabelText(/check-out/i), { target: { value: '2026-03-09T18:00' } })
    await userEvent.type(dlg.getByLabelText(/reason/i), 'Forgot to check out')
    await userEvent.click(send)
    expect(post).toHaveBeenCalledWith('/attendance/corrections', { check_in: '2026-03-09T09:00', check_out: '2026-03-09T18:00', reason: 'Forgot to check out' })
  })

  it('lets a pending request be cancelled', async () => {
    respond({ ...base, '/attendance/corrections/mine': { items: [{ id: 7, work_date: '2026-03-09', check_in: '2026-03-09T03:30:00Z', check_out: '2026-03-09T12:30:00Z', status: 'pending', decision_note: null }], total: 1 } })
    del.mockResolvedValue(null)
    wrap(<AttendancePage />)
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel' }))
    await userEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Cancel request' }))
    expect(del).toHaveBeenCalledWith('/attendance/corrections/7')
  })
})

describe('CorrectionsQueuePage', () => {
  const item = { id: 3, user_name: 'Asha Rao', work_date: '2026-03-09', check_in: '2026-03-09T03:30:00Z', check_out: '2026-03-09T12:30:00Z', reason: 'Forgot to check out', status: 'pending', created_at: '2026-03-10T05:00:00Z' }

  it('approves with an optional note', async () => {
    respond({ '/attendance/corrections': { items: [item], page: 1, page_size: 15, total: 1 } })
    post.mockResolvedValue({})
    wrap(<CorrectionsQueuePage />)
    await userEvent.click(await screen.findByRole('button', { name: 'Approve' }))
    await userEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Approve' }))
    expect(post).toHaveBeenCalledWith('/attendance/corrections/3/decision', { approve: true, note: null })
  })

  it('will not reject without a reason', async () => {
    respond({ '/attendance/corrections': { items: [item], page: 1, page_size: 15, total: 1 } })
    post.mockResolvedValue({})
    wrap(<CorrectionsQueuePage />)
    await userEvent.click(await screen.findByRole('button', { name: 'Reject' }))
    const dlg = within(await screen.findByRole('dialog'))
    expect(dlg.getByRole('button', { name: 'Reject' })).toBeDisabled()
    await userEvent.type(dlg.getByLabelText(/reason for rejecting/i), 'Not what the badge log says')
    await userEvent.click(dlg.getByRole('button', { name: 'Reject' }))
    expect(post).toHaveBeenCalledWith('/attendance/corrections/3/decision', { approve: false, note: 'Not what the badge log says' })
  })

  it('shows an empty state', async () => {
    respond({ '/attendance/corrections': { items: [], page: 1, page_size: 15, total: 0 } })
    wrap(<CorrectionsQueuePage />)
    expect(await screen.findByText('Nothing to review')).toBeInTheDocument()
  })
})

describe('navigation', () => {
  it('limits the new pages to the roles the server allows', () => {
    expect(canAccess('employee', '/attendance/corrections')).toBe(false)
    expect(canAccess('manager', '/attendance/corrections')).toBe(true)
    expect(canAccess('manager', '/attendance/setup')).toBe(false)
    expect(canAccess('hr', '/attendance/setup')).toBe(true)
    expect(canAccess('employee', '/attendance')).toBe(true)
  })
})
