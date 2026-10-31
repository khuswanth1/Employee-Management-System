// Navigation + route access rules. The server is the source of truth for permissions;
// this only decides what to show and which routes to offer.
export const NAV = [
  { to: '/', label: 'Dashboard', icon: 'home', roles: ['founder', 'hr', 'manager', 'employee'], end: true },
  { to: '/my-tasks', label: 'My Tasks', icon: 'check', roles: ['founder', 'hr', 'manager', 'employee'] },
  { to: '/projects', label: 'Projects', icon: 'folder', roles: ['hr', 'manager', 'employee'] },
  { to: '/teams', label: 'Teams', icon: 'users', roles: ['founder', 'hr', 'manager', 'employee'] },
  { to: '/updates', label: 'Daily Updates', icon: 'pencil', roles: ['hr', 'manager', 'employee'] },
  { to: '/updates/team', label: 'Team Updates', icon: 'users', roles: ['founder', 'hr', 'manager'], perm: 'reports.view' },
  { to: '/attendance', label: 'Attendance', icon: 'clock', roles: ['founder', 'hr', 'manager', 'employee'] },
  { to: '/attendance/team', label: 'Attendance Report', icon: 'chart', roles: ['founder', 'hr', 'manager'], perm: 'reports.view' },
  { to: '/attendance/corrections', label: 'Attendance Requests', icon: 'inbox', roles: ['founder', 'hr', 'manager'], perm: 'attendance.approve' },
  { to: '/attendance/setup', label: 'Shifts & locations', icon: 'clock', roles: ['founder', 'hr'] },
  { to: '/leave', label: 'Leave', icon: 'calendar', roles: ['hr', 'manager', 'employee'] },
  { to: '/holidays', label: 'Holiday calendar', icon: 'calendar', roles: ['founder', 'hr', 'manager', 'employee'] },
  { to: '/leave/approvals', label: 'Leave Approvals', icon: 'inbox', roles: ['founder', 'hr', 'manager'], perm: 'leave.approve' },
  { to: '/leave/balances', label: 'Leave Balances', icon: 'chart', roles: ['founder', 'hr', 'manager'], perm: 'reports.view' },
  { to: '/employees', label: 'Employees', icon: 'users', roles: ['founder', 'hr', 'manager', 'employee'] },
  { to: '/branches', label: 'Branches', icon: 'pin', roles: ['founder'] },
  { to: '/managers', label: 'Managers', icon: 'badge', roles: ['founder'] },
  { to: '/board-members', label: 'Board members', icon: 'crown', roles: ['founder'] },
  { to: '/org-chart', label: 'Org chart', icon: 'users', roles: ['founder', 'hr', 'manager', 'employee'] },
  { to: '/lifecycle', label: 'Lifecycle', icon: 'flag', roles: ['founder', 'hr'] },
  { to: '/departments', label: 'Departments', icon: 'building', roles: ['founder', 'hr', 'manager', 'employee'] },
  { to: '/chat', label: 'Chat', icon: 'chat', roles: ['founder', 'hr', 'manager', 'employee', 'board_member'] },
  { to: '/escalations', label: 'Escalations', icon: 'flag', roles: ['hr', 'manager', 'employee'] },
  { to: '/board', label: 'Board analytics', icon: 'chart', roles: ['founder', 'board_member'] },
  { to: '/meetings', label: 'Meetings', icon: 'video', roles: ['founder', 'hr', 'manager', 'employee'] },
  { to: '/webhooks', label: 'Webhooks', icon: 'plug', roles: ['founder'] },
  { to: '/performance', label: 'Performance', icon: 'chart', roles: ['founder', 'hr', 'manager', 'employee'] },
  { to: '/payroll', label: 'Payroll', icon: 'badge', roles: ['founder', 'hr'] },
  { to: '/payslips', label: 'My payslips', icon: 'inbox', roles: ['founder', 'hr', 'manager', 'employee'] },
  { to: '/admin', label: 'Administration', icon: 'shield', roles: ['founder', 'hr'] },
  { to: '/platform', label: 'Companies', icon: 'building', roles: ['platform_admin'], end: true },
]

// `perm` only applies to managers (their permissions can be switched off individually); other roles are decided by role alone
const permitted = (n, role, perms) => !n.perm || role !== 'manager' || !perms || perms.includes(n.perm)
export const navFor = (role, perms) => NAV.filter((n) => n.roles.includes(role) && permitted(n, role, perms))
export const canAccess = (role, path, userId, perms) => {
  // a person's own employee page (personal details, documents) is open to them; the server enforces the same rule
  if (userId != null && role !== 'board_member' && path === `/employees/${userId}`) return true
  const match = NAV.filter((n) => (n.end ? path === n.to : path === n.to || path.startsWith(`${n.to}/`))).sort((a, b) => b.to.length - a.to.length)[0]
  // the permission gates the page itself, not records below it (e.g. /employees/5 is decided by the server)
  return match ? match.roles.includes(role) && (path !== match.to || permitted(match, role, perms)) : true
}

// Why canAccess said no, so the page can explain it instead of a bare "Access denied".
export const deniedReason = (role, path) => {
  const match = NAV.filter((n) => (n.end ? path === n.to : path === n.to || path.startsWith(`${n.to}/`))).sort((a, b) => b.to.length - a.to.length)[0]
  if (match && match.roles.includes(role) && match.perm) return { kind: 'permission', perm: match.perm, label: match.label }
  if (/^\/employees\/\d+/.test(path)) return { kind: 'profile' }
  if (path === '/employees') return { kind: 'directory' }
  return { kind: 'role', label: match?.label }
}

export const CRUMBS = {
  '/my-tasks': 'My Tasks', '/projects': 'Projects', '/teams': 'Teams', '/teams/analytics': 'Productivity', '/updates': 'Daily Updates', '/updates/team': 'Team Updates',
  '/attendance': 'Attendance', '/attendance/team': 'Report', '/attendance/corrections': 'Corrections', '/attendance/setup': 'Shifts & locations', '/leave': 'Leave', '/holidays': 'Holiday calendar', '/leave/approvals': 'Approvals', '/leave/balances': 'Balances',
  '/employees': 'Employees', '/departments': 'Departments', '/org-chart': 'Org chart', '/lifecycle': 'Lifecycle', '/meetings': 'Meetings', '/chat': 'Chat', '/branches': 'Branches', '/managers': 'Managers', '/board-members': 'Board members', '/board': 'Board analytics', '/escalations': 'Escalations', '/webhooks': 'Webhooks',
  '/admin': 'Administration', '/payroll': 'Payroll', '/performance': 'Performance', '/payroll/runs': 'Runs', '/payslips': 'My payslips', '/platform': 'Companies', '/notifications': 'Notifications',
}

export function breadcrumbs(pathname) {
  const parts = pathname.split('/').filter(Boolean)
  const out = [{ label: 'Home', to: '/' }]
  let acc = ''
  parts.forEach((p, i) => {
    acc += `/${p}`
    out.push({ label: CRUMBS[acc] || (/^\d+$/.test(p) ? `#${p}` : p), to: i === parts.length - 1 ? null : acc })
  })
  return parts.length ? out : [{ label: 'Dashboard', to: null }]
}
