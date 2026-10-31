import { useEffect, useState } from 'react'
import { Alert, Badge, Button, Card, EmptyState, ErrorState, Field, Input, Modal, PageHeader, PageLoader, Pagination, Select, StatCard, Table, Tabs, Textarea, useToast } from '../../components/ui'
import { api, download, fieldErrors } from '../../lib/api'
import { fmtDate } from '../../lib/format'
import { useAction, useApi } from '../../lib/hooks'
import { useAuth } from '../auth/AuthContext'
import GoalsCard from './GoalsCard'
import ReviewDialog from './ReviewDialog'
import { CYCLE_TONE, ratingLabel, REVIEW_LABEL, REVIEW_TONE } from './shared'

function useCycle() {
  const { data } = useApi('/performance/cycles')
  const [id, setId] = useState(null)
  const items = data?.items || []
  useEffect(() => { if (!id && items.length) setId((items.find((c) => c.status === 'active') || items[0]).id) }, [items, id])
  return { items, cycle: items.find((c) => c.id === id), setId, loaded: !!data }
}

function CycleSelect({ items, value, onChange }) {
  return <div className="mb-4 w-72"><Field label="Review cycle"><Select value={value || ''} onChange={(e) => onChange(Number(e.target.value))}>{items.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.status})</option>)}</Select></Field></div>
}

// ------------------------------------------------------------------------------- my review

function Mine() {
  const { user } = useAuth()
  const { items, cycle, setId, loaded } = useCycle()
  const [open, setOpen] = useState(null)
  const { data: mine } = useApi('/performance/reviews/mine', { cycle_id: cycle?.id }, { enabled: !!cycle })
  if (!loaded) return <PageLoader />
  if (!items.length) return <EmptyState title="No review cycle yet" description="When HR starts a review cycle you will set goals and write your self review here." />
  const rv = mine?.items?.[0]
  return (
    <>
      <CycleSelect items={items} value={cycle?.id} onChange={setId} />
      {cycle && (
        <div className="space-y-6">
          {rv ? (
            <Card title="My review" action={<Button size="sm" onClick={() => setOpen(rv.id)}>{rv.status === 'pending_self' && cycle.status === 'active' ? 'Write self review' : 'Open'}</Button>}>
              <div className="flex flex-wrap items-center gap-3 text-sm"><Badge tone={REVIEW_TONE[rv.status]}>{REVIEW_LABEL[rv.status]}</Badge>
                {rv.self_due && <span className="text-slate-500">Self review due {fmtDate(rv.self_due)}</span>}
                {rv.status === 'completed' && <strong>Your manager&apos;s review is ready to read.</strong>}
                {rv.manager_rating != null && <span>Final rating: {ratingLabel(cycle.scale, rv.manager_rating)}</span>}</div>
            </Card>
          ) : <Alert tone="amber">You are not part of this cycle.</Alert>}
          {rv && <GoalsCard cycle={cycle} userId={user.id} />}
        </div>
      )}
      {open && <ReviewDialog id={open} onClose={() => setOpen(null)} />}
    </>
  )
}

// ------------------------------------------------------------------------------- team

function Team() {
  const { items, cycle, setId, loaded } = useCycle()
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState('')
  const [open, setOpen] = useState(null)
  const [goalsOf, setGoalsOf] = useState(null)
  const { data, isLoading, error, refetch } = useApi('/performance/reviews', { cycle_id: cycle?.id, status: status || undefined, page, page_size: 15 }, { enabled: !!cycle && cycle.status !== 'draft' })
  const { data: sum } = useApi(`/performance/cycles/${cycle?.id}/summary`, undefined, { enabled: !!cycle && cycle.status !== 'draft' })
  if (!loaded) return <PageLoader />
  if (!items.length) return <EmptyState title="No review cycle yet" />
  return (
    <>
      <CycleSelect items={items} value={cycle?.id} onChange={(v) => { setId(v); setPage(1) }} />
      {cycle?.status === 'draft' ? <Alert tone="amber">This cycle has not started.</Alert> : (<>
        {sum && <div className="mb-4 grid gap-4 sm:grid-cols-4">
          <StatCard title="People" value={sum.participants} />
          <StatCard title="Self reviews in" value={`${sum.completion.self_submitted}/${sum.participants}`} />
          <StatCard title="Manager reviews in" value={`${sum.completion.manager_submitted}/${sum.participants}`} />
          <StatCard title="Average rating" value={sum.average_manager ?? '—'} /></div>}
        <div className="mb-3 w-60"><Field label="Status"><Select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }}><option value="">All</option>{Object.entries(REVIEW_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select></Field></div>
        {error ? <ErrorState error={error} onRetry={refetch} /> : isLoading || !data ? <PageLoader /> : (<>
          <Table caption="Team reviews" rows={data.items} empty={<EmptyState title="Nobody to review" />}
            columns={[
              { key: 'employee', header: 'Employee' },
              { key: 'status', header: 'Status', render: (r) => <Badge tone={REVIEW_TONE[r.status]}>{REVIEW_LABEL[r.status]}</Badge> },
              { key: 'self', header: 'Self', render: (r) => r.self_rating ?? '—' },
              { key: 'mgr', header: 'Manager', render: (r) => r.manager_rating ?? '—' },
              { key: 'a', header: '', render: (r) => <div className="flex gap-1"><Button size="sm" variant="secondary" onClick={() => setOpen(r.id)}>{r.status === 'pending_manager' ? 'Review' : 'Open'}</Button><Button size="sm" variant="ghost" onClick={() => setGoalsOf(r)}>Goals</Button></div> },
            ]} />
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onChange={setPage} />
        </>)}
      </>)}
      {open && <ReviewDialog id={open} onClose={() => setOpen(null)} />}
      {goalsOf && <Modal open wide onClose={() => setGoalsOf(null)} title={`Goals · ${goalsOf.employee}`} footer={<Button variant="secondary" onClick={() => setGoalsOf(null)}>Close</Button>}><GoalsCard cycle={cycle} userId={goalsOf.user_id} manage title="Goals and KPIs" /></Modal>}
    </>
  )
}

// ----------------------------------------------------------------------------- feedback

function Feedback() {
  const [to, setTo] = useState('')
  const [f, setF] = useState({ body: '', kind: 'praise', shared: true })
  const { data: dir } = useApi('/employees/directory')
  const { user } = useAuth()
  const received = useApi('/performance/feedback/received', { page_size: 10 })
  const given = useApi('/performance/feedback/given', { page_size: 10 })
  const send = useAction(() => api.post('/performance/feedback', { to_user_id: Number(to), ...f }), { invalidate: ['/performance/feedback'], success: 'Feedback sent', onSuccess: () => { setF({ body: '', kind: 'praise', shared: true }); setTo('') } })
  const fe = fieldErrors(send.error)
  const people = (dir?.items || []).filter((u) => u.id !== user.id && ['employee', 'manager', 'hr'].includes(u.role))
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card title="Give feedback">
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); send.mutate() }}>
          {send.error && !Object.keys(fe).length && <Alert>{send.error.message}</Alert>}
          <Field label="To" required><Select value={to} onChange={(e) => setTo(e.target.value)}><option value="">Choose a colleague…</option>{people.map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}</Select></Field>
          <Field label="Kind"><Select value={f.kind} onChange={(e) => setF((s) => ({ ...s, kind: e.target.value }))}><option value="praise">Praise</option><option value="constructive">Constructive</option></Select></Field>
          <Field label="Feedback" required error={fe.body}><Textarea value={f.body} onChange={(e) => setF((s) => ({ ...s, body: e.target.value }))} maxLength={2000} /></Field>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.shared} onChange={(e) => setF((s) => ({ ...s, shared: e.target.checked }))} /> Share with them (otherwise only their manager and HR see it)</label>
          <Button type="submit" loading={send.isPending} disabled={!to || f.body.trim().length < 3}>Send</Button>
        </form>
      </Card>
      <div className="space-y-6">
        <Card title="Feedback I received">{received.data?.items?.length ? <ul className="space-y-2 text-sm">{received.data.items.map((x) => <li key={x.id}><strong>{x.from}</strong> <Badge tone={x.kind === 'praise' ? 'green' : 'amber'}>{x.kind}</Badge> · {fmtDate(x.created_at)}<p className="mt-0.5 text-slate-700">{x.body}</p></li>)}</ul> : <EmptyState title="Nothing yet" />}</Card>
        <Card title="Feedback I gave">{given.data?.items?.length ? <ul className="space-y-2 text-sm">{given.data.items.map((x) => <li key={x.id}>To <strong>{x.to}</strong> · {fmtDate(x.created_at)}{!x.shared && ' · private to their manager'}<p className="mt-0.5 text-slate-700">{x.body}</p></li>)}</ul> : <EmptyState title="Nothing yet" />}</Card>
      </div>
    </div>
  )
}

// --------------------------------------------------------------------------------- cycles (HR)

function CycleDialog({ onClose }) {
  const today = new Date().toISOString().slice(0, 10)
  const [f, setF] = useState({ name: '', start_date: today, end_date: '', self_review_due: '', manager_review_due: '', competencies: 'Quality of work, Collaboration, Ownership' })
  const create = useAction(() => api.post('/performance/cycles', { name: f.name.trim(), start_date: f.start_date, end_date: f.end_date, self_review_due: f.self_review_due || null, manager_review_due: f.manager_review_due || null,
    competencies: f.competencies.split(',').map((x) => x.trim()).filter(Boolean) }), { invalidate: ['/performance'], success: 'Cycle created', onSuccess: onClose })
  const fe = fieldErrors(create.error)
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }))
  return (
    <Modal open onClose={onClose} wide title="New review cycle" footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={create.isPending} disabled={f.name.trim().length < 2 || !f.end_date} onClick={() => create.mutate()}>Create</Button></>}>
      <div className="grid gap-4 sm:grid-cols-2">
        {create.error && !Object.keys(fe).length && <div className="sm:col-span-2"><Alert>{create.error.message}</Alert></div>}
        <div className="sm:col-span-2"><Field label="Name" required error={fe.name}><Input value={f.name} onChange={set('name')} maxLength={120} placeholder="2026 annual review" /></Field></div>
        <Field label="Starts" required error={fe.start_date}><Input type="date" value={f.start_date} onChange={set('start_date')} /></Field>
        <Field label="Ends" required error={fe.end_date}><Input type="date" value={f.end_date} min={f.start_date} onChange={set('end_date')} /></Field>
        <Field label="Self reviews due"><Input type="date" value={f.self_review_due} onChange={set('self_review_due')} /></Field>
        <Field label="Manager reviews due" error={fe.manager_review_due}><Input type="date" value={f.manager_review_due} onChange={set('manager_review_due')} /></Field>
        <div className="sm:col-span-2"><Field label="Competencies on the form" hint="Comma separated; everyone is rated on each"><Input value={f.competencies} onChange={set('competencies')} /></Field></div>
      </div>
    </Modal>
  )
}

function Summary({ cycle, onClose }) {
  const { data } = useApi(`/performance/cycles/${cycle.id}/summary`)
  const toast = useToast()
  return (
    <Modal open wide onClose={onClose} title={`Summary · ${cycle.name}`} footer={<><Button variant="secondary" onClick={() => download(`/performance/cycles/${cycle.id}/export.csv`, `performance-${cycle.id}.csv`).catch((e) => toast(e.message, 'red'))}>Export CSV</Button><Button onClick={onClose}>Close</Button></>}>
      {!data ? <PageLoader /> : (
        <div className="space-y-4 text-sm">
          <div className="grid gap-3 sm:grid-cols-4"><StatCard title="People" value={data.participants} /><StatCard title="Manager reviews" value={`${data.completion.manager_submitted}/${data.participants}`} />
            <StatCard title="Acknowledged" value={data.completion.acknowledged} /><StatCard title="Average rating" value={data.average_manager ?? '—'} /></div>
          {(data.overdue.self > 0 || data.overdue.manager > 0) && <Alert tone="amber">Overdue: {data.overdue.self} self review(s), {data.overdue.manager} manager review(s).</Alert>}
          <Table caption="Rating distribution" rows={data.distribution} rowKey={(d) => d.value} columns={[{ key: 'label', header: 'Rating', render: (d) => `${d.value} · ${d.label}` }, { key: 'count', header: 'People' }]} />
          <Table caption="By department" rows={data.by_department} rowKey={(d) => d.department} empty={<p className="p-3 text-slate-500">No submitted reviews yet.</p>} columns={[{ key: 'department', header: 'Department' }, { key: 'reviews', header: 'Reviews' }, { key: 'average', header: 'Average rating' }]} />
          <p className="text-slate-600">Goals: {data.goals.count} agreed, average progress {data.goals.average_progress ?? '—'}%, {data.goals.completed} completed.</p>
        </div>
      )}
    </Modal>
  )
}

function Cycles() {
  const { data, isLoading, error, refetch } = useApi('/performance/cycles')
  const [dlg, setDlg] = useState(null)
  const toast = useToast()
  const act = (path, msg) => useAction((id) => api.post(`/performance/cycles/${id}/${path}`), { invalidate: ['/performance'], success: msg }) // eslint-disable-line react-hooks/rules-of-hooks
  const activate = act('activate', 'Cycle started: reviews were opened'), close = act('close', 'Cycle closed')
  const remind = useAction((id) => api.post(`/performance/cycles/${id}/remind`), { success: (r) => `Reminded ${r.employees} employee(s) and ${r.managers} manager(s)` })
  if (isLoading) return <PageLoader />
  if (error) return <ErrorState error={error} onRetry={refetch} />
  return (
    <>
      <div className="mb-3 flex justify-end"><Button onClick={() => setDlg({ kind: 'new' })}>New cycle</Button></div>
      <Table caption="Review cycles" rows={data.items} empty={<EmptyState title="No cycles yet" />}
        columns={[
          { key: 'name', header: 'Cycle', render: (c) => <>{c.name} <Badge tone={CYCLE_TONE[c.status]}>{c.status}</Badge></> },
          { key: 'dates', header: 'Period', render: (c) => `${fmtDate(c.start_date)} – ${fmtDate(c.end_date)}` },
          { key: 'due', header: 'Due', render: (c) => [c.self_review_due && `self ${fmtDate(c.self_review_due)}`, c.manager_review_due && `manager ${fmtDate(c.manager_review_due)}`].filter(Boolean).join(', ') || '—' },
          { key: 'n', header: 'Reviews', render: (c) => Object.values(c.review_counts || {}).reduce((a, b) => a + b, 0) },
          { key: 'a', header: '', render: (c) => (
            <div className="flex flex-wrap gap-1">
              {c.status === 'draft' && <Button size="sm" onClick={() => window.confirm(`Start "${c.name}"? A review is opened for every employee.`) && activate.mutate(c.id)}>Start</Button>}
              {c.status === 'active' && <><Button size="sm" variant="secondary" onClick={() => remind.mutate(c.id)}>Send reminders</Button><Button size="sm" variant="ghost" onClick={() => window.confirm('Close this cycle? Nothing can be edited afterwards.') && close.mutate(c.id)}>Close</Button></>}
              {c.status !== 'draft' && <Button size="sm" variant="secondary" onClick={() => setDlg({ kind: 'summary', cycle: c })}>Summary</Button>}
            </div>) },
        ]} />
      {dlg?.kind === 'new' && <CycleDialog onClose={() => setDlg(null)} />}
      {dlg?.kind === 'summary' && <Summary cycle={dlg.cycle} onClose={() => setDlg(null)} />}
    </>
  )
}

export default function PerformancePage() {
  const { role } = useAuth()
  const staff = role === 'hr' || role === 'founder'
  const reviewed = role !== 'founder'
  const tabs = [...(reviewed ? [{ id: 'mine', label: 'My review' }] : []), ...(role === 'employee' ? [] : [{ id: 'team', label: 'Team' }]), { id: 'feedback', label: 'Feedback' }, ...(staff ? [{ id: 'cycles', label: 'Cycles' }] : [])]
  const [tab, setTab] = useState(tabs[0].id)
  return (
    <>
      <PageHeader title="Performance" description="Goals, appraisals and feedback." />
      <Tabs value={tab} onChange={setTab} tabs={tabs} />
      <div className="mt-4">
        {tab === 'mine' && <Mine />}
        {tab === 'team' && <Team />}
        {tab === 'feedback' && <Feedback />}
        {tab === 'cycles' && <Cycles />}
      </div>
    </>
  )
}
