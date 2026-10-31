import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../../components/ui'
import { canAccess } from '../../lib/nav'

const get = vi.fn(), post = vi.fn()
const auth = { user: { id: 7, role: 'employee', full_name: 'Elena' }, role: 'employee' }
vi.mock('../auth/AuthContext', () => ({ useAuth: () => auth }))
vi.mock('../../lib/api', async (orig) => ({ ...(await orig()), api: { get: (...a) => get(...a), post: (...a) => post(...a), patch: vi.fn(), put: vi.fn(), del: vi.fn() } }))

import ResignationCard from '../auth/ResignationCard'
import LifecyclePage from './LifecyclePage'
import LifecycleTab, { describe as describeEvent } from './LifecycleTab'
import OrgChartPage from './OrgChartPage'

const wrap = (ui) => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ToastProvider><MemoryRouter>{ui}</MemoryRouter></ToastProvider></QueryClientProvider>)
const respond = (map) => get.mockImplementation(async (path) => { if (path in map) return map[path]; throw new Error(`unexpected GET ${path}`) })
beforeEach(() => { vi.clearAllMocks(); auth.user = { id: 7, role: 'employee', full_name: 'Elena' }; auth.role = 'employee' })

const hist = (over = {}) => ({ user: { id: 7, name: 'Elena', status: 'active' }, can_manage: true, exit_clearance: null,
  state: { probation_end_date: null, confirmation_date: null, last_working_date: null, resigned: false },
  items: [{ id: 2, kind: 'promoted', effective_date: '2026-03-01', from: { designation: 'Engineer', job_level: 'L3' }, to: { designation: 'Senior Engineer', job_level: 'L4' }, note: 'Great year', by: 'Hannah HR' },
    { id: 1, kind: 'joined', effective_date: '2024-01-01', from: null, to: null, note: null, by: 'Fiona' }], ...over })
const extras = { '/departments': { items: [{ id: 1, name: 'Engineering' }, { id: 2, name: 'Sales' }] }, '/employees/directory': { items: [{ id: 3, full_name: 'Marcus', role: 'manager' }, { id: 7, full_name: 'Elena', role: 'employee' }] } }

describe('describe()', () => {
  it('turns stored before/after values into one line', () => {
    expect(describeEvent({ kind: 'promoted', from: { designation: 'Engineer', job_level: 'L3' }, to: { designation: 'Senior', job_level: 'L4' } })).toBe('Engineer (L3) → Senior (L4)')
    expect(describeEvent({ kind: 'department_changed', from: { name: 'Eng' }, to: { name: 'Sales' } })).toBe('Eng → Sales')
    expect(describeEvent({ kind: 'manager_changed', from: null, to: { name: 'Marcus' } })).toBe('none → Marcus')
    expect(describeEvent({ kind: 'suspended', to: { until: null } })).toBe('no end date')
    expect(describeEvent({ kind: 'resignation_submitted', to: { last_working_date: '2026-12-01', shorter_than_notice: true } })).toMatch(/shorter than the notice period/)
    expect(describeEvent({ kind: 'role_changed', from: { role: 'employee' }, to: { role: 'manager' } })).toBe('employee → manager')
  })
})

describe('LifecycleTab', () => {
  it('shows the history newest first with who did it and the note', async () => {
    respond({ '/employees/7/lifecycle': hist(), ...extras })
    wrap(<LifecycleTab id="7" user={{ id: 7, status: 'active', designation: 'Engineer' }} />)
    const list = within(await screen.findByRole('list', { name: 'Employment history' }))
    const rows = list.getAllByRole('listitem')
    expect(rows[0]).toHaveTextContent('Promotion')
    expect(rows[0]).toHaveTextContent('Engineer (L3) → Senior Engineer (L4)')
    expect(rows[0]).toHaveTextContent('Great year')
    expect(rows[0]).toHaveTextContent('by Hannah HR')
    expect(rows[1]).toHaveTextContent('Joined')
  })

  it('offers no actions to someone who cannot manage the person', async () => {
    respond({ '/employees/7/lifecycle': hist({ can_manage: false }), ...extras })
    wrap(<LifecycleTab id="7" user={{ id: 7, status: 'active' }} />)
    await screen.findByRole('list', { name: 'Employment history' })
    expect(screen.queryByRole('button', { name: 'Promote' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Suspend' })).not.toBeInTheDocument()
  })

  it('offers actions that fit the person\'s state', async () => {
    respond({ '/employees/7/lifecycle': hist({ user: { id: 7, status: 'suspended' } }), ...extras })
    const { unmount } = wrap(<LifecycleTab id="7" user={{ id: 7, status: 'suspended' }} />)
    expect(await screen.findByRole('button', { name: 'Reinstate' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Suspend' })).not.toBeInTheDocument()
    unmount()
    respond({ '/employees/7/lifecycle': hist({ exit_clearance: { done: 2, total: 5, cleared: false } }), ...extras })
    const second = wrap(<LifecycleTab id="7" user={{ id: 7, status: 'offboarded' }} />)
    expect(await screen.findByRole('button', { name: 'Bring back' })).toBeInTheDocument()
    expect(screen.getByText(/Exit clearance: 2 of 5 items done/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Promote' })).not.toBeInTheDocument()
    second.unmount()
    respond({ '/employees/7/lifecycle': hist({ state: { probation_end_date: '2026-06-01', confirmation_date: null, last_working_date: null, resigned: true } }), ...extras })
    wrap(<LifecycleTab id="7" user={{ id: 7, status: 'active' }} />)
    expect(await screen.findByRole('button', { name: 'Extend probation' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Withdraw resignation' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Record resignation' })).not.toBeInTheDocument()
  })

  it('records a promotion and a transfer with only what was filled in', async () => {
    respond({ '/employees/7/lifecycle': hist(), ...extras })
    post.mockResolvedValue({})
    wrap(<LifecycleTab id="7" user={{ id: 7, status: 'active', designation: 'Engineer' }} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Promote' }))
    let dlg = within(await screen.findByRole('dialog'))
    await userEvent.clear(dlg.getByLabelText('New title'))
    await userEvent.type(dlg.getByLabelText('New title'), 'Staff Engineer')
    await userEvent.click(dlg.getByRole('button', { name: 'Record' }))
    expect(post).toHaveBeenCalledWith('/employees/7/lifecycle/promotion', expect.objectContaining({ designation: 'Staff Engineer', job_level: null }))
    await userEvent.click(await screen.findByRole('button', { name: 'Transfer' }))
    dlg = within(await screen.findByRole('dialog'))
    await userEvent.selectOptions(dlg.getByLabelText('New department'), '2')
    await userEvent.selectOptions(dlg.getByLabelText('New reporting manager'), 'none')
    await userEvent.click(dlg.getByRole('button', { name: 'Move' }))
    expect(post).toHaveBeenLastCalledWith('/employees/7/lifecycle/transfer', expect.objectContaining({ department_id: 2, manager_id: null, clear_manager: true }))
  })

  it('needs a reason to suspend', async () => {
    respond({ '/employees/7/lifecycle': hist(), ...extras })
    post.mockResolvedValue({})
    wrap(<LifecycleTab id="7" user={{ id: 7, status: 'active' }} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Suspend' }))
    const dlg = within(await screen.findByRole('dialog'))
    expect(dlg.getByText(/signed out immediately/i)).toBeInTheDocument()
    expect(dlg.getByRole('button', { name: 'Suspend' })).toBeDisabled()
    await userEvent.type(dlg.getByLabelText(/^reason/i), 'Pending an investigation')
    await userEvent.click(dlg.getByRole('button', { name: 'Suspend' }))
    expect(post).toHaveBeenCalledWith('/employees/7/lifecycle/suspend', { reason: 'Pending an investigation', until: null })
  })
})

describe('ResignationCard', () => {
  it('lets a person submit their resignation with a last working day', async () => {
    respond({ '/employees/7/lifecycle': hist({ can_manage: false }) })
    post.mockResolvedValue({})
    wrap(<ResignationCard />)
    await userEvent.click(await screen.findByRole('button', { name: 'Submit resignation' }))
    const dlg = within(await screen.findByRole('dialog'))
    const go = dlg.getByRole('button', { name: 'Submit resignation' })
    expect(go).toBeDisabled()
    await userEvent.type(dlg.getByLabelText(/last working day/i), '2999-01-31')
    await userEvent.click(go)
    expect(post).toHaveBeenCalledWith('/employees/7/lifecycle/resignation', { last_working_date: '2999-01-31', reason: null })
  })

  it('shows the open resignation and lets the person withdraw it', async () => {
    respond({ '/employees/7/lifecycle': hist({ state: { probation_end_date: null, confirmation_date: null, last_working_date: '2999-01-31', resigned: true } }) })
    post.mockResolvedValue({})
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    wrap(<ResignationCard />)
    expect(await screen.findByText(/Your resignation is on record/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Withdraw resignation' }))
    expect(post).toHaveBeenCalledWith('/employees/7/lifecycle/resignation/withdraw', {})
  })

  it('is not shown to founders or the board', async () => {
    auth.role = 'founder'
    respond({ '/employees/7/lifecycle': hist() })
    wrap(<ResignationCard />)
    await new Promise((r) => setTimeout(r, 30))
    expect(screen.queryByText('Resignation')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Submit resignation' })).not.toBeInTheDocument()
  })
})

describe('LifecyclePage (HR worklist)', () => {
  it('lists probations, departures and open exit clearance and flags overdue ones', async () => {
    auth.role = 'hr'
    respond({ '/lifecycle/due': { days: 30, probation: [{ user_id: 1, name: 'Pat Probation', date: '2026-01-02', overdue: true }], leaving: [{ user_id: 2, name: 'Lee Leaving', date: '2999-02-01', overdue: false }],
      exit_clearance: [{ user_id: 3, name: 'Gone Person', done: 2, total: 5, date: '2026-01-01' }] } })
    wrap(<LifecyclePage />)
    const probation = within(await screen.findByRole('table', { name: 'Probations' }))
    expect(probation.getByText('Pat Probation')).toHaveAttribute('href', '/employees/1')
    expect(probation.getByText('overdue')).toBeInTheDocument()
    expect(within(screen.getByRole('table', { name: 'Departures' })).getByText('Lee Leaving')).toBeInTheDocument()
    expect(within(screen.getByRole('table', { name: 'Exit clearance' })).getByText('2 of 5')).toBeInTheDocument()
  })

  it('shows the activity feed with readable details', async () => {
    auth.role = 'hr'
    respond({ '/lifecycle/due': { days: 30, probation: [], leaving: [], exit_clearance: [] },
      '/lifecycle/events': { items: [{ id: 1, user_id: 5, employee: 'Ravi', kind: 'department_changed', effective_date: '2026-04-01', from: { name: 'Eng' }, to: { name: 'Sales' }, by: 'Hannah' }], page: 1, page_size: 20, total: 1 } })
    wrap(<LifecyclePage />)
    await userEvent.click(await screen.findByRole('tab', { name: 'Activity' }))
    const row = await screen.findByRole('row', { name: /Ravi/ })
    expect(row).toHaveTextContent('Eng → Sales')
    expect(row).toHaveTextContent('Hannah')
  })
})

describe('OrgChartPage', () => {
  const chart = { total: 4, roots: [{ id: 1, name: 'Fiona Founder', designation: 'Founder', role: 'founder', department: null, branch: null, reports: 3, children: [
    { id: 2, name: 'Marcus Manager', can_open: true, designation: 'Manager', role: 'manager', department: 'Engineering', branch: null, reports: 1, children: [{ id: 3, name: 'Elena Engineer', designation: 'Engineer', role: 'employee', department: 'Engineering', branch: null, reports: 0, children: [] }] },
    { id: 4, name: 'Hannah HR', designation: 'HR', role: 'hr', department: null, branch: null, reports: 0, children: [] }] }] }
  const base = { '/org/chart': chart, '/departments': { items: [] }, '/branches': { items: [] } }

  it('renders the tree and collapses a manager\'s team', async () => {
    respond(base)
    wrap(<OrgChartPage />)
    const tree = within(await screen.findByRole('tree', { name: 'Organisation chart' }))
    expect(tree.getByText('Elena Engineer')).toBeInTheDocument()
    expect(tree.getByText(/3 in team/)).toBeInTheDocument()
    await userEvent.click(tree.getByRole('button', { name: 'Collapse Marcus Manager' }))
    expect(tree.queryByText('Elena Engineer')).not.toBeInTheDocument()
    await userEvent.click(tree.getByRole('button', { name: 'Expand Marcus Manager' }))
    expect(tree.getByText('Elena Engineer')).toBeInTheDocument()
    expect(tree.getByText('Marcus Manager')).toHaveAttribute('href', '/employees/2')
  })

  it('links every person; the profile page decides between the full record and the colleague card', async () => {
    respond(base)
    wrap(<OrgChartPage />)
    const tree = within(await screen.findByRole('tree', { name: 'Organisation chart' }))
    for (const [name, id] of [['Fiona Founder', 1], ['Marcus Manager', 2], ['Elena Engineer', 3], ['Hannah HR', 4]]) {
      expect(tree.getByText(name)).toHaveAttribute('href', `/employees/${id}`)
    }
  })

  it('asks the server for the chosen department', async () => {
    respond({ ...base, '/departments': { items: [{ id: 5, name: 'Sales' }] } })
    wrap(<OrgChartPage />)
    await screen.findByRole('tree')
    await userEvent.selectOptions(screen.getByLabelText('Department'), '5')
    await screen.findByRole('tree')
    expect(get).toHaveBeenCalledWith('/org/chart', { branch_id: undefined, department_id: '5' })
  })
})

describe('navigation', () => {
  it('limits the HR worklist to HR and founders, and the org chart to everyone but the board', () => {
    expect(canAccess('hr', '/lifecycle')).toBe(true)
    expect(canAccess('founder', '/lifecycle')).toBe(true)
    for (const r of ['manager', 'employee', 'board_member']) expect(canAccess(r, '/lifecycle')).toBe(false)
    for (const r of ['employee', 'manager', 'hr', 'founder']) expect(canAccess(r, '/org-chart')).toBe(true)
    expect(canAccess('board_member', '/org-chart')).toBe(false)
  })
})
