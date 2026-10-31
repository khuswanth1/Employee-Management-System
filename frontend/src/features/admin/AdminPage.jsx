import { useState } from 'react'
import { Button, Card, EmptyState, ErrorState, Input, PageHeader, PageLoader, Pagination, SearchInput, StatCard, Table, Tabs } from '../../components/ui'
import { api, download } from '../../lib/api'
import { fmtDateTime } from '../../lib/format'
import { useAction, useApi, useDebounce } from '../../lib/hooks'
import { useToast } from '../../components/ui'
import { useAuth } from '../auth/AuthContext'

function AuditLog() {
  const [action, setAction] = useState('')
  const [page, setPage] = useState(1)
  const d = useDebounce(action)
  const { data, isLoading, error, refetch } = useApi('/admin/audit-logs', { action: d, page, page_size: 20 })
  if (isLoading) return <PageLoader />
  if (error) return <ErrorState error={error} onRetry={refetch} />
  return (
    <>
      <div className="mb-4 w-full sm:w-80"><SearchInput value={action} onChange={(v) => { setAction(v); setPage(1) }} placeholder="Filter by action, e.g. employee." /></div>
      <Table caption="Audit log" rows={data.items} empty={<EmptyState title="No audit events" />}
        columns={[{ key: 'created_at', header: 'When', render: (a) => fmtDateTime(a.created_at) }, { key: 'actor_name', header: 'Actor', render: (a) => a.actor_name || '—' },
          { key: 'action', header: 'Action', render: (a) => <code className="text-xs">{a.action}</code> }, { key: 'entity', header: 'Entity', render: (a) => (a.entity_type ? `${a.entity_type}${a.entity_id ? ` #${a.entity_id}` : ''}` : '—') },
          { key: 'detail', header: 'Detail', render: (a) => <code className="line-clamp-1 max-w-xs text-xs text-slate-500">{a.detail ? JSON.stringify(a.detail) : ''}</code> }, { key: 'ip', header: 'IP', render: (a) => a.ip || '—' }]} />
      <Pagination page={data.page} pageSize={data.page_size} total={data.total} onChange={setPage} />
    </>
  )
}

function Settings({ canEdit }) {
  const { data, isLoading } = useApi('/admin/settings')
  const [draft, setDraft] = useState({})
  const save = useAction(({ key, value }) => api.put(`/admin/settings/${key}`, { value }), { invalidate: ['/admin', '/attendance'], success: 'Setting saved' })
  if (isLoading) return <PageLoader />
  return (
    <Card title="Company settings">
      <ul className="divide-y divide-slate-100">{data.items.map((s) => (
        <li key={s.key} className="flex flex-wrap items-center justify-between gap-3 py-3">
          <div><p className="text-sm font-medium">{s.key.replace(/_/g, ' ')}</p><p className="text-xs text-slate-500">{s.description}</p></div>
          <div className="flex items-center gap-2"><Input aria-label={s.key} className="w-40" disabled={!canEdit} value={draft[s.key] ?? s.value} onChange={(e) => setDraft({ ...draft, [s.key]: e.target.value })} />
            {canEdit && <Button size="sm" disabled={draft[s.key] === undefined || draft[s.key] === s.value} loading={save.isPending} onClick={() => save.mutate({ key: s.key, value: draft[s.key] })}>Save</Button>}</div>
        </li>))}</ul>
      {!canEdit && <p className="mt-3 text-xs text-slate-500">Only a founder can change settings.</p>}
    </Card>
  )
}

function Usage() {
  const toast = useToast()
  const { data } = useApi('/admin/usage')
  const exp = (path, name) => download(path, name).catch((e) => toast(e.message, 'red'))
  if (!data) return <PageLoader />
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <StatCard title="Users" value={data.users} hint={`${data.active_users} active`} /><StatCard title="Projects" value={data.projects} /><StatCard title="Tasks" value={data.tasks} /><StatCard title="Audit events" value={data.audit_events} />
      </div>
      <Card title="Report exports">
        <div className="flex flex-wrap gap-3">
          <Button variant="secondary" onClick={() => exp('/reports/attendance.csv', 'attendance.csv')}>Attendance (CSV)</Button>
          <Button variant="secondary" onClick={() => exp('/reports/tasks.csv', 'tasks.csv')}>Tasks (CSV)</Button>
          <Button variant="secondary" onClick={() => exp('/reports/leave.csv', 'leave.csv')}>Leave (CSV)</Button>
        </div>
      </Card>
    </div>
  )
}

export default function AdminPage() {
  const { role } = useAuth()
  const [tab, setTab] = useState('audit')
  return (
    <>
      <PageHeader title="Administration" description="Audit trail, company settings and usage" />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: 'audit', label: 'Audit log' }, { id: 'settings', label: 'Settings' }, { id: 'usage', label: 'Usage & exports' }]} />
      {tab === 'audit' && <AuditLog />}
      {tab === 'settings' && <Settings canEdit={role === 'founder'} />}
      {tab === 'usage' && <Usage />}
    </>
  )
}
