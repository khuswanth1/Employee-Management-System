import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Avatar, Badge, Button, EmptyState, ErrorState, PageHeader, PageLoader, Pagination, ProgressBar, SearchInput, Select } from '../../components/ui'
import { useApi, useDebounce } from '../../lib/hooks'
import { usePersistentState } from '../../lib/usePersistentState'
import { useAuth } from '../auth/AuthContext'
import TeamModal from './TeamModal'

export default function TeamsPage() {
  const { role, user } = useAuth()
  const nav = useNavigate()
  const [q, setQ] = usePersistentState('teams.q', '')
  const [active, setActive] = usePersistentState('teams.active', '')
  const [page, setPage] = useState(1)
  const [creating, setCreating] = useState(false)
  const dq = useDebounce(q)
  const { data, isLoading, error, refetch } = useApi('/teams', { q: dq, active: active || undefined, page, page_size: 12 })
  const canCreate = role === 'founder' || role === 'manager'
  const canSeeAnalytics = ['founder', 'hr', 'manager'].includes(role)

  return (
    <>
      <PageHeader
        title="Teams"
        description={canCreate ? 'Build teams, appoint leaders and allocate projects' : role === 'hr' ? 'Team memberships and transfers' : 'Your team and its projects'}
        actions={<>
          {canSeeAnalytics && <Link to="/teams/analytics" className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">Productivity</Link>}
          {canCreate && <Button onClick={() => setCreating(true)}>+ New team</Button>}
        </>}
      />
      <div className="mb-4 flex flex-wrap gap-3">
        <div className="w-full sm:w-72"><SearchInput value={q} onChange={(v) => { setQ(v); setPage(1) }} placeholder="Search teams" /></div>
        <Select aria-label="Filter by state" className="w-40" value={active} onChange={(e) => { setActive(e.target.value); setPage(1) }}>
          <option value="">All teams</option>
          <option value="true">Active</option>
          <option value="false">Inactive</option>
        </Select>
      </div>
      {isLoading ? <PageLoader /> : error ? <ErrorState error={error} onRetry={refetch} /> : !data.items.length ? (
        <EmptyState
          title="No teams yet"
          description={canCreate ? 'Create a team, choose its leader and allocate projects to it.' : 'You are not part of a team yet. HR or your manager will add you.'}
          action={canCreate && <Button onClick={() => setCreating(true)}>+ New team</Button>}
        />
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {data.items.map((t) => (
              <Link key={t.id} to={`/teams/${t.id}`} className="flex flex-col rounded-xl border border-slate-200 bg-white p-5 shadow-sm transition hover:border-brand-500 hover:shadow-md">
                <div className="mb-2 flex items-start justify-between gap-2">
                  <h2 className="font-semibold text-slate-900">{t.name}</h2>
                  <div className="flex gap-1">
                    {!t.is_active && <Badge>Inactive</Badge>}
                    {t.leader_id === user.id && <Badge tone="indigo">You lead</Badge>}
                  </div>
                </div>
                <p className="mb-3 line-clamp-2 min-h-10 text-sm text-slate-500">{t.description || 'No description'}</p>
                <div className="mb-3 flex items-center gap-2 text-sm text-slate-600">
                  {t.leader ? <><Avatar name={t.leader.full_name} userId={t.leader.id} v={t.leader.avatar_v} size={6} /><span>{t.leader.full_name} <span className="text-slate-500">· leader</span></span></> : <span className="text-amber-700">No team leader</span>}
                </div>
                <ProgressBar value={t.progress} />
                                <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
                  <span>{t.member_count} members · {t.project_count} projects</span>
                  <span className="flex gap-1">
                    {t.overdue_tasks > 0 && <Badge tone="red">{t.overdue_tasks} overdue</Badge>}
                    {t.blocked_tasks > 0 && <Badge tone="amber">{t.blocked_tasks} blocked</Badge>}
                  </span>
                </div>
                                {/* Projects and team members working on them */}
                {t.projects && t.projects.length > 0 && (
                  <div className="mt-3.5 space-y-2.5 border-t border-slate-100 pt-3">
                    <div className="flex items-center justify-between text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                      <span>Projects &amp; Assigned Members</span>
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 font-medium text-slate-600">{t.projects.length} project{t.projects.length > 1 ? 's' : ''}</span>
                    </div>
                    {t.projects.map((proj) => {
                      const workingMembers = proj.active_members && proj.active_members.length > 0 ? proj.active_members : proj.people
                      return (
                        <div key={proj.id} className="rounded-lg border border-slate-200/90 bg-slate-50/70 p-2.5 text-xs transition hover:bg-slate-50">
                          <div className="flex items-center justify-between gap-2 font-medium text-slate-800">
                            <span className="truncate font-semibold text-slate-900">{proj.name}</span>
                            <span className="shrink-0 text-slate-500 font-normal">{proj.done_count}/{proj.task_count} done ({proj.progress}%)</span>
                          </div>
                          <div className="mt-2 space-y-1.5">
                            {workingMembers && workingMembers.length > 0 ? (
                              workingMembers.map((m) => (
                                <div key={m.id} className="flex flex-col gap-1.5 rounded-md bg-white p-2 border border-slate-100 shadow-2xs">
                                  <div className="flex items-center justify-between gap-2">
                                    <div className="flex items-center gap-1.5 min-w-0">
                                      <Avatar name={m.full_name} userId={m.id} v={m.avatar_v} size={5} />
                                      <span className="truncate font-medium text-slate-800">{m.full_name}</span>
                                      <span className="shrink-0 text-[11px] text-slate-500">· {m.designation || m.role}</span>
                                    </div>
                                    <span className="shrink-0 text-[11px] text-slate-500 font-medium">
                                      {m.open_tasks} open{m.done_tasks > 0 ? ` · ${m.done_tasks} done` : ''}
                                    </span>
                                  </div>
                                  {m.tasks && m.tasks.length > 0 ? (
                                    <div className="flex flex-wrap gap-1 pl-6">
                                      {m.tasks.map((tk) => (
                                        <span
                                          key={tk.id}
                                          className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium ${
                                            tk.is_blocked
                                              ? 'bg-amber-50 text-amber-800 border border-amber-200'
                                              : tk.status === 'done'
                                              ? 'bg-emerald-50 text-emerald-700'
                                              : tk.status === 'in_progress'
                                              ? 'bg-blue-50 text-blue-700'
                                              : 'bg-slate-100 text-slate-700'
                                          }`}
                                        >
                                          <span className="truncate max-w-[150px]">{tk.title}</span>
                                          {tk.is_blocked && <span className="font-semibold text-amber-600">[Blocked]</span>}
                                        </span>
                                      ))}
                                    </div>
                                  ) : (
                                    <div className="pl-6 text-[10px] text-slate-500 italic">Allocated to project</div>
                                  )}
                                </div>
                              ))
                            ) : (
                              <span className="text-slate-500 italic text-[11px]">No members assigned yet</span>
                            )}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}
              </Link>
            ))}
          </div>
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onChange={setPage} />
        </>
      )}
      <TeamModal open={creating} onClose={() => setCreating(false)} onSaved={(t) => nav(`/teams/${t.id}`)} />
    </>
  )
}
