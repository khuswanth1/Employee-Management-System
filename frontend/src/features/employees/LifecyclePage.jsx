import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge, Card, EmptyState, ErrorState, Field, PageHeader, PageLoader, Pagination, Select, Table, Tabs } from '../../components/ui'
import { fmtDate } from '../../lib/format'
import { useApi } from '../../lib/hooks'
import { describe, EVENT } from './LifecycleTab'

const person = (r) => <Link className="font-medium text-brand-700 hover:underline" to={`/employees/${r.user_id}`}>{r.name}</Link>

function Worklist() {
  const [days, setDays] = useState(30)
  const { data, isLoading, error, refetch } = useApi('/lifecycle/due', { days })
  if (isLoading) return <PageLoader />
  if (error) return <ErrorState error={error} onRetry={refetch} />
  const when = (r) => <>{fmtDate(r.date)} {r.overdue && <Badge tone="red">overdue</Badge>}</>
  return (
    <div className="space-y-6">
      <div className="w-48"><Field label="Look ahead"><Select value={days} onChange={(e) => setDays(Number(e.target.value))}>{[14, 30, 60, 90].map((d) => <option key={d} value={d}>{d} days</option>)}</Select></Field></div>
      <Card title="Probation ending (not yet confirmed)" pad={false}><div className="p-1"><Table caption="Probations" rows={data.probation} rowKey={(r) => r.user_id} empty={<EmptyState title="None in this window" />}
        columns={[{ key: 'name', header: 'Employee', render: person }, { key: 'date', header: 'Probation ends', render: when }]} /></div></Card>
      <Card title="Leaving" pad={false}><div className="p-1"><Table caption="Departures" rows={data.leaving} rowKey={(r) => r.user_id} empty={<EmptyState title="No resignations in this window" />}
        columns={[{ key: 'name', header: 'Employee', render: person }, { key: 'date', header: 'Last working day', render: when }]} /></div>
        <p className="px-5 pb-4 text-xs text-slate-500">When the last day has passed, offboard the person from their record to end their access.</p></Card>
      <Card title="Exit clearance still open" pad={false}><div className="p-1"><Table caption="Exit clearance" rows={data.exit_clearance} rowKey={(r) => r.user_id} empty={<EmptyState title="Nothing outstanding" />}
        columns={[{ key: 'name', header: 'Former employee', render: person }, { key: 'date', header: 'Left', render: (r) => (r.date ? fmtDate(r.date) : '—') }, { key: 'progress', header: 'Cleared', render: (r) => `${r.done} of ${r.total}` }]} /></div></Card>
    </div>
  )
}

function Feed() {
  const [kind, setKind] = useState('')
  const [page, setPage] = useState(1)
  const { data, isLoading, error, refetch } = useApi('/lifecycle/events', { kind: kind || undefined, days: 365, page, page_size: 20 })
  return (
    <>
      <div className="mb-3 w-60"><Field label="Kind"><Select value={kind} onChange={(e) => { setKind(e.target.value); setPage(1) }}><option value="">Everything</option>{Object.entries(EVENT).map(([k, [label]]) => <option key={k} value={k}>{label}</option>)}</Select></Field></div>
      {isLoading ? <PageLoader /> : error ? <ErrorState error={error} onRetry={refetch} /> : (<>
        <Table caption="Lifecycle events" rows={data.items} empty={<EmptyState title="No events" />}
          columns={[
            { key: 'date', header: 'Date', render: (e) => fmtDate(e.effective_date) },
            { key: 'who', header: 'Employee', render: (e) => <Link className="text-brand-700 hover:underline" to={`/employees/${e.user_id}`}>{e.employee}</Link> },
            { key: 'kind', header: 'Event', render: (e) => <Badge tone={EVENT[e.kind]?.[1]}>{EVENT[e.kind]?.[0] || e.kind}</Badge> },
            { key: 'what', header: 'Details', render: (e) => describe(e) || e.note || '—' },
            { key: 'by', header: 'By', render: (e) => e.by || '—' },
          ]} />
        <Pagination page={data.page} pageSize={data.page_size} total={data.total} onChange={setPage} />
      </>)}
    </>
  )
}

export default function LifecyclePage() {
  const [tab, setTab] = useState('due')
  return (
    <>
      <PageHeader title="Employee lifecycle" description="Probations, departures, exit clearance and everything that changed in people's employment." />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: 'due', label: 'Needs attention' }, { id: 'feed', label: 'Activity' }]} />
      <div className="mt-4">{tab === 'due' ? <Worklist /> : <Feed />}</div>
    </>
  )
}
