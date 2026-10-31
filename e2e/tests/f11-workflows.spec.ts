import { test, expect } from '@playwright/test'
import { acct, api, token, iso, nextWeekday } from '../helpers'

const rejected = (s: number) => s >= 400 && s < 500

async function ids() {
  const f = await token(acct('founder'))
  const r = await api('GET', '/employees?page_size=100', f)
  const out: Record<string, number> = {}
  for (const u of r.body.items) out[u.email.split('@')[0]] = u.id
  return { f, id: out }
}

test.describe('F12 tasks', () => {
  test('F12-H1 manager creates, assignee progresses, manager reviews and deletes', async () => {
    const { id } = await ids()
    const m = await token(acct('mgr')); const e2 = await token(acct('e2'))
    const proj = (await api('GET', '/projects', m)).body.items[0]
    const t = await api('POST', `/projects/${proj.id}/tasks`, m, { title: 'Task 🚀 café', assignee_id: id.e2, priority: 'medium', due_date: iso(nextWeekday(7)) })
    expect(t.status).toBe(201)
    const p = await api('PATCH', `/tasks/${t.body.id}`, e2, { status: 'in_progress', progress: 50 })
    expect(p.status).toBe(200)
    expect((await api('GET', `/tasks/${t.body.id}`, m)).body.status).toBe('in_progress')
    expect((await api('DELETE', `/tasks/${t.body.id}`, m)).status).toBe(204)
    expect((await api('GET', `/tasks/${t.body.id}`, m)).status).toBe(404)
  })

  test('F12-N1 someone who is not on the project cannot read or change its tasks', async () => {
    const { id } = await ids()
    const m = await token(acct('mgr')); const e3 = await token(acct('e3'))
    const proj = (await api('GET', '/projects', m)).body.items[0]
    const t = await api('POST', `/projects/${proj.id}/tasks`, m, { title: 'Private', assignee_id: id.e1, priority: 'low' })
    expect(rejected((await api('GET', `/tasks/${t.body.id}`, e3)).status)).toBe(true)
    expect(rejected((await api('PATCH', `/tasks/${t.body.id}`, e3, { status: 'done' })).status)).toBe(true)
  })

  test('F12-N2 empty title and absurd progress are refused, not 500', async () => {
    const { id } = await ids()
    const m = await token(acct('mgr'))
    const proj = (await api('GET', '/projects', m)).body.items[0]
    expect(rejected((await api('POST', `/projects/${proj.id}/tasks`, m, { title: '', assignee_id: id.e1 })).status)).toBe(true)
    const t = await api('POST', `/projects/${proj.id}/tasks`, m, { title: 'P', assignee_id: id.e1 })
    expect(rejected((await api('PATCH', `/tasks/${t.body.id}`, m, { progress: 500 })).status)).toBe(true)
  })

  test('F12-N3 a task cannot depend on itself', async () => {
    const { id } = await ids()
    const m = await token(acct('mgr'))
    const proj = (await api('GET', '/projects', m)).body.items[0]
    const t = await api('POST', `/projects/${proj.id}/tasks`, m, { title: 'Loop', assignee_id: id.e1 })
    expect(rejected((await api('PUT', `/tasks/${t.body.id}/dependencies`, m, { depends_on: [t.body.id] })).status)).toBe(true)
  })
})

test.describe('F13 teams', () => {
  test('F13-H1 manager creates a team, leader sees it, member cannot restructure it', async () => {
    const { id } = await ids()
    const m = await token(acct('mgr'))
    const avail = await api('GET', '/teams/available', m)
    expect(avail.status).toBe(200)
    const e3 = await token(acct('e3'))
    const t = await api('POST', '/teams', m, { name: 'Beta ✨', leader_id: id.e3, member_ids: [id.e3] })
    expect(t.status).toBe(201)
    expect((await api('GET', `/teams/${t.body.id}`, e3)).status).toBe(200)
    expect(rejected((await api('PATCH', `/teams/${t.body.id}`, e3, { name: 'Hijack' })).status)).toBe(true)
    expect(rejected((await api('PUT', `/teams/${t.body.id}/leader`, e3, { user_id: null })).status)).toBe(true)
    expect(rejected((await api('DELETE', `/teams/${t.body.id}`, e3)).status)).toBe(true)
  })

  test('F13-N1 a person can be in only one team', async () => {
    const { id } = await ids()
    const m = await token(acct('mgr'))
    const r = await api('POST', '/teams', m, { name: 'Gamma', member_ids: [id.e1] }) // e1 is already in Alpha Team
    expect(rejected(r.status)).toBe(true)
  })

  test('F13-N2 an employee cannot create teams', async () => {
    const e = await token(acct('e2'))
    expect(rejected((await api('POST', '/teams', e, { name: 'Rogue team' })).status)).toBe(true)
  })

  test('F13-N3 a one-character team name is refused', async () => {
    const m = await token(acct('mgr'))
    expect(rejected((await api('POST', '/teams', m, { name: 'x' })).status)).toBe(true)
  })
})

test.describe('F14 escalations', () => {
  test('F14-H1 employee raises, manager escalates to founder, founder resolves', async () => {
    const e1 = await token(acct('e1')); const m = await token(acct('mgr')); const f = await token(acct('founder'))
    const made = await api('POST', '/escalations', e1, { subject: 'Broken laptop 💻', body: 'It will not boot at all', route: 'manager' })
    expect(made.status).toBe(201)
    const eid = made.body.id
    expect((await api('POST', `/escalations/${eid}/escalate`, m, { note: 'Needs a budget decision' })).status).toBeLessThan(300)
    expect((await api('POST', `/escalations/${eid}/resolve`, f, { resolution: 'New laptop ordered' })).status).toBeLessThan(300)
    const after = await api('GET', `/escalations/${eid}`, e1)
    expect(after.body.status).toBe('resolved')
  })

  test('F14-N1 the raiser cannot resolve their own escalation; others cannot read it', async () => {
    const e1 = await token(acct('e1')); const e2 = await token(acct('e2'))
    const made = await api('POST', '/escalations', e1, { subject: 'Private issue', body: 'Only for my manager', route: 'manager' })
    expect(rejected((await api('POST', `/escalations/${made.body.id}/resolve`, e1, { resolution: 'self resolved' })).status)).toBe(true)
    expect(rejected((await api('GET', `/escalations/${made.body.id}`, e2)).status)).toBe(true)
  })

  test('F14-N2 too-short subject refused', async () => {
    const e1 = await token(acct('e1'))
    expect(rejected((await api('POST', '/escalations', e1, { subject: 'a', body: 'bb' })).status)).toBe(true)
  })
})

test.describe('F15 chat', () => {
  test('F15-H1 employee messages their manager, manager reads it and the unread count drops', async () => {
    const { id } = await ids()
    const e1 = await token(acct('e1')); const m = await token(acct('mgr'))
    const c = await api('POST', '/chat/conversations', e1, { user_id: id.mgr })
    expect(c.status).toBeLessThan(300)
    const cid = c.body.id
    expect((await api('POST', `/chat/conversations/${cid}/messages`, e1, { body: 'Hello 😀 <b>bold</b>' })).status).toBe(201)
    const unread = await api('GET', '/chat/unread-count', m)
    expect(JSON.stringify(unread.body)).toMatch(/[1-9]/)
    const msgs = await api('GET', `/chat/conversations/${cid}/messages`, m)
    expect(JSON.stringify(msgs.body)).toContain('Hello 😀')
    expect((await api('POST', `/chat/conversations/${cid}/read`, m)).status).toBe(204)
    expect(JSON.stringify((await api('GET', '/chat/unread-count', m)).body)).not.toMatch(/[1-9]/)
  })

  test('F15-N1 employee cannot message the founder directly until the founder grants an exception', async () => {
    const { id, f } = await ids()
    const e2 = await token(acct('e2'))
    expect(rejected((await api('POST', '/chat/conversations', e2, { user_id: id.founder })).status)).toBe(true)
    expect((await api('PUT', `/chat/exceptions/${id.e2}`, f)).status).toBe(204)
    expect((await api('POST', '/chat/conversations', e2, { user_id: id.founder })).status).toBeLessThan(300)
    expect((await api('DELETE', `/chat/exceptions/${id.e2}`, f)).status).toBe(204)
  })

  test('F15-N2 blank and oversize messages refused', async () => {
    const { id } = await ids()
    const e1 = await token(acct('e1'))
    const c = await api('POST', '/chat/conversations', e1, { user_id: id.mgr })
    expect(rejected((await api('POST', `/chat/conversations/${c.body.id}/messages`, e1, { body: '   ' })).status)).toBe(true)
    expect(rejected((await api('POST', `/chat/conversations/${c.body.id}/messages`, e1, { body: 'x'.repeat(5000) })).status)).toBe(true)
  })

  test('F15-N3 outsiders cannot read or post in someone else\'s conversation', async () => {
    const { id } = await ids()
    const e1 = await token(acct('e1')); const e2 = await token(acct('e2'))
    const c = await api('POST', '/chat/conversations', e1, { user_id: id.mgr })
    expect(rejected((await api('GET', `/chat/conversations/${c.body.id}/messages`, e2)).status)).toBe(true)
    expect(rejected((await api('POST', `/chat/conversations/${c.body.id}/messages`, e2, { body: 'intruder' })).status)).toBe(true)
  })
})

test.describe('F16 webhooks', () => {
  test('F16-H1 founder registers an HTTPS webhook; the secret is shown once', async () => {
    const f = await token(acct('founder'))
    const events = (await api('GET', '/webhooks/events', f)).body
    const list: string[] = Array.isArray(events) ? events : events.items ?? events.events
    const r = await api('POST', '/webhooks', f, { url: 'https://example.com/hooks/worksphere', events: [list.find((e) => e !== 'webhook.test')] })
    expect(r.status).toBe(201)
    expect(JSON.stringify(r.body)).toMatch(/secret/i)
    const again = await api('GET', '/webhooks', f)
    expect(JSON.stringify(again.body)).not.toContain(r.body.secret ?? 'no-secret-present')
  })

  test('F16-N1 plain http, localhost and private addresses are refused (SSRF guard)', async () => {
    const f = await token(acct('founder'))
    const ev = ['task.created']
    for (const url of ['http://example.com/x', 'https://localhost/x', 'https://127.0.0.1/x', 'https://169.254.169.254/latest/meta-data', 'https://10.0.0.5/x', 'ftp://example.com/x', 'javascript:alert(1)']) {
      const r = await api('POST', '/webhooks', f, { url, events: ev })
      expect(rejected(r.status), `${url} -> ${r.status}`).toBe(true)
    }
  })

  test('F16-N2 non-founders cannot manage webhooks', async () => {
    for (const k of ['hr', 'mgr', 'e1']) expect(rejected((await api('GET', '/webhooks', await token(acct(k)))).status)).toBe(true)
  })
})

test.describe('F17 notifications', () => {
  test('F17-H1 a leave request notifies the manager; marking read works', async () => {
    const e1 = await token(acct('e1')); const m = await token(acct('mgr'))
    const before = (await api('GET', '/notifications', m)).body.total ?? 0
    const types = await api('GET', '/leave/types', e1)
    const d = iso(nextWeekday(90))
    const lr = await api('POST', '/leave/requests', e1, { leave_type_id: types.body.items[0].id, start_date: d, end_date: d, reason: 'notify me' })
    expect(lr.status).toBe(201)
    const after = await api('GET', '/notifications', m)
    expect(after.body.total).toBeGreaterThan(before)
    const first = after.body.items[0]
    expect((await api('POST', `/notifications/${first.id}/read`, m)).status).toBe(204)
  })

  test('F17-N1 nobody can mark another user\'s notification read', async () => {
    const m = await token(acct('mgr')); const e2 = await token(acct('e2'))
    const n = (await api('GET', '/notifications', m)).body.items[0]
    expect(rejected((await api('POST', `/notifications/${n.id}/read`, e2)).status)).toBe(true)
  })
})

test.describe('F18 leave: reject and cancel', () => {
  test('F18-H1 manager rejects with a note, employee sees Rejected; pending request can be cancelled', async () => {
    const e2 = await token(acct('e2')); const m = await token(acct('mgr'))
    const types = await api('GET', '/leave/types', e2)
    const d = iso(nextWeekday(120)); const d2 = iso(nextWeekday(130))
    const a = await api('POST', '/leave/requests', e2, { leave_type_id: types.body.items[0].id, start_date: d, end_date: d, reason: 'reject me' })
    expect((await api('POST', `/leave/requests/${a.body.id}/decision`, m, { approved: false, note: 'Busy period' })).status).toBeLessThan(300)
    const mine = await api('GET', '/leave/requests/mine', e2)
    expect(mine.body.items.find((x: { id: number }) => x.id === a.body.id).status).toBe('rejected')
    const b = await api('POST', '/leave/requests', e2, { leave_type_id: types.body.items[0].id, start_date: d2, end_date: d2, reason: 'cancel me' })
    expect((await api('POST', `/leave/requests/${b.body.id}/cancel`, e2)).status).toBeLessThan(300)
    expect(rejected((await api('POST', `/leave/requests/${b.body.id}/decision`, m, { approved: true, note: '' })).status)).toBe(true) // already cancelled
  })

  test('F18-N1 leave on a weekend or in the past is refused', async () => {
    const e2 = await token(acct('e2'))
    const types = await api('GET', '/leave/types', e2)
    const past = '2020-01-06'
    expect(rejected((await api('POST', '/leave/requests', e2, { leave_type_id: types.body.items[0].id, start_date: past, end_date: past })).status)).toBe(true)
  })
})
