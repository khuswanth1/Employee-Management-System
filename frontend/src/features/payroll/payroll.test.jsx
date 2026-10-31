import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../../components/ui'
import { canAccess } from '../../lib/nav'

const get = vi.fn(), post = vi.fn(), patch = vi.fn()
const auth = { user: { id: 1, role: 'hr', full_name: 'Hannah HR', branch_id: null }, role: 'hr' }
vi.mock('../auth/AuthContext', () => ({ useAuth: () => auth }))
vi.mock('../../lib/api', async (orig) => ({ ...(await orig()), api: { get: (...a) => get(...a), post: (...a) => post(...a), patch: (...a) => patch(...a), del: vi.fn(), put: vi.fn() }, download: vi.fn() }))

import MyPayslipsPage from './MyPayslipsPage'
import PayrollPage from './PayrollPage'
import PayrollRunPage from './PayrollRunPage'
import PayslipView from './PayslipView'
import { fmtMoney, monthName, warningText } from './money'

const wrap = (ui, path = '/x') => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <ToastProvider><MemoryRouter initialEntries={[path]}><Routes><Route path="/x" element={ui} /><Route path="/payroll/runs/:id" element={ui} /></Routes></MemoryRouter></ToastProvider>
  </QueryClientProvider>,
)
const respond = (map) => get.mockImplementation(async (path) => {
  if (path in map) return map[path]
  throw new Error(`unexpected GET ${path}`)
})

const slip = (over = {}) => ({ id: 11, run_id: 3, user_id: 5, employee: 'Elena Engineer', employee_code: 'EMP-0005', designation: 'Engineer', currency: 'USD', basic: 3000, gross: 4400, deductions: 580, net: 3820,
  warnings: [], facts: { scheduled_days: 22, payable_days: '22', paid_leave_days: '0', unpaid_leave_days: '0', absent_days: '0', overtime_hours: '0.00' }, period: { year: 2026, month: 1, start: '2026-01-01', end: '2026-01-31' }, run_status: 'approved',
  lines: [{ id: 1, code: 'BASIC', name: 'Basic salary', kind: 'earning', amount: 3000, basis: 'full month', adjustment: false },
    { id: 2, code: 'HRA', name: 'Housing allowance', kind: 'earning', amount: 1200, basis: '40% of basic', adjustment: false },
    { id: 3, code: 'RETIRE', name: 'Retirement contribution', kind: 'deduction', amount: 360, basis: '12% of basic', adjustment: false },
    { id: 4, code: 'ADJ', name: 'Spot bonus', kind: 'earning', amount: 200, basis: 'one-off adjustment', adjustment: true }], ...over })

const run = (over = {}) => ({ id: 3, year: 2026, month: 1, status: 'draft', note: null, processed_by: null, approved_by: null, processed_at: null, approved_at: null, paid_at: null, payment_reference: null,
  policy: { currency: 'USD' }, skipped: [], totals: { payslips: 1, gross: 4400, deductions: 580, net: 3820 }, by_department: [{ department: 'Engineering', people: 1, gross: 4400, net: 3820 }],
  payslips: [{ id: 11, user_id: 5, employee: 'Elena Engineer', currency: 'USD', basic: 3000, gross: 4400, deductions: 580, net: 3820, warnings: [] }], ...over })

beforeEach(() => { vi.clearAllMocks(); auth.role = 'hr'; auth.user = { id: 1, role: 'hr', full_name: 'Hannah HR', branch_id: null } })

describe('money helpers', () => {
  it('formats amounts, months and warnings, and survives an unknown currency code', () => {
    expect(fmtMoney(1234.5, 'USD')).toContain('1,234.50')
    expect(fmtMoney(1234.5, 'ZZZZ')).toBe('1,234.50 ZZZZ')
    expect(fmtMoney(null)).toBe('—')
    expect(monthName(2026, 1)).toBe('January 2026')
    expect(warningText('deductions_exceed_pay')).toMatch(/larger than pay/)
    expect(warningText('invalid_calc:ODD')).toMatch(/ODD/)
  })
})

describe('PayslipView', () => {
  it('shows earnings, deductions, the totals and marks one-off lines', async () => {
    respond({ '/payroll/payslips/11': slip() })
    wrap(<PayslipView id={11} onClose={() => {}} />)
    expect(await screen.findByText('Elena Engineer')).toBeInTheDocument()
    const earnings = within(screen.getByRole('table', { name: 'Earnings' }))
    expect(earnings.getByText('Housing allowance')).toBeInTheDocument()
    expect(earnings.getByText('(one-off)')).toBeInTheDocument()
    expect(within(screen.getByRole('table', { name: 'Deductions' })).getByText('Retirement contribution')).toBeInTheDocument()
    expect(screen.getByText('Net pay').nextSibling).toHaveTextContent('$3,820.00')
    expect(screen.getByText(/22 of 22 working days paid/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Print / save as PDF' })).toBeEnabled()
    expect(screen.queryByText(/not yet approved/)).not.toBeInTheDocument()
  })

  it('warns when the figures are a draft or have a problem', async () => {
    respond({ '/payroll/payslips/11': slip({ run_status: 'draft', warnings: ['deductions_exceed_pay'], net: -10 }) })
    wrap(<PayslipView id={11} onClose={() => {}} />)
    expect(await screen.findByText(/not yet approved/i)).toBeInTheDocument()
    expect(screen.getByText('Deductions are larger than pay')).toBeInTheDocument()
  })
})

describe('MyPayslipsPage', () => {
  it('lists issued payslips and opens one', async () => {
    respond({ '/payroll/my-payslips': { items: [{ id: 11, year: 2026, month: 1, currency: 'USD', gross: 4400, deductions: 580, net: 3820, status: 'approved' }] }, '/payroll/payslips/11': slip() })
    wrap(<MyPayslipsPage />)
    expect(await screen.findByText('January 2026')).toBeInTheDocument()
    expect(screen.getByText('$3,820.00')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'View' }))
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
  })

  it('shows an empty state before anything is approved', async () => {
    respond({ '/payroll/my-payslips': { items: [] } })
    wrap(<MyPayslipsPage />)
    expect(await screen.findByText('No payslips yet')).toBeInTheDocument()
  })
})

describe('PayrollRunPage workflow', () => {
  const at = () => wrap(<PayrollRunPage />, '/payroll/runs/3')

  it('lets payroll staff recalculate and submit a draft, and adjust a payslip', async () => {
    respond({ '/payroll/runs/3': run() })
    post.mockResolvedValue({})
    at()
    await userEvent.click(await screen.findByRole('button', { name: 'Submit for approval' }))
    expect(post).toHaveBeenCalledWith('/payroll/runs/3/submit')
    await userEvent.click(screen.getByRole('button', { name: 'Recalculate' }))
    expect(post).toHaveBeenCalledWith('/payroll/runs/3/recalculate')
    await userEvent.click(screen.getByRole('button', { name: 'Adjust' }))
    const dlg = within(await screen.findByRole('dialog'))
    expect(dlg.getByRole('button', { name: 'Add' })).toBeDisabled()
    await userEvent.type(dlg.getByLabelText(/description/i), 'Spot bonus')
    await userEvent.type(dlg.getByLabelText(/amount/i), '250.5')
    await userEvent.click(dlg.getByRole('button', { name: 'Add' }))
    expect(post).toHaveBeenLastCalledWith('/payroll/payslips/11/adjustments', { name: 'Spot bonus', kind: 'earning', amount: 250.5 })
  })

  it('does not offer to approve a run you submitted yourself', async () => {
    respond({ '/payroll/runs/3': run({ status: 'processed', processed_by: 'Hannah HR' }) })
    at()
    expect(await screen.findByText(/someone else has to approve/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Recalculate' })).not.toBeInTheDocument()
  })

  it('lets another person approve after confirming, and requires a reason to send back', async () => {
    auth.user = { id: 2, role: 'founder', full_name: 'Fiona Founder', branch_id: null }; auth.role = 'founder'
    respond({ '/payroll/runs/3': run({ status: 'processed', processed_by: 'Hannah HR' }) })
    post.mockResolvedValue({})
    at()
    await userEvent.click(await screen.findByRole('button', { name: 'Send back' }))
    let dlg = within(await screen.findByRole('dialog'))
    expect(dlg.getByRole('button', { name: 'Send back' })).toBeDisabled()
    await userEvent.type(dlg.getByLabelText(/what needs fixing/i), 'Check Ethan')
    await userEvent.click(dlg.getByRole('button', { name: 'Send back' }))
    expect(post).toHaveBeenCalledWith('/payroll/runs/3/return', { note: 'Check Ethan' })
    await userEvent.click(await screen.findByRole('button', { name: 'Approve' }))
    dlg = within(await screen.findByRole('dialog'))
    expect(dlg.getByText(/become final and visible to employees/)).toBeInTheDocument()
    await userEvent.click(dlg.getByRole('button', { name: 'Approve' }))
    expect(post).toHaveBeenLastCalledWith('/payroll/runs/3/approve')
  })

  it('blocks approval while a payslip has deductions larger than pay', async () => {
    auth.user = { id: 2, role: 'founder', full_name: 'Fiona Founder', branch_id: null }; auth.role = 'founder'
    const bad = run({ status: 'processed', processed_by: 'Hannah HR', payslips: [{ id: 11, user_id: 5, employee: 'Elena', currency: 'USD', basic: 100, gross: 100, deductions: 900, net: -800, warnings: ['deductions_exceed_pay'] }] })
    respond({ '/payroll/runs/3': bad })
    at()
    expect(await screen.findByText(/block approval/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Approve' })).toBeDisabled()
  })

  it('shows people left out of the run, and offers only "mark as paid" once approved', async () => {
    respond({ '/payroll/runs/3': run({ status: 'approved', processed_by: 'Hannah HR', approved_by: 'Fiona', skipped: [{ user_id: 9, name: 'Nia New', reason: 'no pay structure set up' }] }) })
    at()
    expect(await screen.findByText(/Nia New \(no pay structure set up\)/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Mark as paid' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Cancel run' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Recalculate' })).not.toBeInTheDocument()
  })

  it('hides run actions from branch HR', async () => {
    auth.user = { id: 3, role: 'hr', full_name: 'Branch HR', branch_id: 4 }
    respond({ '/payroll/runs/3': run() })
    at()
    await screen.findByText('Elena Engineer')
    expect(screen.queryByRole('button', { name: 'Submit for approval' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Adjust' })).not.toBeInTheDocument()
  })
})

describe('PayrollPage', () => {
  const comps = { items: [
    { id: 1, code: 'HRA', name: 'Housing allowance', kind: 'earning', calc: 'percent_of_basic', default_value: 40, prorate: true, cap: null, note: null, is_active: true },
    { id: 2, code: 'RETIRE', name: 'Retirement contribution', kind: 'deduction', calc: 'percent_of_basic', default_value: 12, prorate: true, cap: 500, note: null, is_active: true }] }

  it('offers percentage-of-gross only for deductions when adding a component', async () => {
    respond({ '/payroll/components': comps })
    post.mockResolvedValue({})
    wrap(<PayrollPage />)
    await userEvent.click(await screen.findByRole('tab', { name: 'Components' }))
    await userEvent.click(await screen.findByRole('button', { name: 'New component' }))
    const dlg = within(await screen.findByRole('dialog'))
    expect(dlg.getByText(/not built in/i)).toBeInTheDocument()
    expect(dlg.queryByRole('option', { name: 'Percentage of gross pay' })).not.toBeInTheDocument()
    await userEvent.selectOptions(dlg.getByLabelText('Type'), 'deduction')
    expect(dlg.getByRole('option', { name: 'Percentage of gross pay' })).toBeInTheDocument()
    await userEvent.type(dlg.getByLabelText(/^code/i), 'LEVY')
    await userEvent.type(dlg.getByLabelText(/^name/i), 'Income levy')
    await userEvent.selectOptions(dlg.getByLabelText('Calculated as'), 'percent_of_gross')
    await userEvent.clear(dlg.getByLabelText(/default percentage/i))
    await userEvent.type(dlg.getByLabelText(/default percentage/i), '5')
    await userEvent.click(dlg.getByRole('button', { name: 'Save' }))
    expect(post).toHaveBeenCalledWith('/payroll/components', expect.objectContaining({ code: 'LEVY', kind: 'deduction', calc: 'percent_of_gross', default_value: 5, cap: null }))
  })

  it('saves a new version of someone\'s pay structure with the chosen components', async () => {
    respond({
      '/payroll/compensation': { items: [{ user_id: 5, name: 'Elena Engineer', employee_code: 'EMP-0005', role: 'employee', basic: 3000, currency: 'USD', effective_from: '2025-06-01' }], page: 1, page_size: 15, total: 1 },
      '/payroll/compensation/5': { user: { id: 5 }, items: [{ id: 1, effective_from: '2025-06-01', basic: 3000, currency: 'USD', note: null, lines: [{ component_id: 1, code: 'HRA', name: 'Housing allowance', kind: 'earning', calc: 'percent_of_basic', value: 40 }] }] },
      '/payroll/components': comps, '/admin/settings': { items: [] },
    })
    post.mockResolvedValue({})
    wrap(<PayrollPage />)
    await userEvent.click(await screen.findByRole('tab', { name: 'Pay structures' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Change' }))
    const dlg = within(await screen.findByRole('dialog'))
    expect(await dlg.findByDisplayValue('3000')).toBeInTheDocument()                       // starts from the current structure
    expect(dlg.getByDisplayValue('40')).toBeInTheDocument()
    await userEvent.clear(dlg.getByLabelText(/monthly basic/i))
    await userEvent.type(dlg.getByLabelText(/monthly basic/i), '3300')
    await userEvent.type(dlg.getByLabelText(/retirement contribution/i), '12')
    await userEvent.click(dlg.getByRole('button', { name: 'Save new version' }))
    expect(post).toHaveBeenCalledWith('/payroll/compensation/5', expect.objectContaining({ basic: 3300, lines: [{ component_id: 1, value: 40 }, { component_id: 2, value: 12 }] }))
  })
})

describe('navigation', () => {
  it('keeps payroll pages to payroll staff, and payslips to everyone who is paid', () => {
    for (const role of ['employee', 'manager', 'board_member']) expect(canAccess(role, '/payroll')).toBe(false)
    expect(canAccess('hr', '/payroll')).toBe(true)
    expect(canAccess('founder', '/payroll/runs/3')).toBe(true)
    expect(canAccess('manager', '/payroll/runs/3')).toBe(false)
    expect(canAccess('employee', '/payslips')).toBe(true)
    expect(canAccess('board_member', '/payslips')).toBe(false)
  })
})
