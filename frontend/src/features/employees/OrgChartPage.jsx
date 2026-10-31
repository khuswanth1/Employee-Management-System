import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Avatar, Button, EmptyState, ErrorState, Field, PageHeader, PageLoader, Select } from '../../components/ui'
import { useApi } from '../../lib/hooks'
import { useAuth } from '../auth/AuthContext'

function Node({ n, depth, open, toggle }) {
  const expanded = open[n.id] ?? depth < 2
  const hasKids = n.children.length > 0
  return (
    <li role="treeitem" aria-expanded={hasKids ? expanded : undefined} aria-level={depth + 1}>
      <div className="flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-slate-50">
        {hasKids ? <button type="button" className="h-6 w-6 rounded text-slate-500 hover:bg-slate-200" aria-label={`${expanded ? 'Collapse' : 'Expand'} ${n.name}`} onClick={() => toggle(n.id, expanded)}>{expanded ? '−' : '+'}</button> : <span className="inline-block h-6 w-6" />}
        <Avatar name={n.name} size={8} userId={n.id} v={n.avatar_v} />
        <div className="min-w-0"><Link to={`/employees/${n.id}`} className="font-medium text-slate-900 hover:underline">{n.name}</Link>
          <p className="truncate text-xs text-slate-500">{[n.designation, n.department, n.branch].filter(Boolean).join(' · ') || n.role}{n.reports ? ` · ${n.reports} in team` : ''}</p></div>
      </div>
      {hasKids && expanded && <ul role="group" className="ml-3 border-l border-slate-200 pl-2 sm:ml-5 sm:pl-3">{n.children.map((c) => <Node key={c.id} n={c} depth={depth + 1} open={open} toggle={toggle} />)}</ul>}
    </li>
  )
}

export default function OrgChartPage() {
  const { role } = useAuth()
  const [f, setF] = useState({ branch_id: '', department_id: '' })
  const [open, setOpen] = useState({})
  const { data, isLoading, error, refetch } = useApi('/org/chart', { branch_id: f.branch_id || undefined, department_id: f.department_id || undefined })
  const { data: depts } = useApi('/departments')
  const { data: branches } = useApi('/branches', undefined, { enabled: role !== 'board_member' })
  const all = (nodes, val) => nodes.reduce((acc, n) => ({ ...acc, [n.id]: val, ...all(n.children, val) }), {})
  return (
    <>
      <PageHeader title="Organisation chart" description="Who reports to whom. Filter by department or branch."
        actions={data && <><Button variant="secondary" onClick={() => setOpen(all(data.roots, true))}>Expand all</Button><Button variant="secondary" onClick={() => setOpen(all(data.roots, false))}>Collapse all</Button></>} />
      <div className="mb-4 flex flex-wrap gap-3">
        <div className="w-56"><Field label="Department"><Select value={f.department_id} onChange={(e) => setF((s) => ({ ...s, department_id: e.target.value }))}><option value="">All</option>{(depts?.items || []).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</Select></Field></div>
        <div className="w-56"><Field label="Branch"><Select value={f.branch_id} onChange={(e) => setF((s) => ({ ...s, branch_id: e.target.value }))}><option value="">All</option>{(branches?.items || []).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</Select></Field></div>
      </div>
      {isLoading ? <PageLoader /> : error ? <ErrorState error={error} onRetry={refetch} /> : !data.roots.length ? <EmptyState title="Nobody matches" /> : (
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white p-3">
          <p className="mb-2 text-xs text-slate-500">{data.total} people</p>
          <ul role="tree" aria-label="Organisation chart">{data.roots.map((n) => <Node key={n.id} n={n} depth={0} open={open} toggle={(id, cur) => setOpen((s) => ({ ...s, [id]: !cur }))} />)}</ul>
        </div>
      )}
    </>
  )
}
