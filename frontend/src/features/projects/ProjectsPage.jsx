import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Badge, Button, ConfirmDialog, EmptyState, ErrorState, PageHeader, PageLoader, Pagination, ProgressBar, SearchInput, Select, StatusBadge } from '../../components/ui'
import { api } from '../../lib/api'
import { fmtDate } from '../../lib/format'
import { useAction, useApi, useDebounce } from '../../lib/hooks'
import { usePersistentState } from '../../lib/usePersistentState'
import { useAuth } from '../auth/AuthContext'
import ProjectModal from './ProjectModal'

export default function ProjectsPage() {
  const { role } = useAuth()
  const [q, setQ] = usePersistentState('projects.q', '')
  const [status, setStatus] = usePersistentState('projects.status', '')
  const [risk, setRisk] = usePersistentState('projects.risk', '')
  const [page, setPage] = useState(1)
  const nav = useNavigate()
  const [editing, setEditing] = useState(null) // project | 'new' | null
  const [deleting, setDeleting] = useState(null)
  const del = useAction(() => api.del(`/projects/${deleting.id}`), {
    invalidate: ['/projects', '/dashboard', '/tasks'],
    success: 'Project deleted',
    onSuccess: () => setDeleting(null)
  })
  const dq = useDebounce(q)
  const { data, isLoading, error, refetch } = useApi('/projects', { q: dq, status, risk_level: risk, page, page_size: 12 })
  const canCreate = ['manager', 'founder', 'hr'].includes(role)

  return (
    <>
      <PageHeader
        title="Projects"
        description="Track delivery across milestones and tasks"
        actions={canCreate && (
          <Button onClick={() => setEditing('new')}>
            + New project
          </Button>
        )}
      />
      <div className="mb-4 flex flex-wrap gap-3">
        <div className="w-full sm:w-72">
          <SearchInput value={q} onChange={(v) => { setQ(v); setPage(1) }} placeholder="Search name or code" />
        </div>
        <Select aria-label="Filter by status" className="w-44" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }}>
          <option value="">All statuses</option>
          {['planning', 'active', 'on_hold', 'completed'].map((s) => (
            <option key={s} value={s}>{s.replace('_', ' ')}</option>
          ))}
        </Select>
        <Select aria-label="Filter by risk" className="w-40" value={risk} onChange={(e) => { setRisk(e.target.value); setPage(1) }}>
          <option value="">All risk levels</option>
          {['low', 'medium', 'high', 'critical'].map((r) => (
            <option key={r} value={r}>{r[0].toUpperCase() + r.slice(1)} risk</option>
          ))}
        </Select>
      </div>
      {isLoading ? (
        <PageLoader />
      ) : error ? (
        <ErrorState error={error} onRetry={refetch} />
      ) : !data.items.length ? (
        <EmptyState
          title="No projects found"
          description={canCreate ? 'Create your first project to start planning work.' : 'Projects you are part of will appear here.'}
          action={canCreate && (
            <Button onClick={() => setEditing('new')}>
              + New project
            </Button>
          )}
        />
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {data.items.map((p) => (
              <div key={p.id} className="flex flex-col rounded-xl border border-slate-200 bg-white shadow-sm transition hover:border-brand-500 hover:shadow-md">
                <Link to={`/projects/${p.id}`} className="block flex-1 p-5">
                  <div className="mb-2 flex items-start justify-between gap-2">
                    <div className="min-w-0"><h2 className="font-semibold text-slate-900">{p.name}</h2><p className="font-mono text-xs text-slate-500">{p.code}{p.category ? ` · ${p.category}` : ''}</p></div>
                    <StatusBadge value={p.status} />
                  </div>
                  {(p.risk_level === 'high' || p.risk_level === 'critical' || p.visibility === 'company') && (
                    <div className="mb-2 flex gap-1.5">
                      {(p.risk_level === 'high' || p.risk_level === 'critical') && <Badge tone={p.risk_level === 'critical' ? 'red' : 'amber'}>{p.risk_level === 'critical' ? 'Critical risk' : 'High risk'}</Badge>}
                      {p.visibility === 'company' && <Badge tone="blue">Visible to all</Badge>}
                    </div>
                  )}
                  <p className="mb-4 line-clamp-2 min-h-10 text-sm text-slate-500">{p.description || 'No description'}</p>
                  <ProgressBar value={p.progress} />
                  <div className="mt-3 flex justify-between text-xs text-slate-500">
                    <span>{p.done_count}/{p.task_count} tasks done</span>
                    <span>Due {fmtDate(p.due_date)}</span>
                  </div>
                </Link>
                {p.can_edit && (
                  <div className="flex justify-end gap-2 border-t border-slate-100 px-4 py-2 bg-slate-50/50 rounded-b-xl">
                    <Button size="sm" variant="secondary" onClick={() => setEditing(p)} aria-label={`Edit ${p.name}`}>
                      Edit
                    </Button>
                    <Button size="sm" variant="danger" onClick={() => setDeleting(p)} aria-label={`Delete ${p.name}`}>
                      Delete
                    </Button>
                  </div>
                )}
              </div>
            ))}
          </div>
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onChange={setPage} />
        </>
      )}
      <ProjectModal
        open={!!editing}
        onClose={() => setEditing(null)}
        project={editing === 'new' ? null : editing}
        onCreated={(p) => nav(`/projects/${p.id}`)}
      />
      <ConfirmDialog
        open={!!deleting}
        danger
        title="Delete project"
        confirmLabel="Delete project"
        loading={del.isPending}
        onClose={() => setDeleting(null)}
        onConfirm={() => del.mutate()}
        message={`Delete "${deleting?.name}" and all its tasks, milestones and attachments? This cannot be undone.`}
      />
    </>
  )
}
