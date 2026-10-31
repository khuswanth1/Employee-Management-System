import { Link } from 'react-router-dom'
import { ROLE_LABEL } from '../../lib/format'
import { deniedReason } from '../../lib/nav'
import { useAuth } from '../auth/AuthContext'

const PERMISSION_TEXT = {
  'employees.manage': 'view and manage their direct reports',
  'leave.approve': 'approve or reject leave requests',
  'reports.view': 'view team reports',
  'attendance.approve': 'review attendance corrections',
}

function LinkButton({ to, children, primary }) {
  return <Link to={to} className={primary ? 'rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700' : 'rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50'}>{children}</Link>
}

// Shown instead of a page the person may not open. It says why, keeps other people's details hidden, and offers somewhere useful to go.
export default function AccessDenied({ path }) {
  const { user, role } = useAuth()
  const why = deniedReason(role, path)
  const mine = `/employees/${user.id}`
  let title = 'You do not have access to this page'
  let body = `Your role (${ROLE_LABEL?.[role] || role}) cannot open it.`
  if (why.kind === 'profile') {
    title = 'This profile is private'
    body = 'You can open your own record in full. Personal details, documents and history of other people are visible only to their manager and HR. The org chart and departments show names, titles and teams.'
  } else if (why.kind === 'directory') {
    title = 'The employee records list is not available to you'
    body = 'Employee records are managed by HR, founders and managers with the right permission. You can open your own record, and the org chart shows who works where.'
  } else if (why.kind === 'permission') {
    title = `${why.label} needs an extra permission`
    body = `Your account is not allowed to ${PERMISSION_TEXT[why.perm] || 'use this page'} (permission "${why.perm}"). Ask a founder to grant it under Managers.`
  }
  return (
    <div role="alert" className="mx-auto max-w-xl py-16 text-center">
      <div aria-hidden className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-slate-100 text-xl text-slate-500">🔒</div>
      <h1 className="text-lg font-semibold text-slate-900">{title}</h1>
      <p className="mt-2 text-sm text-slate-600">{body}</p>
      <div className="mt-6 flex flex-wrap justify-center gap-3">
        <LinkButton to="/" primary>Go to dashboard</LinkButton>
        {role !== 'board_member' && <LinkButton to={mine}>Open my profile</LinkButton>}
        {['profile', 'directory'].includes(why.kind) && <LinkButton to="/org-chart">View the org chart</LinkButton>}
        {['profile', 'directory'].includes(why.kind) && <LinkButton to="/departments">Departments</LinkButton>}
      </div>
    </div>
  )
}
