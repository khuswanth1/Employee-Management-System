import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../../components/ui'
import { canAccess } from '../../lib/nav'

const get = vi.fn(), post = vi.fn(), put = vi.fn(), del = vi.fn()
const auth = { user: { id: 5, role: 'employee', full_name: 'Elena' }, role: 'employee' }
vi.mock('../auth/AuthContext', () => ({ useAuth: () => auth }))
vi.mock('../../lib/api', async (orig) => ({ ...(await orig()), api: { get: (...a) => get(...a), post: (...a) => post(...a), put: (...a) => put(...a), del: (...a) => del(...a), patch: vi.fn() }, download: vi.fn() }))

import GoalsCard from './GoalsCard'
import PerformancePage from './PerformancePage'
import ReviewDialog from './ReviewDialog'

const scale = { id: 1, name: 'Standard', levels: [1, 2, 3, 4, 5].map((v) => ({ value: v, label: `L${v}`, description: null })) }
const cycle = { id: 1, name: '2026 review', status: 'active', scale, competencies: ['Quality'], start_date: '2026-01-01', end_date: '2026-12-31', self_review_due: null, manager_review_due: null, review_counts: { pending_self: 2 } }
const wrap = (ui) => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ToastProvider><MemoryRouter>{ui}</MemoryRouter></ToastProvider></QueryClientProvider>)
const respond = (map) => get.mockImplementation(async (path) => { if (path in map) return map[path]; throw new Error(`unexpected GET ${path}`) })

const review = (over = {}) => ({ id: 9, cycle_id: 1, cycle: '2026 review', cycle_status: 'active', user_id: 5, employee: 'Elena Engineer', reviewer_id: 2, reviewer: 'Marcus', status: 'pending_self',
  self_rating: null, self_comments: null, self_submitted_at: null, self_competencies: {}, self_goals: {}, manager_rating: null, manager_comments: null, strengths: null, development_areas: null,
  manager_competencies: {}, manager_goals: {}, goal_score: null, acknowledged_at: null, employee_response: null, hidden_until_shared: true, competencies: ['Quality'], scale,
  goals: [{ id: 3, title: 'Ship it', weight: 100, progress: 50 }], can_review: false, ...over })

beforeEach(() => { vi.clearAllMocks(); auth.user = { id: 5, role: 'employee', full_name: 'Elena' }; auth.role = 'employee' })

describe('ReviewDialog', () => {
  it('lets the person write and submit their self review (saving first)', async () => {
    respond({ '/performance/reviews/9': review(), '/auth/me': { id: 5 } })
    put.mockResolvedValue({}); post.mockResolvedValue({})
    wrap(<ReviewDialog id={9} onClose={() => {}} />)
    const dlg = within(await screen.findByRole('dialog'))
    await userEvent.selectOptions(await dlg.findByLabelText('Overall self rating'), '4')
    await userEvent.selectOptions(dlg.getByLabelText('Self rating for Quality'), '5')
    await userEvent.selectOptions(dlg.getByLabelText('Self rating for goal Ship it'), '3')
    await userEvent.type(dlg.getByLabelText(/how did the cycle go/i), 'Delivered the portal')
    await userEvent.click(dlg.getByRole('button', { name: 'Submit self review' }))
    expect(put).toHaveBeenCalledWith('/performance/reviews/9/self', { rating: 4, comments: 'Delivered the portal', competencies: { Quality: 5 }, goals: { 3: 3 } })
    expect(post).toHaveBeenCalledWith('/performance/reviews/9/self/submit')
    expect(dlg.getByRole('button', { name: 'Save draft' })).toBeInTheDocument()
  })

  it('shows nothing of the manager review to the employee before it is shared', async () => {
    respond({ '/performance/reviews/9': review({ status: 'pending_manager', self_submitted_at: '2026-02-01T00:00:00Z', self_rating: 4, self_comments: 'Good year' }), '/auth/me': { id: 5 } })
    wrap(<ReviewDialog id={9} onClose={() => {}} />)
    const dlg = within(await screen.findByRole('dialog'))
    expect(await dlg.findByText('Good year')).toBeInTheDocument()
    expect(dlg.getByText(/assessment stays private/i)).toBeInTheDocument()
    expect(dlg.getByText('Not shared yet.')).toBeInTheDocument()
    expect(dlg.queryByRole('button', { name: 'Acknowledge' })).not.toBeInTheDocument()
  })

  it('lets the reviewer write the manager part and warns it is hidden until submitted', async () => {
    auth.user = { id: 2, role: 'manager' }; auth.role = 'manager'
    respond({ '/performance/reviews/9': review({ status: 'pending_manager', can_review: true, self_submitted_at: '2026-02-01T00:00:00Z', self_rating: 4, self_comments: 'Good year' }), '/auth/me': { id: 2 } })
    put.mockResolvedValue({}); post.mockResolvedValue({})
    wrap(<ReviewDialog id={9} onClose={() => {}} />)
    const dlg = within(await screen.findByRole('dialog'))
    expect(await dlg.findByText(/cannot see your rating or comments until you submit/i)).toBeInTheDocument()
    expect(dlg.getByText('Good year')).toBeInTheDocument()                                                  // the submitted self review is visible to the reviewer
    await userEvent.selectOptions(dlg.getByLabelText('Overall manager rating'), '3')
    await userEvent.selectOptions(dlg.getByLabelText('Manager rating for Quality'), '3')
    await userEvent.type(dlg.getByLabelText(/^assessment/i), 'Solid delivery.')
    await userEvent.click(dlg.getByRole('button', { name: 'Submit review' }))
    expect(put).toHaveBeenCalledWith('/performance/reviews/9/manager', expect.objectContaining({ rating: 3, comments: 'Solid delivery.', competencies: { Quality: 3 } }))
    expect(post).toHaveBeenCalledWith('/performance/reviews/9/manager/submit')
  })

  it('shows the shared review and lets the person acknowledge it with a response', async () => {
    respond({ '/performance/reviews/9': review({ status: 'completed', self_submitted_at: '2026-02-01T00:00:00Z', self_rating: 4, self_comments: 'Good year', manager_rating: 3, manager_comments: 'Solid delivery.', strengths: 'Reliable', goal_score: 3.5, hidden_until_shared: false }), '/auth/me': { id: 5 } })
    post.mockResolvedValue({})
    wrap(<ReviewDialog id={9} onClose={() => {}} />)
    const dlg = within(await screen.findByRole('dialog'))
    expect(await dlg.findByText('Solid delivery.')).toBeInTheDocument()
    expect(dlg.getByText('3 · L3')).toBeInTheDocument()
    expect(dlg.getByText('3.5')).toBeInTheDocument()
    await userEvent.type(dlg.getByLabelText(/your response/i), 'Thanks')
    await userEvent.click(dlg.getByRole('button', { name: 'Acknowledge' }))
    expect(post).toHaveBeenCalledWith('/performance/reviews/9/acknowledge', { response: 'Thanks' })
  })
})

describe('GoalsCard', () => {
  const goals = { user: { id: 5 }, total_weight: 80, items: [
    { id: 1, title: 'Proposed goal', weight: 30, status: 'proposed', kind: 'goal', progress: 0, due_date: null, description: null },
    { id: 2, title: 'Close tickets', weight: 50, status: 'agreed', kind: 'kpi', progress: 25, current_value: 10, target_value: 40, unit: 'tickets', due_date: null, description: null },
    { id: 3, title: 'Dropped', weight: 20, status: 'cancelled', kind: 'goal', progress: 0, due_date: null, description: null }] }

  it('only the manager sees Agree; cancelled goals are hidden; weight used is shown', async () => {
    respond({ '/performance/goals': goals, '/performance/goals/2/updates': { items: [] } })
    const { unmount } = wrap(<GoalsCard cycle={cycle} userId={5} />)
    expect(await screen.findByText('Proposed goal')).toBeInTheDocument()
    expect(screen.queryByText('Dropped')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Agree' })).not.toBeInTheDocument()
    expect(screen.getByText(/Weights used: 80%/)).toBeInTheDocument()
    unmount()
    post.mockResolvedValue({})
    wrap(<GoalsCard cycle={cycle} userId={5} manage />)
    await userEvent.click(await screen.findByRole('button', { name: 'Agree' }))
    expect(post).toHaveBeenCalledWith('/performance/goals/1/agree')
  })

  it('records a KPI check-in as a current value, and offers nothing once the cycle is closed', async () => {
    respond({ '/performance/goals': goals, '/performance/goals/2/updates': { items: [] } })
    post.mockResolvedValue({})
    const { unmount } = wrap(<GoalsCard cycle={cycle} userId={5} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Update progress' }))
    const dlg = within(await screen.findByRole('dialog'))
    const input = dlg.getByLabelText(/current value/i)
    await userEvent.clear(input)
    await userEvent.type(input, '24')
    await userEvent.click(dlg.getByRole('button', { name: 'Save' }))
    expect(post).toHaveBeenCalledWith('/performance/goals/2/updates', { current_value: 24, comment: null })
    unmount()
    wrap(<GoalsCard cycle={{ ...cycle, status: 'closed' }} userId={5} />)
    await screen.findByText('Close tickets')
    expect(screen.queryByRole('button', { name: 'Add goal' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Update progress' })).not.toBeInTheDocument()
  })

  it('adds a KPI with its target', async () => {
    respond({ '/performance/goals': { user: { id: 5 }, total_weight: 0, items: [] } })
    post.mockResolvedValue({})
    wrap(<GoalsCard cycle={cycle} userId={5} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Add goal' }))
    const dlg = within(await screen.findByRole('dialog'))
    await userEvent.type(dlg.getByLabelText(/^title/i), 'Reduce bugs')
    await userEvent.selectOptions(dlg.getByLabelText('Type'), 'kpi')
    expect(dlg.getByRole('button', { name: 'Add' })).toBeDisabled()                                        // a KPI needs a target
    await userEvent.type(dlg.getByLabelText(/^target/i), '12')
    await userEvent.click(dlg.getByRole('button', { name: 'Add' }))
    expect(post).toHaveBeenCalledWith('/performance/goals', expect.objectContaining({ cycle_id: 1, title: 'Reduce bugs', kind: 'kpi', target_value: 12 }))
  })
})

describe('PerformancePage tabs by role', () => {
  const base = { '/performance/cycles': { items: [cycle] }, '/performance/reviews/mine': { items: [] }, '/performance/feedback/received': { items: [] }, '/performance/feedback/given': { items: [] }, '/employees/directory': { items: [] } }

  it('employees get My review and Feedback only', async () => {
    respond(base)
    wrap(<PerformancePage />)
    expect(await screen.findByRole('tab', { name: 'My review' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Feedback' })).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'Team' })).not.toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'Cycles' })).not.toBeInTheDocument()
  })

  it('founders are not reviewed but manage cycles; HR gets everything', async () => {
    auth.user = { id: 1, role: 'founder' }; auth.role = 'founder'
    respond(base)
    const { unmount } = wrap(<PerformancePage />)
    expect(await screen.findByRole('tab', { name: 'Cycles' })).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'My review' })).not.toBeInTheDocument()
    unmount()
    auth.user = { id: 3, role: 'hr' }; auth.role = 'hr'
    wrap(<PerformancePage />)
    for (const t of ['My review', 'Team', 'Feedback', 'Cycles']) expect(await screen.findByRole('tab', { name: t })).toBeInTheDocument()
  })

  it('HR starts a draft cycle after confirming', async () => {
    auth.user = { id: 3, role: 'hr' }; auth.role = 'hr'
    respond({ ...base, '/performance/cycles': { items: [{ ...cycle, id: 4, name: 'Draft cycle', status: 'draft', review_counts: {} }] } })
    post.mockResolvedValue({})
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    wrap(<PerformancePage />)
    await userEvent.click(await screen.findByRole('tab', { name: 'Cycles' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Start' }))
    expect(post).toHaveBeenCalledWith('/performance/cycles/4/activate')
  })

  it('shows the team table once the cycle is known (the reviews query waits for it) and opens a review', async () => {
    auth.user = { id: 2, role: 'manager' }; auth.role = 'manager'
    const rows = { items: [{ id: 9, user_id: 5, employee: 'Elena Engineer', status: 'pending_manager', self_rating: 4, manager_rating: null }], page: 1, page_size: 15, total: 1 }
    const sum = { participants: 1, completion: { self_submitted: 1, manager_submitted: 0, acknowledged: 0 }, average_manager: null }
    respond({ ...base, '/performance/reviews': rows, '/performance/cycles/1/summary': sum, '/performance/reviews/9': review({ status: 'pending_manager', can_review: true, self_submitted_at: 'x', self_rating: 4, self_comments: 'Good year' }), '/auth/me': { id: 2 } })
    wrap(<PerformancePage />)
    await userEvent.click(await screen.findByRole('tab', { name: 'Team' }))
    const row = await screen.findByRole('row', { name: /Elena Engineer/ })
    expect(within(row).getByText('Waiting for manager')).toBeInTheDocument()
    await userEvent.click(within(row).getByRole('button', { name: 'Review' }))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
  })

  it('sends feedback to a colleague, shared by default', async () => {
    respond({ ...base, '/employees/directory': { items: [{ id: 6, full_name: 'Ethan', role: 'employee' }, { id: 5, full_name: 'Elena', role: 'employee' }] } })
    post.mockResolvedValue({})
    wrap(<PerformancePage />)
    await userEvent.click(await screen.findByRole('tab', { name: 'Feedback' }))
    const sel = await screen.findByLabelText(/^to/i)
    expect(within(sel).queryByRole('option', { name: 'Elena' })).not.toBeInTheDocument()                    // not yourself
    await userEvent.selectOptions(sel, '6')
    await userEvent.type(screen.getByLabelText(/^feedback/i), 'Great release')
    await userEvent.click(screen.getByRole('button', { name: 'Send' }))
    expect(post).toHaveBeenCalledWith('/performance/feedback', { to_user_id: 6, body: 'Great release', kind: 'praise', shared: true })
  })
})

describe('navigation', () => {
  it('is open to everyone who is reviewed or manages reviews, not the board', () => {
    for (const r of ['employee', 'manager', 'hr', 'founder']) expect(canAccess(r, '/performance')).toBe(true)
    expect(canAccess('board_member', '/performance')).toBe(false)
  })
})
