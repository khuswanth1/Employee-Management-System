import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  Alert, Avatar, Badge, Button, Card, ConfirmDialog, EmptyState, ErrorState, Field, Input, Modal, PageHeader, PageLoader, ProgressBar,
  Select, StatCard, StatusBadge, Table, Tabs, Textarea,
} from '../../components/ui'
import { api } from '../../lib/api'
import { fmtDate, fmtDateTime, label, today } from '../../lib/format'
import { useAction, useApi } from '../../lib/hooks'
import { usePersistentState } from '../../lib/usePersistentState'
import { useAuth } from '../auth/AuthContext'
import MultiSelect from '../../components/MultiSelect'
import TaskEditor from '../projects/TaskEditor'
import TeamModal from './TeamModal'

const INV = ['/teams', '/projects', '/tasks', '/dashboard']

/* ---------- overview ---------- */
function Overview({ team }) {
  const monitor = team.can_monitor
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-6">
        <StatCard title="Progress" value={`${team.progress}%`} hint={`${team.done_count}/${team.task_count} tasks done`} />
        <StatCard title="Open tasks" value={team.open_tasks} />
        <StatCard title="Overdue" value={team.overdue_tasks} tone="danger" />
        <StatCard title="Blocked" value={team.blocked_tasks} tone="danger" />
        <StatCard title="Done (30 days)" value={team.done_last_30d} />
        <StatCard title="On-time delivery" value={team.on_time_rate == null ? '—' : `${team.on_time_rate}%`} />
      </div>
      {monitor && (team.blockers.tasks.length > 0 || team.blockers.updates.length > 0) && (
        <Card title="Blockers needing attention">
          <ul className="space-y-2 text-sm">
            {team.blockers.tasks.map((b) => (
              <li key={`t${b.task_id}`} className="flex flex-wrap items-center gap-2">
                <Badge tone="amber">Task</Badge>
                <Link className="font-medium text-brand-700 hover:underline" to={`/projects/${b.project_id}`}>{b.title}</Link>
                <span className="text-slate-500">{b.assignee_name}{b.note ? ` — ${b.note}` : ''}</span>
              </li>
            ))}
            {team.blockers.updates.map((b) => (
              <li key={`u${b.update_id}`} className="flex flex-wrap items-center gap-2">
                <Badge tone="red">Daily update</Badge>
                <span className="font-medium">{b.full_name}</span>
                <span className="text-slate-500">{fmtDate(b.work_date)} — {b.blockers}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
      <Card title="Project progress &amp; Assigned Members">
        {!team.projects.length ? <p className="text-sm text-slate-500">No projects allocated yet.</p> : (
          <ul className="divide-y divide-slate-100">
            {team.projects.map((p) => {
              const workingMembers = (p.people || []).filter((m) => m.tasks && m.tasks.length > 0)
              const displayMembers = workingMembers.length > 0 ? workingMembers : (p.people || [])
              return (
                <li key={p.id} className="py-4">
                  <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
                    <Link to={`/projects/${p.id}`} className="font-semibold text-slate-900 hover:text-brand-700">{p.name}</Link>
                    <div className="flex items-center gap-2 text-xs text-slate-500">
                      <StatusBadge value={p.status} />
                      {monitor && p.overdue_tasks > 0 && <Badge tone="red">{p.overdue_tasks} overdue</Badge>}
                      {monitor && p.unassigned_tasks > 0 && <Badge tone="amber">{p.unassigned_tasks} unassigned</Badge>}
                      <span>Due {fmtDate(p.due_date)}</span>
                    </div>
                  </div>
                  <ProgressBar value={p.progress} />
                  <p className="mt-1.5 text-xs text-slate-500">
                    {p.done_count}/{p.task_count} tasks · milestones {p.milestones_done}/{p.milestones_total}
                    {p.next_milestone && ` · next: ${p.next_milestone.title} (${fmtDate(p.next_milestone.due_date)})`}
                    {monitor && p.overdue_milestones > 0 && <span className="text-red-600"> · {p.overdue_milestones} milestone(s) overdue</span>}
                  </p>
                  {displayMembers.length > 0 && (
                    <div className="mt-3 rounded-lg border border-slate-200/80 bg-slate-50/70 p-3">
                      <div className="mb-2 flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-slate-500">
                        <span>Team members working on this project</span>
                        <span>{displayMembers.length} member{displayMembers.length > 1 ? 's' : ''}</span>
                      </div>
                      <div className="grid gap-2 sm:grid-cols-2">
                        {displayMembers.map((m) => (
                          <div key={m.id} className="rounded-lg border border-slate-200/80 bg-white p-2.5 shadow-2xs">
                            <div className="flex items-center justify-between gap-2">
                              <div className="flex items-center gap-2 min-w-0">
                                <Avatar name={m.full_name} userId={m.id} v={m.avatar_v} size={6} />
                                <div className="min-w-0">
                                  <div className="font-medium text-slate-900 text-xs truncate">{m.full_name}</div>
                                  <div className="text-[11px] text-slate-500 truncate">{m.designation || label(m.role)}</div>
                                </div>
                              </div>
                              <span className="shrink-0 text-[11px] font-medium text-slate-500">
                                {m.open_tasks} open{m.done_tasks > 0 ? ` · ${m.done_tasks} done` : ''}
                              </span>
                            </div>
                            {m.tasks && m.tasks.length > 0 ? (
                              <div className="mt-2 space-y-1">
                                {m.tasks.map((t) => (
                                  <div key={t.id} className="flex items-center justify-between text-[11px] text-slate-600 bg-slate-50 rounded px-2 py-1">
                                    <span className="truncate max-w-[180px]">{t.title}</span>
                                    <div className="flex items-center gap-1 shrink-0">
                                      {t.is_blocked && <span className="text-amber-600 font-semibold">[Blocked]</span>}
                                      <StatusBadge value={t.status} />
                                    </div>
                                  </div>
                                ))}
                              </div>
                            ) : (
                              <div className="mt-1 text-[10px] text-slate-500 italic">Allocated to project</div>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </Card>
      <Card title="Team Workload & Progress" pad={false}>
        <Table caption="Team workload" rows={team.members} columns={[
          { key: 'n', header: 'Member', render: (m) => (
            <div className="flex items-center gap-2">
              <Avatar name={m.full_name} userId={m.id} v={m.avatar_v} size={6} />
              <div>
                <span className="font-medium text-slate-900">{m.full_name}</span>
                {m.is_leader && <Badge tone="indigo" className="ml-1.5">Leader</Badge>}
                <div className="text-xs text-slate-500">{m.designation || label(m.role)}</div>
              </div>
            </div>
          ) },
          { key: 'o', header: 'Open tasks', render: (m) => {
            const count = m.open_tasks ?? (m.projects?.reduce((acc, p) => acc + (p.tasks?.filter((t) => t.status !== 'done').length || 0), 0) || 0)
            return <span className="font-medium text-slate-800">{count}</span>
          } },
          ...(monitor ? [{ key: 'ov', header: 'Overdue', render: (m) => <span className={m.overdue_tasks ? 'font-medium text-red-600' : 'text-slate-500'}>{m.overdue_tasks || '0'}</span> }] : []),
          { key: 'b', header: 'Blocked', render: (m) => {
            const blocked = m.blocked_tasks ?? (m.projects?.reduce((acc, p) => acc + (p.tasks?.filter((t) => t.is_blocked).length || 0), 0) || 0)
            return <span className={blocked ? 'font-medium text-amber-700' : 'text-slate-500'}>{blocked || '0'}</span>
          } },
          { key: 'd', header: 'Done', render: (m) => {
            const done = m.done_count ?? (m.projects?.reduce((acc, p) => acc + (p.tasks?.filter((t) => t.status === 'done').length || 0), 0) || 0)
            return <span className="text-slate-600">{done}</span>
          } },
          { key: 'p', header: 'Progress', className: 'w-44', render: (m) => {
            const open = m.open_tasks ?? (m.projects?.reduce((acc, p) => acc + (p.tasks?.filter((t) => t.status !== 'done').length || 0), 0) || 0)
            const done = m.done_count ?? (m.projects?.reduce((acc, p) => acc + (p.tasks?.filter((t) => t.status === 'done').length || 0), 0) || 0)
            const total = open + done
            const prog = m.progress ?? (total > 0 ? Math.round((done / total) * 100) : 0)
            return (
              <div className="space-y-1">
                <div className="text-right text-[11px] text-slate-500">{prog}%</div>
                <ProgressBar value={prog} />
              </div>
            )
          } },
        ]} />
      </Card>
    </div>
  )
}

/* ---------- members ---------- */
function AddMembers({ team, onClose }) {
  const { data } = useApi('/teams/available', { branch_id: team.branch_id || undefined })
  const [ids, setIds] = useState([])
  const add = useAction(() => api.post(`/teams/${team.id}/members`, { user_ids: ids }), { invalidate: INV, success: 'Members added', onSuccess: onClose })
  return (
    <Modal open onClose={onClose} title="Add members" footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button disabled={!ids.length} loading={add.isPending} onClick={() => add.mutate()}>Add {ids.length || ''} member(s)</Button></>}>
      <div className="space-y-3">
        {add.error && <Alert>{add.error.message}</Alert>}
        <Field label="People without a team" hint="Search by name. People already in a team are moved by HR with a transfer.">
          <MultiSelect options={(data?.items || []).map((p) => ({ value: p.id, label: p.full_name, hint: p.designation || label(p.role) }))} value={ids} onChange={setIds} />
        </Field>
        {data && !data.items.length && <p className="text-sm text-slate-500">Everyone eligible is already in a team.</p>}
      </div>
    </Modal>
  )
}

function Transfer({ team, member, onClose }) {
  const { data } = useApi('/teams', { active: true, page_size: 100 })
  const [to, setTo] = useState('')
  const [note, setNote] = useState('')
  const go = useAction(() => api.post('/teams/transfer', { user_id: member.id, to_team_id: Number(to), note: note || null }), {
    invalidate: INV, onSuccess: (r) => { onClose(r) },
    success: (r) => `Transferred${r.branch_changed ? ' (branch changed)' : ''}${r.unassigned_tasks ? ` · ${r.unassigned_tasks} open task(s) unassigned` : ''}`,
  })
  const options = (data?.items || []).filter((t) => t.id !== team.id)
  return (
    <Modal open onClose={() => onClose()} title={`Transfer ${member.full_name}`} footer={<><Button variant="secondary" onClick={() => onClose()}>Cancel</Button><Button disabled={!to} loading={go.isPending} onClick={() => go.mutate()}>Transfer</Button></>}>
      <div className="space-y-4">
        {go.error && <Alert>{go.error.message}</Alert>}
        <Alert tone="amber">Open tasks they hold in {team.name}'s projects become unassigned and the leaders are notified.</Alert>
        <Field label="Destination team">
          <Select value={to} onChange={(e) => setTo(e.target.value)}>
            <option value="">Choose a team…</option>
            {options.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </Select>
        </Field>
        <Field label="Note (optional)"><Input value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} placeholder="Reason for the transfer" /></Field>
      </div>
    </Modal>
  )
}

function Members({ team }) {
  const { role } = useAuth()
  const nav = useNavigate()
  const [adding, setAdding] = useState(false)
  const [moving, setMoving] = useState(null)
  const setLeader = useAction((user_id) => api.put(`/teams/${team.id}/leader`, { user_id }), { invalidate: INV, success: 'Leader updated' })
  const remove = useAction((id) => api.del(`/teams/${team.id}/members/${id}`), {
    invalidate: INV, success: (r) => `Removed${r.unassigned_tasks ? ` · ${r.unassigned_tasks} open task(s) unassigned` : ''}`,
  })
  const monitor = team.can_monitor
  const canTransfer = role === 'hr' || role === 'founder'
  const cols = [
    { key: 'n', header: 'Member', render: (m) => (
      <div className="flex items-center gap-2.5">
        <Avatar name={m.full_name} userId={m.id} v={m.avatar_v} size={8} />
        <div>
          <div className="flex items-center gap-1.5">
            <span className="font-semibold text-slate-900">{m.full_name}</span>
            {m.is_leader && <Badge tone="indigo">Leader</Badge>}
          </div>
          <div className="text-xs text-slate-500">{m.designation || label(m.role)}</div>
          <div className="text-[11px] text-slate-500">{m.email}</div>
        </div>
      </div>
    ) },
    { key: 'proj', header: 'Project & Assigned Tasks', render: (m) => {
      if (!m.projects || m.projects.length === 0) {
        return <span className="text-xs text-slate-500 italic">No project assigned</span>
      }
      return (
        <div className="space-y-2 py-1 max-w-md">
          {m.projects.map((p) => (
            <div key={p.id} className="rounded-lg border border-slate-200/80 bg-slate-50/60 p-2">
              <div className="flex items-center justify-between gap-2 mb-1.5">
                <Link to={`/projects/${p.id}`} className="font-semibold text-xs text-brand-700 hover:underline">
                  {p.name}
                </Link>
                <span className="text-[11px] text-slate-500 font-medium">
                  {p.tasks_count} task{p.tasks_count !== 1 ? 's' : ''}
                </span>
              </div>
              {p.tasks && p.tasks.length > 0 ? (
                <div className="space-y-1">
                  {p.tasks.map((t) => (
                    <div key={t.id} className="flex items-center justify-between gap-2 rounded bg-white px-2 py-1 text-[11px] border border-slate-100 shadow-2xs">
                      <div className="flex items-center gap-1.5 min-w-0">
                        <span className={`inline-block h-1.5 w-1.5 rounded-full shrink-0 ${t.status === 'done' ? 'bg-emerald-500' : t.is_blocked ? 'bg-amber-500' : 'bg-blue-500'}`} />
                        <span className="truncate text-slate-700 font-medium max-w-[190px]">{t.title}</span>
                      </div>
                      <div className="flex items-center gap-1 shrink-0">
                        {t.is_blocked && <span className="rounded bg-amber-100 px-1 py-0.2 text-[9px] font-semibold text-amber-800">Blocked</span>}
                        {t.priority === 'high' && <span className="rounded bg-rose-50 px-1 py-0.2 text-[9px] font-medium text-rose-700">High</span>}
                        {t.progress > 0 && t.status !== 'done' && <span className="text-[10px] text-slate-500">{t.progress}%</span>}
                        <StatusBadge value={t.status} />
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-[11px] text-slate-500 italic">No tasks assigned in this project</div>
              )}
            </div>
          ))}
        </div>
      )
    } },
    { key: 'stats', header: 'Workload & Progress', className: 'w-44', render: (m) => {
      const openCount = m.open_tasks ?? (m.projects?.reduce((acc, p) => acc + (p.tasks?.filter((t) => t.status !== 'done').length || 0), 0) || 0)
      const doneCount = m.done_count ?? (m.projects?.reduce((acc, p) => acc + (p.tasks?.filter((t) => t.status === 'done').length || 0), 0) || 0)
      const blockedCount = m.blocked_tasks ?? (m.projects?.reduce((acc, p) => acc + (p.tasks?.filter((t) => t.is_blocked).length || 0), 0) || 0)
      const totalCount = openCount + doneCount
      const progressVal = m.progress ?? (totalCount > 0 ? Math.round((doneCount / totalCount) * 100) : 0)
      return (
        <div className="space-y-1">
          <div className="flex items-center justify-between text-xs">
            <span className="text-slate-700 font-medium">{openCount} open</span>
            <span className="text-slate-500">{doneCount} done</span>
          </div>
          <ProgressBar value={progressVal} />
          <div className="flex items-center justify-between text-[10px] text-slate-500">
            <span>{progressVal}% complete</span>
            {blockedCount > 0 && <span className="text-amber-600 font-semibold">{blockedCount} blocked</span>}
          </div>
        </div>
      )
    } },
    ...(monitor ? [
      { key: 'ov', header: 'Overdue', render: (m) => <span className={m.overdue_tasks ? 'font-medium text-red-600' : 'text-slate-500'}>{m.overdue_tasks || '0'}</span> },
      { key: 'lu', header: 'Last update', render: (m) => fmtDate(m.last_update) || '—' },
    ] : []),
    { key: 'chat', header: '', render: (m) => <Link className="rounded border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-brand-700 hover:bg-slate-50" to="/chat">Message</Link> },
    ...(team.can_manage_members ? [{ key: 'act', header: '', className: 'whitespace-nowrap text-right', render: (m) => (
      <div className="flex justify-end gap-3">
        {team.can_manage && !m.is_leader && ['employee', 'manager'].includes(m.role) && (
          <button className="text-brand-700 hover:underline" onClick={() => setLeader.mutate(m.id)}>{team.leader_id ? 'Make leader' : 'Appoint leader'}</button>
        )}
        {team.can_manage && m.is_leader && <button className="text-slate-600 hover:underline" onClick={() => setLeader.mutate(null)}>Clear leader</button>}
        {canTransfer && <button className="text-brand-700 hover:underline" onClick={() => setMoving(m)}>Transfer</button>}
        {(!m.is_leader || team.can_manage || role === 'hr') && <button className="text-red-600 hover:underline" onClick={() => window.confirm(`Remove ${m.full_name} from ${team.name}?`) && remove.mutate(m.id)}>Remove</button>}
      </div>
    ) }] : []),
  ]
  return (
    <>
      <div className="mb-3 flex justify-end">
        {team.can_manage_members && team.is_active && <Button onClick={() => setAdding(true)}>+ Add members</Button>}
      </div>
      <Table caption="Team members" rows={team.members} columns={cols} empty={<EmptyState title="No members yet" description="Add people to start assigning work." />} />
      {adding && <AddMembers team={team} onClose={() => setAdding(false)} />}
      {moving && <Transfer team={team} member={moving} onClose={(r) => { setMoving(null); if (r?.to_team_id) nav(`/teams/${r.to_team_id}`) }} />}
    </>
  )
}

/* ---------- projects ---------- */
function Allocate({ team, onClose }) {
  const { data } = useApi('/projects', { page_size: 100 })
  const [pid, setPid] = useState('')
  const taken = new Set(team.projects.map((p) => p.id))
  const options = (data?.items || []).filter((p) => p.can_edit && !taken.has(p.id))
  const go = useAction(() => api.post(`/teams/${team.id}/projects`, { project_id: Number(pid) }), { invalidate: INV, success: 'Project allocated', onSuccess: onClose })
  return (
    <Modal open onClose={onClose} title="Allocate a project" footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button disabled={!pid} loading={go.isPending} onClick={() => go.mutate()}>Allocate</Button></>}>
      <div className="space-y-3">
        {go.error && <Alert>{go.error.message}</Alert>}
        <Field label="Project" hint="You can allocate projects you own. Team members and the leader get access to it.">
          <Select value={pid} onChange={(e) => setPid(e.target.value)}>
            <option value="">Choose a project…</option>
            {options.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </Select>
        </Field>
        {data && !options.length && <p className="text-sm text-slate-500">No further projects available. <Link className="text-brand-700 hover:underline" to="/projects">Create one first</Link>.</p>}
      </div>
    </Modal>
  )
}

function Projects({ team }) {
  const [allocating, setAllocating] = useState(false)
  const [taskIn, setTaskIn] = useState(null)
  const drop = useAction((pid) => api.del(`/teams/${team.id}/projects/${pid}`), { invalidate: INV, success: 'Project removed from team' })
  const canTask = (team.can_lead || team.can_manage) && team.is_active
  return (
    <>
      <div className="mb-3 flex justify-end">{team.can_manage && team.is_active && <Button onClick={() => setAllocating(true)}>+ Allocate project</Button>}</div>
      {!team.projects.length ? <EmptyState title="No projects allocated" description={team.can_manage ? 'Allocate a project you own to give this team work.' : 'Projects allocated to this team appear here.'} /> : (
        <div className="grid gap-4 md:grid-cols-2">
          {team.projects.map((p) => (
            <Card key={p.id} title={<Link to={`/projects/${p.id}`} className="hover:text-brand-700">{p.name}</Link>} action={<StatusBadge value={p.status} />}>
              <ProgressBar value={p.progress} />
              <p className="mt-2 text-xs text-slate-500">{p.done_count}/{p.task_count} tasks · milestones {p.milestones_done}/{p.milestones_total} · due {fmtDate(p.due_date)}</p>
              <div className="mt-4">
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Team members on this project</h3>
                <ul className="space-y-2">
                  {p.people.map((m) => (
                    <li key={m.id} className="rounded-lg border border-slate-100 bg-slate-50/60 p-2.5">
                      <div className="flex items-center gap-2 text-sm">
                        <Avatar name={m.full_name} userId={m.id} v={m.avatar_v} size={6} />
                        <span className="font-medium text-slate-900">{m.full_name}</span>
                        {m.is_leader && <Badge tone="indigo">Leader</Badge>}
                        <span className="text-xs text-slate-500">{m.designation || label(m.role)}</span>
                        <span className="ml-auto text-xs text-slate-500">{m.open_tasks} open · {m.done_tasks} done</span>
                      </div>
                      {m.tasks.length > 0 ? (
                        <ul className="mt-2 space-y-1.5 pl-8 text-xs">
                          {m.tasks.map((t) => (
                            <li key={t.id} className="flex flex-wrap items-center justify-between gap-2 rounded bg-white px-2 py-1 border border-slate-100">
                              <span className="text-slate-800 font-medium truncate max-w-[240px]">{t.title}</span>
                              <div className="flex items-center gap-1.5 shrink-0">
                                {t.is_blocked && <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-800">Blocked</span>}
                                {t.priority === 'high' && <span className="rounded bg-rose-50 px-1.5 py-0.5 text-[10px] font-medium text-rose-700">High</span>}
                                {t.progress > 0 && t.status !== 'done' && <span className="text-[10px] text-slate-500">{t.progress}%</span>}
                                <StatusBadge value={t.status} />
                                {t.due_date && <span className="text-[11px] text-slate-500">due {fmtDate(t.due_date)}</span>}
                              </div>
                            </li>
                          ))}
                        </ul>
                      ) : <p className="mt-1 pl-8 text-xs text-slate-500 italic">No tasks assigned yet</p>}
                    </li>
                  ))}
                </ul>
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <Link to={`/projects/${p.id}`} className="rounded-lg border border-slate-300 px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50">Open board</Link>
                {canTask && <Button size="sm" onClick={() => setTaskIn(p.id)}>+ Assign task</Button>}
                {team.can_manage && <Button size="sm" variant="danger" onClick={() => window.confirm(`Remove ${p.name} from this team?`) && drop.mutate(p.id)}>Remove</Button>}
              </div>
            </Card>
          ))}
        </div>
      )}
      {allocating && <Allocate team={team} onClose={() => setAllocating(false)} />}
      <TaskEditor open={!!taskIn} onClose={() => setTaskIn(null)} projectId={taskIn} task={null} />
    </>
  )
}

/* ---------- daily updates ---------- */
function Updates({ team }) {
  const [day, setDay] = useState(today())
  const { data, isLoading, error, refetch } = useApi(`/teams/${team.id}/updates`, { work_date: day })
  const canReview = team.can_lead || team.can_manage
  const review = useAction(({ id, status, comment }) => api.post(`/teams/${team.id}/updates/${id}/review`, { status, comment }), { invalidate: ['/teams'], success: 'Review saved' })
  return (
    <>
      <div className="mb-4 flex flex-wrap items-end gap-4">
        <Field label="Date"><Input type="date" max={today()} value={day} onChange={(e) => setDay(e.target.value)} /></Field>
        {data && <p className="pb-2 text-sm text-slate-600"><b>{data.submitted}</b> submitted · <b className={data.missing ? 'text-amber-700' : ''}>{data.missing}</b> missing</p>}
      </div>
      {isLoading ? <PageLoader /> : error ? <ErrorState error={error} onRetry={refetch} /> : (
        <div className="space-y-3">
          {data.items.map((i) => (
            <Card key={i.user_id} title={i.full_name} action={i.submitted ? <StatusBadge value={i.update.review_status} /> : <Badge tone="amber">Not submitted</Badge>}>
              {i.update ? (
                <div className="space-y-2 text-sm">
                  <p><span className="font-medium text-slate-700">Completed ({i.update.hours_worked}h):</span> {i.update.completed}</p>
                  {i.update.pending && <p><span className="font-medium text-slate-700">Pending:</span> {i.update.pending}</p>}
                  {i.update.blockers && <p className="rounded-lg bg-amber-50 px-3 py-2 text-amber-900"><span className="font-medium">Blockers:</span> {i.update.blockers}</p>}
                  {i.update.next_plan && <p><span className="font-medium text-slate-700">Next:</span> {i.update.next_plan}</p>}
                  {i.update.review_comment && <p className="text-slate-500">Review: {i.update.review_comment}</p>}
                  {canReview && (
                    <div className="flex gap-2 pt-1">
                      <Button size="sm" onClick={() => review.mutate({ id: i.update.id, status: 'reviewed' })}>Mark reviewed</Button>
                      <Button size="sm" variant="secondary" onClick={() => { const c = window.prompt('What needs to change?'); if (c) review.mutate({ id: i.update.id, status: 'needs_changes', comment: c }) }}>Needs changes</Button>
                    </div>
                  )}
                </div>
              ) : <p className="text-sm text-slate-500">Nothing submitted for {fmtDate(day)}.</p>}
            </Card>
          ))}
        </div>
      )}
    </>
  )
}

/* ---------- reports ---------- */
function Reports({ team }) {
  const { data, isLoading } = useApi(`/teams/${team.id}/reports`)
  const [f, setF] = useState({ summary: '', health: 'on_track', project_id: '' })
  const send = useAction(() => api.post(`/teams/${team.id}/reports`, { summary: f.summary, health: f.health, project_id: f.project_id ? Number(f.project_id) : null }), {
    invalidate: [`/teams/${team.id}/reports`], success: 'Report sent to the manager', onSuccess: () => setF({ summary: '', health: 'on_track', project_id: '' }),
  })
  const tone = { on_track: 'green', at_risk: 'amber', blocked: 'red' }
  return (
    <div className="space-y-6">
      {team.can_lead && (
        <Card title="Report progress to your manager">
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); send.mutate() }}>
            {send.error && <Alert>{send.error.message}</Alert>}
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Overall health">
                <Select value={f.health} onChange={(e) => setF({ ...f, health: e.target.value })}>
                  <option value="on_track">On track</option><option value="at_risk">At risk</option><option value="blocked">Blocked</option>
                </Select>
              </Field>
              <Field label="Project (optional)">
                <Select value={f.project_id} onChange={(e) => setF({ ...f, project_id: e.target.value })}>
                  <option value="">Whole team</option>
                  {team.projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                </Select>
              </Field>
            </div>
            <Field label="Summary" required><Textarea rows={4} value={f.summary} onChange={(e) => setF({ ...f, summary: e.target.value })} placeholder="Progress, risks, blockers and what you need from the manager" /></Field>
            <Button type="submit" disabled={f.summary.trim().length < 3} loading={send.isPending}>Send report</Button>
          </form>
        </Card>
      )}
      {isLoading ? <PageLoader /> : !data.items.length ? <EmptyState title="No reports yet" description="Reports from the team leader appear here." /> : (
        <ul className="space-y-3">
          {data.items.map((r) => (
            <li key={r.id} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="mb-1 flex items-center justify-between gap-2">
                <span className="text-sm font-medium text-slate-900">{r.author_name || 'Former leader'} <span className="font-normal text-slate-500">· {fmtDateTime(r.created_at)}</span></span>
                <Badge tone={tone[r.health]}>{label(r.health)}</Badge>
              </div>
              <p className="whitespace-pre-wrap text-sm text-slate-700">{r.summary}</p>
              {r.project_id && <p className="mt-1 text-xs text-slate-500">Project: {team.projects.find((p) => p.id === r.project_id)?.name || `#${r.project_id}`}</p>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/* ---------- header dialogs ---------- */
function Reassign({ team, onClose }) {
  const { data } = useApi('/employees/directory')
  const [mid, setMid] = useState('')
  const options = (data?.items || []).filter((u) => u.role === 'manager' && u.id !== team.manager_id && (!team.branch_id || !u.branch_id || u.branch_id === team.branch_id))
  const go = useAction(() => api.post(`/teams/${team.id}/reassign`, { manager_id: Number(mid) }), { invalidate: INV, success: 'Team reassigned', onSuccess: onClose })
  return (
    <Modal open onClose={onClose} title="Reassign team" footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button disabled={!mid} loading={go.isPending} onClick={() => go.mutate()}>Reassign</Button></>}>
      <div className="space-y-3">
        {go.error && <Alert>{go.error.message}</Alert>}
        <Alert tone="amber">The new manager takes over this team, its project allocation and its reports. You may lose access if you are not a founder.</Alert>
        <Field label="New managing manager">
          <Select value={mid} onChange={(e) => setMid(e.target.value)}>
            <option value="">Choose a manager…</option>
            {options.map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}
          </Select>
        </Field>
      </div>
    </Modal>
  )
}

export default function TeamDetailPage() {
  const { id } = useParams()
  const nav = useNavigate()
  const [tab, setTab] = usePersistentState(`team.${id}.tab`, 'overview', { store: 'session' })
  const [editing, setEditing] = useState(false)
  const [reassigning, setReassigning] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const { data: team, isLoading, error, refetch } = useApi(`/teams/${id}`)
  const toggle = useAction(() => api.patch(`/teams/${id}`, { is_active: !team.is_active }), { invalidate: INV, success: () => (team.is_active ? 'Team deactivated' : 'Team reactivated') })
  const del = useAction(() => api.del(`/teams/${id}`), { invalidate: INV, success: 'Team deleted', onSuccess: () => nav('/teams') })
  const tabs = useMemo(() => {
    if (!team) return []
    return [
      { id: 'overview', label: 'Overview' }, { id: 'members', label: `Members (${team.member_count})` }, { id: 'projects', label: `Projects (${team.project_count})` },
      ...(team.can_monitor ? [{ id: 'updates', label: 'Daily updates' }, { id: 'reports', label: 'Reports' }] : []),
    ]
  }, [team])

  if (isLoading) return <PageLoader />
  if (error) return <ErrorState error={error} onRetry={refetch} />
  return (
    <>
      <PageHeader
        title={team.name}
        description={team.description || 'No description'}
        actions={team.can_manage && <>
          <Button variant="secondary" onClick={() => setEditing(true)}>Edit</Button>
          <Button variant="secondary" onClick={() => setReassigning(true)}>Reassign</Button>
          <Button variant="secondary" loading={toggle.isPending} onClick={() => toggle.mutate()}>{team.is_active ? 'Deactivate' : 'Reactivate'}</Button>
          <Button variant="danger" onClick={() => setDeleting(true)}>Delete</Button>
        </>}
      />
      <div className="mb-5 flex flex-wrap items-center gap-x-6 gap-y-2 text-sm text-slate-600">
        {!team.is_active && <Badge>Inactive</Badge>}
        <span>Manager: <b className="text-slate-900">{team.manager?.full_name || 'Founder-managed'}</b></span>
        <span>Leader: <b className={team.leader ? 'text-slate-900' : 'text-amber-700'}>{team.leader?.full_name || 'None appointed'}</b></span>
        {team.can_lead && <Badge tone="indigo">You lead this team</Badge>}
      </div>
      {!team.is_active && <div className="mb-4"><Alert tone="amber">This team is inactive: the leader cannot distribute tasks and no members or projects can be added.</Alert></div>}
      <Tabs tabs={tabs} value={tab} onChange={setTab} />
      {tab === 'overview' && <Overview team={team} />}
      {tab === 'members' && <Members team={team} />}
      {tab === 'projects' && <Projects team={team} />}
      {tab === 'updates' && team.can_monitor && <Updates team={team} />}
      {tab === 'reports' && team.can_monitor && <Reports team={team} />}
      <TeamModal open={editing} onClose={() => setEditing(false)} team={team} />
      {reassigning && <Reassign team={team} onClose={() => setReassigning(false)} />}
      <ConfirmDialog open={deleting} danger title="Delete team" confirmLabel="Delete team" loading={del.isPending} onClose={() => setDeleting(false)} onConfirm={() => del.mutate()}
        message={`Delete "${team.name}"? Members stay employees, but lose access to the team's projects unless they still hold tasks there.`} />
    </>
  )
}
