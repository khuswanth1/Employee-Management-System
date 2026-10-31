import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, buildQuery, fieldErrors, request, session } from './api'
import { breadcrumbs, canAccess, navFor } from './nav'

describe('role navigation', () => {
  it('shows only permitted items per role', () => {
    const labels = (r) => navFor(r).map((n) => n.label)
    expect(labels('employee')).toContain('Employees')                       // the people directory
    expect(labels('board_member')).not.toContain('Employees')
    expect(labels('employee')).not.toContain('Webhooks')
    expect(labels('hr')).toContain('Employees')
    expect(labels('hr')).not.toContain('Webhooks')
    expect(labels('founder')).toContain('Webhooks')
    expect(labels('platform_admin')).toEqual(['Companies'])
  })

  it('guards routes, including nested ones', () => {
    // everyone but board members may open the people directory and any person's page; the page shows the full record only where the server allows it
    expect(canAccess('employee', '/employees')).toBe(true)
    expect(canAccess('employee', '/employees/3')).toBe(true)
    expect(canAccess('employee', '/employees/7', 7)).toBe(true)
    expect(canAccess('board_member', '/employees')).toBe(false)
    expect(canAccess('board_member', '/employees/7', 7)).toBe(false)
    expect(canAccess('manager', '/admin')).toBe(false)
    expect(canAccess('manager', '/updates/team')).toBe(true)
    expect(canAccess('employee', '/updates/team')).toBe(false)
    expect(canAccess('employee', '/updates')).toBe(true)
    expect(canAccess('platform_admin', '/')).toBe(false)
    expect(canAccess('employee', '/teams')).toBe(true)
    expect(canAccess('employee', '/teams/4')).toBe(true)
    expect(canAccess('board_member', '/teams')).toBe(false)
  })

  it('builds breadcrumbs', () => {
    expect(breadcrumbs('/')).toEqual([{ label: 'Dashboard', to: null }])
    expect(breadcrumbs('/projects/12').map((c) => c.label)).toEqual(['Home', 'Projects', '#12'])
  })
})

describe('api client', () => {
  beforeEach(() => sessionStorage.clear())
  afterEach(() => vi.restoreAllMocks())

  it('builds query strings, skipping empty values', () => {
    expect(buildQuery({ a: 1, b: '', c: undefined, d: 'x y' })).toBe('?a=1&d=x+y')
    expect(buildQuery({})).toBe('')
  })

  it('maps validation errors by field', () => {
    const e = new ApiError(422, 'validation_error', 'Invalid', [{ field: 'email', message: 'Value error, bad email' }])
    expect(fieldErrors(e)).toEqual({ email: 'bad email' })
    expect(fieldErrors(new ApiError(500, 'internal_error', 'x'))).toEqual({})
  })

  it('never sends a tenant identifier or a token, and marks itself as the web client (CSRF check)', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{"ok":1}', { status: 200, headers: { 'content-type': 'application/json' } }))
    await request('/projects', { params: { page: 1 } })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/projects?page=1')
    expect(init.headers['X-WS-Client']).toBe('web')
    expect(init.headers.Authorization).toBeUndefined()
    expect(Object.keys(init.headers).some((h) => /tenant|company/i.test(h))).toBe(false)
  })

  it('refreshes an expired session once and retries', async () => {
    document.cookie = 'ws_session=1; path=/'
    const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(json({ error: { code: 'unauthorized', message: 'expired' } }, 401))
      .mockResolvedValueOnce(json({ role: 'employee' }))
      .mockResolvedValueOnce(json({ items: [] }))
    expect(await request('/projects')).toEqual({ items: [] })
    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(fetchMock.mock.calls[1][0]).toBe('/api/v1/auth/refresh')
  })

  it('logs out when refresh fails', async () => {
    document.cookie = 'ws_session=1; path=/'
    const onLogout = vi.fn()
    window.addEventListener('ws:logout', onLogout)
    const json = (body, status) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(json({ error: { code: 'unauthorized', message: 'expired' } }, 401)).mockResolvedValueOnce(json({}, 401))
    await expect(request('/projects')).rejects.toMatchObject({ status: 401 })
    expect(onLogout).toHaveBeenCalled()
    expect(session.exists()).toBe(false)
  })

  it('surfaces server error messages and network failures', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify({ error: { code: 'conflict', message: 'Already exists' } }), { status: 409, headers: { 'content-type': 'application/json' } }))
    await expect(request('/x', { method: 'POST', body: {} })).rejects.toMatchObject({ status: 409, code: 'conflict', message: 'Already exists' })
    vi.spyOn(globalThis, 'fetch').mockRejectedValueOnce(new TypeError('failed'))
    await expect(request('/x')).rejects.toMatchObject({ code: 'network_error' })
  })
})


describe('organisation navigation', () => {
  it('limits board members to analytics, chat and their profile', () => {
    expect(navFor('board_member').map((n) => n.to)).toEqual(['/chat', '/board'])
    for (const p of ['/employees', '/projects', '/leave', '/branches', '/managers', '/board-members']) expect(canAccess('board_member', p)).toBe(false)
    expect(canAccess('board_member', '/board')).toBe(true)
    expect(canAccess('board_member', '/profile')).toBe(true)
  })
  it('keeps founder-only organisation pages away from other roles', () => {
    for (const role of ['hr', 'manager', 'employee']) {
      expect(canAccess(role, '/managers')).toBe(false)
      expect(canAccess(role, '/board-members')).toBe(false)
      expect(canAccess(role, '/board')).toBe(false)
    }
    expect(canAccess('hr', '/branches')).toBe(false)
    expect(canAccess('founder', '/branches')).toBe(true)
    expect(canAccess('employee', '/branches')).toBe(false)
    expect(['hr', 'manager', 'employee'].every((r) => canAccess(r, '/escalations'))).toBe(true)
    expect(canAccess('founder', '/managers') && canAccess('founder', '/board-members') && canAccess('founder', '/board')).toBe(true)
  })
})

describe('founder navigation', () => {
  it('does not offer the personal work pages to the founder (except the to-do list)', () => {
    expect(canAccess('founder', '/my-tasks')).toBe(true)
    for (const p of ['/updates', '/projects', '/projects/3', '/leave', '/escalations']) expect(canAccess('founder', p)).toBe(false)
    expect(navFor('founder').map((n) => n.to)).toEqual(expect.arrayContaining(['/my-tasks']))
    for (const p of ['/updates/team', '/leave/approvals', '/holidays', '/attendance/team', '/employees', '/branches', '/managers', '/board', '/chat']) expect(canAccess('founder', p)).toBe(true)
    for (const role of ['hr', 'manager', 'employee']) expect(canAccess(role, '/holidays')).toBe(true) // everyone can view the holiday calendar
    expect(canAccess('board_member', '/holidays')).toBe(false)
  })
  it('keeps those pages for the other work roles', () => {
    for (const role of ['hr', 'manager', 'employee']) for (const p of ['/my-tasks', '/updates', '/projects', '/leave']) expect(canAccess(role, p)).toBe(true)
  })
})

describe('manager permissions in navigation', () => {
  const links = (role, perms) => navFor(role, perms).map((n) => n.to)
  it('hides the attendance requests page from a manager who lacks attendance.approve, and blocks the route', () => {
    expect(links('manager', ['leave.approve'])).not.toContain('/attendance/corrections')
    expect(canAccess('manager', '/attendance/corrections', 1, ['leave.approve'])).toBe(false)
  })
  it('shows it when granted, when permissions are unknown, and to HR and founders regardless', () => {
    expect(links('manager', ['attendance.approve'])).toContain('/attendance/corrections')
    expect(links('manager', undefined)).toContain('/attendance/corrections')
    expect(canAccess('manager', '/attendance/corrections', 1, ['attendance.approve'])).toBe(true)
    expect(links('hr', null)).toContain('/attendance/corrections')
    expect(canAccess('founder', '/attendance/corrections', 1, null)).toBe(true)
    expect(canAccess('employee', '/attendance/corrections', 1, null)).toBe(false)
  })
})

describe('every permission-gated manager page', () => {
  const gated = { '/leave/approvals': 'leave.approve', '/leave/balances': 'reports.view', '/attendance/team': 'reports.view', '/updates/team': 'reports.view' }
  it.each(Object.entries(gated))('%s needs %s for a manager only', (path, perm) => {
    expect(canAccess('manager', path, 1, [])).toBe(false)
    expect(canAccess('manager', path, 1, [perm])).toBe(true)
    expect(canAccess('hr', path, 1, [])).toBe(true)
    expect(navFor('manager', []).map((n) => n.to)).not.toContain(path)
  })
  it('lets every non-board role open the people directory and a colleague card; the page decides what to show', () => {
    for (const role of ['employee', 'manager', 'hr', 'founder']) {
      expect(canAccess(role, '/employees', 1, [])).toBe(true)
      expect(canAccess(role, '/employees/5', 1, [])).toBe(true)
    }
    expect(canAccess('board_member', '/employees/5', 1, null)).toBe(false)
  })
})
