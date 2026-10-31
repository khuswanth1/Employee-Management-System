import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const get = vi.fn()
const auth = { user: { id: 3, role: 'employee', full_name: 'Elena', permissions: null }, role: 'employee' }
vi.mock('../auth/AuthContext', () => ({ useAuth: () => auth }))
vi.mock('../../lib/api', async (orig) => ({ ...(await orig()), api: { get: (...a) => get(...a), post: vi.fn(), patch: vi.fn(), put: vi.fn(), del: vi.fn() } }))
vi.mock('./EmployeeDetailPage', () => ({ default: () => <h1>FULL RECORD</h1> }))

import EmployeeDirectory from './EmployeeDirectory'
import EmployeeRoute from './ColleagueCard'
import EmployeesPage from './EmployeesPage'

const wrap = (ui, path) => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={[path]}>
      <Routes><Route path="/employees" element={ui} /><Route path="/employees/:id" element={ui} /></Routes>
    </MemoryRouter>
  </QueryClientProvider>,
)
const respond = (map) => get.mockImplementation(async (path) => { if (path in map) return map[path]; throw new Error(`unexpected GET ${path}`) })
const card = (over = {}) => ({ id: 9, full_name: 'Marcus Manager', designation: 'Engineering Manager', role: 'manager', avatar_v: null, department: 'Engineering', branch: 'North',
  location: 'Oslo', manager: { id: 1, name: 'Fiona Founder' }, team: 'Mobile', joined: '2024-01-02', direct_reports: 4, email: null, can_open: false, ...over })
beforeEach(() => { vi.clearAllMocks(); auth.user = { id: 3, role: 'employee', full_name: 'Elena', permissions: null }; auth.role = 'employee' })

describe('EmployeeRoute', () => {
  it('shows a colleague card with directory facts and nothing personal when the record is closed', async () => {
    respond({ '/employees/9/card': card() })
    wrap(<EmployeeRoute />, '/employees/9')
    expect(await screen.findByRole('heading', { name: 'Marcus Manager' })).toBeInTheDocument()
    const facts = within(screen.getByLabelText('About Marcus Manager'))
    expect(facts.getByText('Engineering')).toBeInTheDocument()
    expect(facts.getByText('Mobile')).toBeInTheDocument()
    expect(facts.getByRole('link', { name: 'Fiona Founder' })).toHaveAttribute('href', '/employees/1')
    expect(screen.queryByText(/@/)).not.toBeInTheDocument()                       // no e-mail for employees
    expect(screen.queryByText('FULL RECORD')).not.toBeInTheDocument()
    expect(screen.getByText(/visible only to the person, their manager and HR/)).toBeInTheDocument()
  })
  it('shows the e-mail when the server sends it', async () => {
    respond({ '/employees/9/card': card({ email: 'marcus@acme.com' }) })
    wrap(<EmployeeRoute />, '/employees/9')
    expect(await screen.findByRole('link', { name: 'marcus@acme.com' })).toHaveAttribute('href', 'mailto:marcus@acme.com')
  })
  it('opens the full record when the server says the viewer may', async () => {
    respond({ '/employees/9/card': card({ can_open: true }) })
    wrap(<EmployeeRoute />, '/employees/9')
    expect(await screen.findByText('FULL RECORD')).toBeInTheDocument()
  })
  it('reports a person who cannot be seen', async () => {
    get.mockRejectedValue(Object.assign(new Error('Employee not found'), { status: 404 }))
    wrap(<EmployeeRoute />, '/employees/77')
    expect(await screen.findByText(/not found/i)).toBeInTheDocument()
  })
})

describe('EmployeesPage by role', () => {
  const dir = { '/employees/directory': { items: [{ id: 9, full_name: 'Marcus Manager', designation: 'Eng Manager', role: 'manager', department_id: 1 }, { id: 4, full_name: 'Zoe Zhang', designation: 'QA', role: 'employee', department_id: 1 }] }, '/departments': { items: [{ id: 1, name: 'Engineering' }] } }
  it('gives an employee a searchable read-only directory whose rows open the card', async () => {
    respond(dir)
    wrap(<EmployeesPage />, '/employees')
    expect(await screen.findByRole('heading', { name: 'People' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /add employee/i })).not.toBeInTheDocument()
    await userEvent.type(screen.getByRole('searchbox'), 'zoe')
    await waitFor(() => expect(screen.queryByText('Marcus Manager')).not.toBeInTheDocument())
    expect(screen.getByText('Zoe Zhang')).toBeInTheDocument()
  })
  it('a manager without employees.manage gets the same directory', async () => {
    auth.user = { id: 5, role: 'manager', permissions: ['leave.approve'] }; auth.role = 'manager'
    respond(dir)
    wrap(<EmployeeDirectory />, '/employees')
    expect(await screen.findByRole('heading', { name: 'People' })).toBeInTheDocument()
  })
})
