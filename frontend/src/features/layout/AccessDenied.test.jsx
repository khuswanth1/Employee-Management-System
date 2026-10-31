import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const auth = { user: { id: 3, role: 'employee' }, role: 'employee' }
vi.mock('../auth/AuthContext', () => ({ useAuth: () => auth }))
import AccessDenied from './AccessDenied'

const show = (path) => render(<MemoryRouter><AccessDenied path={path} /></MemoryRouter>)
beforeEach(() => { auth.user = { id: 3, role: 'employee' }; auth.role = 'employee' })

describe('AccessDenied', () => {
  it("explains that employee records are closed to board members and points to useful pages", () => {
    auth.user = { id: 3, role: 'board_member' }; auth.role = 'board_member'
    show('/employees/1')
    expect(screen.getByRole('heading', { name: 'This profile is private' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'View the org chart' })).toHaveAttribute('href', '/org-chart')
    expect(screen.getByRole('link', { name: 'Go to dashboard' })).toHaveAttribute('href', '/')
    expect(screen.queryByText(/Access denied/)).not.toBeInTheDocument()
  })
  it('explains the employee list instead of a bare refusal', () => {
    show('/employees')
    expect(screen.getByRole('heading', { name: /employee records list is not available/i })).toBeInTheDocument()
  })
  it('tells a manager which permission is missing', () => {
    auth.user = { id: 9, role: 'manager' }; auth.role = 'manager'
    show('/leave/approvals')
    expect(screen.getByRole('heading', { name: 'Leave Approvals needs an extra permission' })).toBeInTheDocument()
    expect(screen.getByText(/leave\.approve/)).toBeInTheDocument()
  })
  it('falls back to a role message for any other page', () => {
    show('/webhooks')
    expect(screen.getByText(/Your role \(Employee\) cannot open it/)).toBeInTheDocument()
  })
  it('offers no profile link to board members', () => {
    auth.user = { id: 5, role: 'board_member' }; auth.role = 'board_member'
    show('/employees')
    expect(screen.queryByRole('link', { name: 'Open my profile' })).not.toBeInTheDocument()
  })
})
