import { useEffect, useState } from 'react'
import { Alert, Button, Card, EmptyState, ErrorState, Field, Input, PageHeader, PageLoader, Pagination, StatusBadge, Textarea } from '../../components/ui'
import { api, fieldErrors } from '../../lib/api'
import { fmtDate, today } from '../../lib/format'
import { useAction, useApi } from '../../lib/hooks'
import { local, userKey } from '../../lib/storage'
import { useAuth } from '../auth/AuthContext'

const blank = { completed: '', hours_worked: 8, pending: '', blockers: '', next_plan: '' }

export default function MyUpdatesPage() {
  const [date, setDate] = useState(today())
  const [page, setPage] = useState(1)
  const { data, isLoading, error, refetch } = useApi('/daily-updates/mine', { page, page_size: 10 })
  const [f, setF] = useState(blank)
  const { user } = useAuth()
  const draftKey = userKey('draft', user.id, `daily-update.${date}`) // unsent text survives a refresh or closed browser
  const [restored, setRestored] = useState(false)
  const existing = data?.items.find((u) => u.work_date === date)

  useEffect(() => {
    const draft = existing ? null : local.get(draftKey, null)
    setRestored(Boolean(draft))
    if (draft) { setF({ ...blank, ...draft }); return }
    setF(existing ? { completed: existing.completed, hours_worked: existing.hours_worked, pending: existing.pending || '', blockers: existing.blockers || '', next_plan: existing.next_plan || '' } : blank)
  }, [existing?.id, existing?.review_status, date]) // eslint-disable-line react-hooks/exhaustive-deps

  const save = useAction(() => api.post('/daily-updates', { ...f, work_date: date, hours_worked: Number(f.hours_worked) }), {
    invalidate: ['/daily-updates', '/dashboard'], success: existing ? 'Update revised' : 'Update submitted',
    onSuccess: () => { local.remove(draftKey); setRestored(false) },
  })
  const fe = fieldErrors(save.error)
  const set = (k) => (e) => {
    const next = { ...f, [k]: e.target.value }
    setF(next)
    if (!existing) local.set(draftKey, next)
  }
  const min = new Date(Date.now() - 7 * 864e5).toISOString().slice(0, 10)

  return (
    <>
      <PageHeader title="Daily work update" description="Tell your manager what you finished, what's blocking you and what's next." />
      <div className="grid gap-6 lg:grid-cols-5">
        <Card title={existing ? 'Edit update' : 'New update'} className="lg:col-span-3">
          <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
            {restored && !existing && (
              <Alert tone="amber">
                Your unsent draft for this day was restored.{' '}
                <button type="button" className="font-medium underline" onClick={() => { local.remove(draftKey); setRestored(false); setF(blank) }}>Discard draft</button>
              </Alert>
            )}
            {save.error && !Object.keys(fe).length && <Alert>{save.error.message}</Alert>}
            {existing && existing.review_status !== 'pending' && (
              <Alert tone={existing.review_status === 'reviewed' ? 'green' : 'amber'}>
                {existing.review_status === 'reviewed' ? 'Reviewed' : 'Changes requested'}{existing.review_comment ? `: ${existing.review_comment}` : ''}. Editing re-submits it for review.
              </Alert>
            )}
            <div className="grid grid-cols-2 gap-3">
              <Field label="Date" required><Input type="date" value={date} min={min} max={today()} onChange={(e) => setDate(e.target.value)} /></Field>
              <Field label="Hours worked" required error={fe.hours_worked}><Input type="number" min="0" max="24" step="0.25" value={f.hours_worked} onChange={set('hours_worked')} /></Field>
            </div>
            <Field label="Completed today" required error={fe.completed}><Textarea rows={4} value={f.completed} onChange={set('completed')} placeholder="What did you finish?" required /></Field>
            <Field label="Pending activities" error={fe.pending}><Textarea value={f.pending} onChange={set('pending')} /></Field>
            <Field label="Blockers" hint="Anything stopping you? Your manager is notified." error={fe.blockers}><Textarea value={f.blockers} onChange={set('blockers')} /></Field>
            <Field label="Plan for next day" error={fe.next_plan}><Textarea value={f.next_plan} onChange={set('next_plan')} /></Field>
            <Button type="submit" loading={save.isPending}>{existing ? 'Update' : 'Submit update'}</Button>
          </form>
        </Card>
        <Card title="History" className="lg:col-span-2" pad={false}>
          {isLoading ? <PageLoader /> : error ? <div className="p-5"><ErrorState error={error} onRetry={refetch} /></div> : !data.items.length ? <div className="p-5"><EmptyState title="No updates yet" /></div> : (
            <>
              <ul className="divide-y divide-slate-100">
                {data.items.map((u) => (
                  <li key={u.id}><button className="w-full px-5 py-3 text-left hover:bg-slate-50" onClick={() => setDate(u.work_date)}>
                    <div className="flex items-center justify-between"><span className="text-sm font-medium">{fmtDate(u.work_date)}</span><StatusBadge value={u.review_status} /></div>
                    <p className="mt-0.5 line-clamp-1 text-sm text-slate-500">{u.completed}</p>
                  </button></li>
                ))}
              </ul>
              <div className="px-5 pb-4"><Pagination page={data.page} pageSize={data.page_size} total={data.total} onChange={setPage} /></div>
            </>
          )}
        </Card>
      </div>
    </>
  )
}
