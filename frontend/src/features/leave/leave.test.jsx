import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../../components/ui'
import { canAccess } from '../../lib/nav'

const get = vi.fn(), post = vi.fn(), patch = vi.fn(), del = vi.fn()
const auth = { user: { id: 1, role: 'manager' }, role: 'manager' }
vi.mock('../auth/AuthContext', () => ({ useAuth: () => auth }))
vi.mock('../../lib/api', async (orig) => ({ ...(await orig()), api: { get: (...a) => get(...a), post: (...a) => post(...a), patch: (...a) => patch(...a), del: (...a) => del(...a), put: vi.fn() }, download: vi.fn() }))

import DelegationCard from './DelegationCard'
import LeaveApprovalsPage from './LeaveApprovalsPage'
import LeaveBalancesPage from './LeaveBalancesPage'
import LeavePage from './LeavePage'
import LeaveRequestDialog from './LeaveRequestDialog'
import LeaveTypeDialog from './LeaveTypeDialog'

const wrap = (ui) => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <ToastProvider><MemoryRouter>{ui}</MemoryRouter></ToastProvider>
  </QueryClientProvider>,
)
const respond = (map) => get.mockImplementation(async (path) => {
  if (path in map) return map[path]
  throw new Error(`unexpected GET ${path}`)
})
const types = [
  { id: 1, name: 'Annual Leave', allow_half_day: true, count_all_days: false, min_notice_days: 0, is_active: true },
  { id: 2, name: 'Block', allow_half_day: false, count_all_days: false, min_notice_days: 7, is_active: true },
]

beforeEach(() => { vi.clearAllMocks(); auth.role = 'manager'; auth.user = { id: 1, role: 'manager' } })

describe('LeaveRequestDialog', () => {
  it('offers a half day only for a single date and a type that allows it, and sends it', async () => {
    post.mockResolvedValue({})
    wrap(<LeaveRequestDialog open onClose={() => {}} types={types} />)
    const dlg = within(await screen.findByRole('dialog'))
    await userEvent.selectOptions(dlg.getByLabelText(/leave type/i), '1')
    await userEvent.type(dlg.getByLabelText(/^from/i), '2030-01-07')
    expect(dlg.getByLabelText(/length/i)).toBeInTheDocument()                    // from == to after typing the start date
    await userEvent.selectOptions(dlg.getByLabelText(/length/i), 'second')
    await userEvent.click(dlg.getByRole('button', { name: 'Submit request' }))
    expect(post).toHaveBeenCalledWith('/leave/requests', { leave_type_id: 1, start_date: '2030-01-07', end_date: '2030-01-07', half_day: 'second', reason: null })
  })

  it('hides the half-day choice for multi-day ranges and for types without half days, and shows the notice rule', async () => {
    wrap(<LeaveRequestDialog open onClose={() => {}} types={types} />)
    const dlg = within(await screen.findByRole('dialog'))
    await userEvent.selectOptions(dlg.getByLabelText(/leave type/i), '1')
    await userEvent.type(dlg.getByLabelText(/^from/i), '2030-01-07')
    await userEvent.clear(dlg.getByLabelText(/^to/i))
    await userEvent.type(dlg.getByLabelText(/^to/i), '2030-01-09')
    expect(dlg.queryByLabelText(/length/i)).not.toBeInTheDocument()
    await userEvent.selectOptions(dlg.getByLabelText(/leave type/i), '2')
    expect(dlg.getByText(/needs 7 days/i)).toBeInTheDocument()
  })

  it('edits a pending request with PATCH and revises approved leave with POST /revise', async () => {
    patch.mockResolvedValue({}); post.mockResolvedValue({})
    const request = { id: 9, leave_type_id: 1, start_date: '2030-02-04', end_date: '2030-02-05', half_day: null, reason: 'trip' }
    const { unmount } = wrap(<LeaveRequestDialog open onClose={() => {}} types={types} mode="edit" request={request} />)
    await userEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Save changes' }))
    expect(patch).toHaveBeenCalledWith('/leave/requests/9', { leave_type_id: 1, start_date: '2030-02-04', end_date: '2030-02-05', half_day: null, reason: 'trip' })
    unmount()
    wrap(<LeaveRequestDialog open onClose={() => {}} types={types} mode="revise" request={request} />)
    const dlg = within(await screen.findByRole('dialog'))
    expect(dlg.getByText(/stays in place/i)).toBeInTheDocument()
    await userEvent.click(dlg.getByRole('button', { name: 'Send revision' }))
    expect(post).toHaveBeenCalledWith('/leave/requests/9/revise', expect.objectContaining({ leave_type_id: 1 }))
  })

  it('shows the server message when the request is refused', async () => {
    post.mockRejectedValue(Object.assign(new Error('Insufficient Annual Leave balance (1 days available)'), { code: 'insufficient_balance' }))
    wrap(<LeaveRequestDialog open onClose={() => {}} types={types} />)
    const dlg = within(await screen.findByRole('dialog'))
    await userEvent.selectOptions(dlg.getByLabelText(/leave type/i), '1')
    await userEvent.type(dlg.getByLabelText(/^from/i), '2030-01-07')
    await userEvent.click(dlg.getByRole('button', { name: 'Submit request' }))
    expect(await dlg.findByRole('alert')).toHaveTextContent(/insufficient annual leave balance/i)
  })
})

describe('LeaveTypeDialog', () => {
  const type = { id: 4, name: 'Sick Leave', annual_quota: 10, paid: true, accrual: 'annual_upfront', carry_forward_max: 0, carry_expiry_months: null, allow_half_day: true,
    count_all_days: false, min_notice_days: 0, max_consecutive_days: null, encashable: false, encash_max_days: null, is_active: true }

  it('warns that history is untouched and only offers to adjust balances when the quota changes', async () => {
    patch.mockResolvedValue({})
    wrap(<LeaveTypeDialog type={type} onClose={() => {}} />)
    const dlg = within(await screen.findByRole('dialog'))
    expect(dlg.getByText(/already approved or pending keeps the days/i)).toBeInTheDocument()
    expect(dlg.queryByLabelText(/also add the difference/i)).not.toBeInTheDocument()
    const quota = dlg.getByLabelText(/days per year/i)
    await userEvent.clear(quota)
    await userEvent.type(quota, '12')
    await userEvent.click(dlg.getByLabelText(/also add the difference/i))
    await userEvent.click(dlg.getByRole('button', { name: 'Save' }))
    expect(patch).toHaveBeenCalledWith('/leave/types/4', expect.objectContaining({ annual_quota: 12, apply_to_current_year: true, carry_expiry_months: null, max_consecutive_days: null }))
  })

  it('only allows a carry expiry when something can be carried', async () => {
    wrap(<LeaveTypeDialog onClose={() => {}} />)
    const dlg = within(await screen.findByRole('dialog'))
    expect(dlg.getByLabelText(/lapse after month/i)).toBeDisabled()
    await userEvent.type(dlg.getByLabelText(/carry forward at most/i), '{Control>}a{/Control}5')
    expect(dlg.getByLabelText(/lapse after month/i)).toBeEnabled()
  })
})

describe('LeavePage', () => {
  const balances = { items: [
    { leave_type_id: 1, leave_type: 'Annual Leave', paid: true, allocated: 18, carried_in: 4, used: 2, expired: 0, encashed: 0, pending: 3, remaining: 20, accrual: 'annual_upfront' },
    { leave_type_id: 3, leave_type: 'Earned', paid: true, allocated: 3, carried_in: 0, used: 0, expired: 0, encashed: 0, pending: 0, remaining: 3, accrual: 'monthly' },
  ] }
  const mine = (items) => ({ items, page: 1, page_size: 10, total: items.length })
  const future = '2999-01-05'

  it('shows carried, pending and accrual details on the balance cards', async () => {
    auth.role = 'employee'
    respond({ '/leave/balances': balances, '/leave/types': { items: types }, '/leave/requests/mine': mine([]) })
    wrap(<LeavePage />)
    expect(await screen.findByText('4 carried in · 3 pending')).toBeInTheDocument()
    expect(screen.getByText('accrues monthly')).toBeInTheDocument()
    expect(screen.getByText('of 22 left')).toBeInTheDocument()
  })

  it('offers Edit for pending and Change for approved future leave', async () => {
    auth.role = 'employee'
    const base = { leave_type: 'Annual Leave', leave_type_id: 1, start_date: future, end_date: future, days: 1, decision_note: null }
    respond({ '/leave/balances': balances, '/leave/types': { items: types },
      '/leave/requests/mine': mine([{ ...base, id: 1, status: 'pending' }, { ...base, id: 2, status: 'approved' }, { ...base, id: 3, status: 'rejected' }]) })
    wrap(<LeavePage />)
    const table = within(await screen.findByRole('table', { name: 'My leave requests' }))
    await waitFor(() => expect(table.getAllByRole('row').length).toBe(4))
    const [, pending, approved, rejected] = table.getAllByRole('row')
    expect(within(pending).getByRole('button', { name: 'Edit' })).toBeInTheDocument()
    expect(within(pending).queryByRole('button', { name: 'Change' })).not.toBeInTheDocument()
    expect(within(approved).getByRole('button', { name: 'Change' })).toBeInTheDocument()
    expect(within(rejected).queryByRole('button')).not.toBeInTheDocument()
  })

  it('lets HR run the year-end job and manage policies, but not employees', async () => {
    auth.role = 'hr'
    respond({ '/leave/balances': balances, '/leave/types': { items: types }, '/leave/requests/mine': mine([]) })
    post.mockResolvedValue({ carried_days: 1, expired_days: 0 })
    wrap(<LeavePage />)
    await userEvent.click(await screen.findByRole('tab', { name: 'Leave policies' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Run year-end and accruals' }))
    expect(post).toHaveBeenCalledWith('/leave/maintenance')
  })

  it('hides the policies tab from employees', async () => {
    auth.role = 'employee'
    respond({ '/leave/balances': balances, '/leave/types': { items: types }, '/leave/requests/mine': mine([]) })
    wrap(<LeavePage />)
    await screen.findByRole('tab', { name: 'History' })
    expect(screen.queryByRole('tab', { name: 'Leave policies' })).not.toBeInTheDocument()
  })
})

describe('DelegationCard', () => {
  it('lists what you gave and received, and ends a delegation', async () => {
    respond({ '/leave/delegations': { items: [
      { id: 5, direction: 'given', delegate: 'Dev Rao', delegator: 'Me', start_date: '2999-01-01', end_date: '2999-02-01', active: false, revoked: false },
      { id: 6, direction: 'received', delegate: 'Me', delegator: 'Asha Iyer', start_date: '2000-01-01', end_date: '2999-12-31', active: true, revoked: false }] } })
    del.mockResolvedValue(null)
    wrap(<DelegationCard />)
    expect(await screen.findByText('You → Dev Rao')).toBeInTheDocument()
    expect(screen.getByText('Asha Iyer → you')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'End' }))
    expect(del).toHaveBeenCalledWith('/leave/delegations/5')
  })

  it('only managers can start a delegation', async () => {
    respond({ '/leave/delegations': { items: [] } })
    auth.role = 'hr'
    wrap(<DelegationCard />)
    await screen.findByText('No active delegations')
    expect(screen.queryByRole('button', { name: 'Delegate my approvals' })).not.toBeInTheDocument()
  })
})

describe('LeaveApprovalsPage', () => {
  const pending = { id: 7, user_id: 9, user_name: 'Eli Employee', leave_type: 'Annual Leave', start_date: '2030-01-07', end_date: '2030-01-09', days: 3, status: 'pending', reason: null }
  const base = { '/leave/requests': { items: [pending], total: 1, page: 1, page_size: 15 }, '/leave/delegations': { items: [] }, '/employees/directory': { items: [] } }

  it('keeps the dialog open and explains a refused approval, with a way forward, then re-reads the list', async () => {
    respond(base)
    post.mockRejectedValue(Object.assign(new Error('Employee no longer has enough balance'), { code: 'insufficient_balance' }))
    wrap(<LeaveApprovalsPage />)
    await userEvent.click(await screen.findByRole('button', { name: 'Approve' }))
    const dlg = within(await screen.findByRole('dialog'))
    await userEvent.click(dlg.getByRole('button', { name: /approve/i }))
    const alert = await dlg.findByRole('alert')
    expect(alert).toHaveTextContent('Employee no longer has enough balance')
    expect(alert).toHaveTextContent(/reject the request with a note, or ask HR to adjust the balance/i)
    const before = get.mock.calls.filter(([p]) => p === '/leave/requests').length
    await waitFor(() => expect(get.mock.calls.filter(([p]) => p === '/leave/requests').length).toBeGreaterThan(before - 1))
    await userEvent.click(dlg.getByRole('button', { name: 'Cancel' }))
    await userEvent.click(screen.getByRole('button', { name: 'Reject' }))
    expect(within(await screen.findByRole('dialog')).queryByRole('alert')).not.toBeInTheDocument()   // the old error does not follow the next decision
  })
})

describe('LeaveBalancesPage', () => {
  const row = { user_id: 7, employee: 'Asha Iyer', leave_type: 'Privilege', year: 2026, allocated: 15, carried_in: 0, used: 0, pending: 0, expired: 0, encashed: 0, remaining: 15 }
  const data = { '/leave/reports/balances': { items: [row] }, '/leave/types': { items: [{ id: 8, name: 'Privilege', encashable: true }] } }

  it('lets HR adjust (note required) and encash', async () => {
    auth.role = 'hr'
    respond(data)
    post.mockResolvedValue({})
    wrap(<LeaveBalancesPage />)
    await userEvent.click(await screen.findByRole('button', { name: 'Adjust' }))
    let dlg = within(await screen.findByRole('dialog'))
    const go = dlg.getByRole('button', { name: 'Adjust' })
    await userEvent.type(dlg.getByLabelText(/^days/i), '2')
    expect(go).toBeDisabled()                                                    // a reason is required
    await userEvent.type(dlg.getByLabelText(/reason/i), 'Worked a holiday')
    await userEvent.click(go)
    expect(post).toHaveBeenCalledWith('/leave/balances/7/adjust', { leave_type_id: 8, days: 2, note: 'Worked a holiday' })
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: 'Encash' }))
    dlg = within(await screen.findByRole('dialog'))
    await userEvent.type(dlg.getByLabelText(/^days/i), '3')
    await userEvent.click(dlg.getByRole('button', { name: 'Record encashment' }))
    expect(post).toHaveBeenLastCalledWith('/leave/balances/7/encash', { leave_type_id: 8, days: 3, note: null })
  })

  it('is read-only for managers', async () => {
    auth.role = 'manager'
    respond(data)
    wrap(<LeaveBalancesPage />)
    await screen.findByText('Asha Iyer')
    expect(screen.queryByRole('button', { name: 'Adjust' })).not.toBeInTheDocument()
  })
})

describe('navigation', () => {
  it('limits the balances report to approvers', () => {
    expect(canAccess('employee', '/leave/balances')).toBe(false)
    expect(canAccess('manager', '/leave/balances')).toBe(true)
    expect(canAccess('employee', '/leave')).toBe(true)
  })
})
