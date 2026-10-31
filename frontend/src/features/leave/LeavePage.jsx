import { useMemo, useState } from 'react'
import { Alert, Button, Card, EmptyState, ErrorState, Field, Input, Modal, PageHeader, PageLoader, Pagination, ProgressBar, Table, Tabs, Textarea, Select, StatusBadge } from '../../components/ui'
import { api, fieldErrors } from '../../lib/api'
import { fmtDate } from '../../lib/format'
import { useAction, useApi } from '../../lib/hooks'
import { useAuth } from '../auth/AuthContext'
import HolidayCalendar from './HolidayCalendar'
import LeaveRequestDialog, { iso } from './LeaveRequestDialog'
import LeaveTypeDialog from './LeaveTypeDialog'
import { Badge } from '../../components/ui'

function MonthCalendar({ canSeeTeam }) {
  const [cursor, setCursor] = useState(() => { const d = new Date(); d.setDate(1); return d })
  const first = new Date(cursor), last = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 0)
  const { data } = useApi('/leave/calendar', { start: iso(first), end: iso(last) })
  const cells = useMemo(() => {
    const offset = (first.getDay() + 6) % 7
    return [...Array(offset).fill(null), ...Array.from({ length: last.getDate() }, (_, i) => new Date(cursor.getFullYear(), cursor.getMonth(), i + 1))]
  }, [cursor]) // eslint-disable-line react-hooks/exhaustive-deps
  const hol = Object.fromEntries((data?.holidays || []).map((h) => [h.date, h.name]))
  const on = (d) => (data?.leaves || []).filter((l) => l.start_date <= iso(d) && l.end_date >= iso(d))
  return (
    <Card title={cursor.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })} action={
      <div className="flex gap-1"><Button size="sm" variant="secondary" aria-label="Previous month" onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() - 1, 1))}>←</Button>
        <Button size="sm" variant="secondary" aria-label="Next month" onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1))}>→</Button></div>}>
      <div className="grid grid-cols-7 gap-px overflow-hidden rounded-lg border border-slate-200 bg-slate-200 text-xs" role="grid">
        <div role="row" className="contents">{['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((d) => <div key={d} role="columnheader" className="bg-slate-50 py-1.5 text-center font-semibold text-slate-500">{d}</div>)}</div>
        {Array.from({ length: Math.ceil(cells.length / 7) }, (_, w) => <div key={w} role="row" className="contents">{cells.slice(w * 7, w * 7 + 7).map((d, j) => { const i = w * 7 + j; return (
          <div key={i} role="gridcell" className={`min-h-16 bg-white p-1 ${d && [0, 6].includes(d.getDay()) ? 'bg-slate-50' : ''}`}>
            {d && <>
              <span className={`text-slate-500 ${iso(d) === iso(new Date()) ? 'rounded-full bg-brand-600 px-1.5 py-0.5 font-semibold text-white' : ''}`}>{d.getDate()}</span>
              {hol[iso(d)] && <p className="mt-0.5 truncate rounded bg-purple-100 px-1 text-purple-800" title={hol[iso(d)]}>{hol[iso(d)]}</p>}
              {on(d).slice(0, 2).map((l) => <p key={l.id} className="mt-0.5 truncate rounded bg-sky-100 px-1 text-sky-800" title={`${l.user_name} – ${l.leave_type}`}>{canSeeTeam ? l.user_name.split(' ')[0] : l.leave_type}</p>)}
            </>}
          </div>
        ); })}</div>)}
      </div>
    </Card>
  )
}

const ACCRUAL = { annual_upfront: 'Start of year', monthly: 'Monthly' }

function Policies({ types }) {
  const [dlg, setDlg] = useState(null) // {} = new, {type} = edit
  const run = useAction(() => api.post('/leave/maintenance'), {
    invalidate: ['/leave'], success: (r) => `Year-end run done: ${r.carried_days} days carried, ${r.expired_days} lapsed`,
  })
  return (
    <div className="space-y-6">
      <Card title="Leave types and policies" action={<Button size="sm" onClick={() => setDlg({})}>New leave type</Button>} pad={false}>
        <div className="p-1">
          <Table caption="Leave types" rows={types} empty={<EmptyState title="No leave types" />}
            columns={[
              { key: 'name', header: 'Type', render: (t) => <>{t.name}{!t.paid && <> <Badge>unpaid</Badge></>}{!t.is_active && <> <Badge tone="amber">inactive</Badge></>}</> },
              { key: 'annual_quota', header: 'Days / year' },
              { key: 'accrual', header: 'Granted', render: (t) => ACCRUAL[t.accrual] },
              { key: 'carry', header: 'Carry forward', render: (t) => (t.carry_forward_max ? `up to ${t.carry_forward_max}${t.carry_expiry_months ? `, lapses after month ${t.carry_expiry_months}` : ''}` : '—') },
              { key: 'rules', header: 'Rules', render: (t) => [t.allow_half_day ? 'half days' : null, t.count_all_days ? 'calendar days' : null, t.min_notice_days ? `${t.min_notice_days} d notice` : null, t.encashable ? 'encashable' : null].filter(Boolean).join(', ') || '—' },
              { key: 'a', header: '', render: (t) => <Button size="sm" variant="ghost" onClick={() => setDlg({ type: t })}>Edit</Button> },
            ]} />
        </div>
      </Card>
      <Card title="Year-end and accruals">
        <p className="mb-3 text-sm text-slate-600">Books accruals that are due, carries last year&apos;s unused days into this year (within each type&apos;s limit) and lapses carried days past their expiry month. Running it again changes nothing.</p>
        <Button variant="secondary" loading={run.isPending} onClick={() => run.mutate()}>Run year-end and accruals</Button>
      </Card>
      {dlg && <LeaveTypeDialog type={dlg.type} onClose={() => setDlg(null)} />}
    </div>
  )
}

const KIND = { grant: 'Granted', carry_in: 'Carried in', adjust: 'Adjustment', use: 'Leave taken', refund: 'Refunded', expire: 'Lapsed', encash: 'Encashed' }

function History() {
  const [page, setPage] = useState(1)
  const { data, isLoading, error, refetch } = useApi('/leave/ledger', { page, page_size: 15 })
  if (isLoading) return <PageLoader />
  if (error) return <ErrorState error={error} onRetry={refetch} />
  return (
    <>
      <Table caption="Balance history" rows={data.items} empty={<EmptyState title="No balance changes yet" />}
        columns={[
          { key: 'created_at', header: 'When', render: (e) => fmtDate(e.created_at) },
          { key: 'leave_type', header: 'Type' },
          { key: 'kind', header: 'What', render: (e) => KIND[e.kind] || e.kind },
          { key: 'days', header: 'Days', render: (e) => <span className={e.days < 0 ? 'text-red-700' : 'text-emerald-700'}>{e.days > 0 ? '+' : ''}{e.days}</span> },
          { key: 'note', header: 'Note', render: (e) => e.note || '—' },
        ]} />
      <Pagination page={data.page} pageSize={data.page_size} total={data.total} onChange={setPage} />
    </>
  )
}

const isHrUser = (role) => role === 'hr' || role === 'founder'

export default function LeavePage() {
  const { role } = useAuth()
  const [tab, setTab] = useState('overview')
  const [dialog, setDialog] = useState(null) // { mode: 'new'|'edit'|'revise', request? }
  const [page, setPage] = useState(1)
  const { data: bal, isLoading, error, refetch } = useApi('/leave/balances')
  const { data: types } = useApi('/leave/types', isHrUser(role) ? { include_inactive: true } : undefined)
  const { data: reqs } = useApi('/leave/requests/mine', { page, page_size: 10 })
  const cancel = useAction((id) => api.post(`/leave/requests/${id}/cancel`), { invalidate: ['/leave'], success: 'Request cancelled' })
  const isHr = role === 'hr' || role === 'founder'

  return (
    <>
      <PageHeader title="Leave" description="Balances, applications and holidays" actions={<Button onClick={() => setDialog({ mode: 'new' })}>Apply for leave</Button>} />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: 'overview', label: 'Overview' }, { id: 'history', label: 'History' }, { id: 'calendar', label: 'Calendar' }, { id: 'holidays', label: 'Holidays' }, ...(isHr ? [{ id: 'policies', label: 'Leave policies' }] : [])]} />
      {tab === 'overview' && (isLoading ? <PageLoader /> : error ? <ErrorState error={error} onRetry={refetch} /> : (
        <div className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {bal.items.map((b) => (
              <div key={b.leave_type_id} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
                <p className="text-sm text-slate-500">{b.leave_type}</p>
                <p className="mt-1 text-3xl font-semibold tabular-nums">{b.paid ? b.remaining : b.used}<span className="ml-1 text-sm font-normal text-slate-500">{b.paid ? `of ${b.allocated + b.carried_in} left` : 'taken'}</span></p>
                {b.paid && <div className="mt-3"><ProgressBar value={b.allocated + b.carried_in ? Math.round(((b.used + b.expired + b.encashed) / (b.allocated + b.carried_in)) * 100) : 0} tone="brand" /></div>}
                {b.paid && (b.carried_in > 0 || b.pending > 0 || b.expired > 0 || b.encashed > 0 || b.accrual === 'monthly') && (
                  <p className="mt-2 text-xs text-slate-500">{[b.carried_in > 0 && `${b.carried_in} carried in`, b.pending > 0 && `${b.pending} pending`, b.expired > 0 && `${b.expired} lapsed`, b.encashed > 0 && `${b.encashed} encashed`, b.accrual === 'monthly' && 'accrues monthly'].filter(Boolean).join(' · ')}</p>
                )}
              </div>
            ))}
          </div>
          <div>
            <h2 className="mb-3 text-lg font-semibold">My requests</h2>
            <Table caption="My leave requests" rows={reqs?.items} empty={<EmptyState title="No leave requests" action={<Button onClick={() => setDialog({ mode: 'new' })}>Apply for leave</Button>} />}
              columns={[
                { key: 'leave_type', header: 'Type' }, { key: 'dates', header: 'Dates', render: (r) => `${fmtDate(r.start_date)} → ${fmtDate(r.end_date)}` },
                { key: 'days', header: 'Days', render: (r) => (r.half_day ? `0.5 (${r.half_day} half)` : r.days) }, { key: 'status', header: 'Status', render: (r) => <><StatusBadge value={r.status} />{r.supersedes_id && <> <Badge tone="blue">revision</Badge></>}</> },
                { key: 'decision_note', header: 'Note', render: (r) => r.decision_note || '—' },
                { key: 'act', header: '', render: (r) => (
                  <div className="flex gap-1">
                    {r.status === 'pending' && <Button size="sm" variant="ghost" onClick={() => setDialog({ mode: 'edit', request: r })}>Edit</Button>}
                    {r.status === 'approved' && r.start_date > iso(new Date()) && <Button size="sm" variant="ghost" onClick={() => setDialog({ mode: 'revise', request: r })}>Change</Button>}
                    {(r.status === 'pending' || (r.status === 'approved' && r.start_date > iso(new Date()))) && <Button size="sm" variant="ghost" onClick={() => window.confirm('Cancel this request?') && cancel.mutate(r.id)}>Cancel</Button>}
                  </div>) },
              ]} />
            {reqs && <Pagination page={reqs.page} pageSize={reqs.page_size} total={reqs.total} onChange={setPage} />}
          </div>
        </div>
      ))}
      {tab === 'history' && <History />}
      {tab === 'calendar' && <MonthCalendar canSeeTeam={role !== 'employee'} />}
      {tab === 'holidays' && <div className="max-w-2xl"><HolidayCalendar canEdit={isHr} /></div>}
      {tab === 'policies' && isHr && <Policies types={types?.items || []} />}
      <LeaveRequestDialog open={!!dialog} mode={dialog?.mode} request={dialog?.request} onClose={() => setDialog(null)} types={(types?.items || []).filter((t) => t.is_active !== false)} />
    </>
  )
}
