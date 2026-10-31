import { test, expect } from '@playwright/test'
import { acct, api, token } from '../helpers'

// Project and task detail fields, through the real API on the seeded company (migration 0009).
test.describe('F25 project and task fields', () => {
  test('F25-H1 task type, labels and hours round-trip; changes need a comment and return to work', async () => {
    const m = await token(acct('mgr')); const e2 = await token(acct('e2'))
    const dir = await api('GET', '/employees/directory', m)
    const e2id = dir.body.items.find((u: any) => u.email === acct('e2')).id
    const proj = (await api('GET', '/projects', m)).body.items[0]
    expect(proj.code).toMatch(/^PRJ-\d{4}$|^[A-Z0-9_-]{2,20}$/)

    const t = await api('POST', `/projects/${proj.id}/tasks`, m, { title: 'Fix redirect', task_type: 'bug', labels: ['web', 'Web'], assignee_id: e2id, estimated_hours: 3 })
    expect(t.status).toBe(201)
    expect(t.body.task_type).toBe('bug'); expect(t.body.labels).toEqual(['web'])

    expect((await api('PATCH', `/tasks/${t.body.id}`, e2, { actual_hours: 2.5, status: 'review' })).status).toBe(200)
    expect((await api('PATCH', `/tasks/${t.body.id}`, e2, { task_type: 'feature' })).status).toBe(403)

    expect((await api('POST', `/tasks/${t.body.id}/review`, m, { approved: false })).status).toBe(422)
    const rej = await api('POST', `/tasks/${t.body.id}/review`, m, { approved: false, note: 'Cover the expired session' })
    expect(rej.body.status).toBe('changes_requested'); expect(rej.body.review_notes).toContain('expired session')

    expect((await api('PATCH', `/tasks/${t.body.id}`, e2, { status: 'review' })).status).toBe(200)
    const done = await api('POST', `/tasks/${t.body.id}/review`, m, { approved: true })
    expect(done.body.status).toBe('done'); expect(done.body.completed_on).toBeTruthy()
    await api('DELETE', `/tasks/${t.body.id}`, m)
  })

  test('F25-N1 invalid risk, code and hours are refused with 4xx, never 500', async () => {
    const m = await token(acct('mgr'))
    for (const bad of [{ risk_level: 'extreme' }, { code: 'a b' }, { estimated_hours: -1 }, { visibility: 'public' }]) {
      const r = await api('POST', '/projects', m, { name: 'Bad input project', ...bad })
      expect(r.status).toBeGreaterThanOrEqual(400); expect(r.status).toBeLessThan(500)
    }
  })

  test('F25-N2 a restricted project is invisible to people who are not on it', async () => {
    const m = await token(acct('mgr')); const e3 = await token(acct('e3'))
    const p = await api('POST', '/projects', m, { name: 'Quiet project', visibility: 'restricted' })
    expect(p.status).toBe(201)
    expect((await api('GET', `/projects/${p.body.id}`, e3)).status).toBe(404)
    await api('PATCH', `/projects/${p.body.id}`, m, { visibility: 'company' })
    const seen = await api('GET', `/projects/${p.body.id}`, e3)
    expect(seen.status).toBe(200); expect(seen.body.can_edit).toBe(false)
    expect((await api('PATCH', `/projects/${p.body.id}`, e3, { name: 'Hijack' })).status).toBe(403)
    await api('DELETE', `/projects/${p.body.id}`, m)
  })
})
