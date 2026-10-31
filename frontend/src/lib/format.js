export const fmtDate = (d) => (d ? new Date(d.length === 10 ? `${d}T00:00:00` : d).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : '—')
export const fmtDateTime = (d) => (d ? new Date(d.endsWith('Z') || d.includes('+') ? d : `${d}Z`).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—')
export const fmtTime = (d) => (d ? new Date(d.endsWith('Z') || d.includes('+') ? d : `${d}Z`).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) : '—')
export const today = () => new Date().toISOString().slice(0, 10)
export const label = (s) => (s || '').replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())
export const initials = (name = '') => name.split(' ').filter(Boolean).slice(0, 2).map((p) => p[0].toUpperCase()).join('')
export const ROLE_LABEL = { platform_admin: 'Platform Admin', founder: 'Founder', hr: 'HR', manager: 'Manager', employee: 'Employee', board_member: 'Board member' }

const withZone = (d) => (d.endsWith('Z') || d.includes('+') ? d : `${d}Z`)
/** A time of day in a given IANA zone (the zone attendance is kept in), falling back to the browser's when none is given. */
export const fmtTimeIn = (d, tz) => (d ? new Date(withZone(d)).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', ...(tz ? { timeZone: tz } : {}) }) : '—')
