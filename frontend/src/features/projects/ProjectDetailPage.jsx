import { useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Alert, Avatar, Badge, Button, Card, EmptyState, ErrorState, Field, Input, Modal, PageHeader, PageLoader, ProgressBar, Select, StatusBadge, Table, Tabs, Textarea } from '../../components/ui'
import { api } from '../../lib/api'
import { fmtDate, label } from '../../lib/format'
import { useAction, useApi } from '../../lib/hooks'
import { useAuth } from '../auth/AuthContext'
import ProjectModal from './ProjectModal'
import TaskModal from './TaskModal'

const COLUMNS = [
  { id: 'todo', title: 'To do' },
  { id: 'in_progress', title: 'In progress' },
  { id: 'review', title: 'In review' },
  { id: 'changes_requested', title: 'Changes requested' },
  { id: 'done', title: 'Done' },
]
const PRIORITY_BORDER = {
  low: 'border-l-slate-300',
  medium: 'border-l-sky-400',
  high: 'border-l-amber-400',
  urgent: 'border-l-red-500'
}

function TaskCard({ task, person, canMove, canManage, onOpen, onMove, onReview }) {
  const blocked = task.depends_on?.length > 0 && task.status === 'todo'
  return (
    <article
      draggable={canMove}
      onDragStart={(e) => e.dataTransfer.setData('text/task', String(task.id))}
      className={`rounded-lg border border-l-4 border-slate-200 bg-white p-3 shadow-sm ${PRIORITY_BORDER[task.priority]} ${
        canMove ? 'cursor-grab active:cursor-grabbing' : ''
      }`}
    >
      <button onClick={onOpen} className="w-full text-left text-sm font-medium text-slate-900 hover:text-brand-700">
        {task.title}
      </button>
      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs">
        <StatusBadge value={task.priority} />
        {task.overdue && <Badge tone="red">Overdue</Badge>}
        {blocked && <Badge tone="amber">Blocked</Badge>}
        {task.task_type && task.task_type !== 'feature' && <Badge tone="purple">{label(task.task_type)}</Badge>}
        {task.labels?.slice(0, 2).map((l) => <Badge key={l}>{l}</Badge>)}
        {task.due_date && <span className="text-slate-500">{fmtDate(task.due_date)}</span>}
      </div>
      {task.status === 'changes_requested' && task.review_notes && <p className="mt-2 rounded bg-red-50 px-2 py-1 text-xs text-red-800">{task.review_notes}</p>}
      <div className="mt-2">
        <ProgressBar value={task.progress} />
      </div>
      {(task.estimated_hours != null || task.actual_hours != null) && <p className="mt-1 text-xs text-slate-500">{task.actual_hours ?? 0}h of {task.estimated_hours ?? '?'}h</p>}
      <div className="mt-2 flex items-center justify-between gap-2">
        {person ? (
          <span className="flex items-center gap-1.5 text-xs text-slate-600">
            <Avatar name={person.full_name} size={6} />
            {person.full_name.split(' ')[0]}
          </span>
        ) : (
          <span className="text-xs text-slate-500">Unassigned</span>
        )}
        {canMove && (
          <select
            aria-label={`Move task ${task.title}`}
            className="cursor-pointer appearance-none rounded border border-slate-200 bg-white px-2 py-0.5 text-xs text-center"
            value={task.status}
            onChange={(e) => onMove(e.target.value)}
          >
            {task.status === 'changes_requested' && <option value="changes_requested" disabled>Changes requested</option>}
            {COLUMNS.filter((c) => c.id !== 'changes_requested' && (canManage || c.id !== 'done')).map((c) => (
              <option key={c.id} value={c.id}>{c.title}</option>
            ))}
          </select>
        )}
      </div>
      {canManage && task.status === 'review' && (
        <div className="mt-2 flex gap-2 border-t border-slate-100 pt-2">
          <Button size="sm" onClick={() => onReview(true)}>Approve</Button>
          <Button size="sm" variant="secondary" onClick={() => onReview(false)}>Request changes</Button>
        </div>
      )}
    </article>
  )
}

function Board({ tasks, byId, canManage, meId, onOpen }) {
  const [over, setOver] = useState(null)
  const move = useAction(({ id, status }) => api.patch(`/tasks/${id}`, { status }), {
    invalidate: ['/projects', '/tasks', '/dashboard']
  })
  const [asking, setAsking] = useState(null) // task a reviewer is requesting changes on
  const [note, setNote] = useState('')
  const review = useAction(({ id, approved, note }) => api.post(`/tasks/${id}/review`, { approved, note }), {
    invalidate: ['/projects', '/tasks', '/dashboard'],
    success: (t) => (t.status === 'done' ? 'Task approved' : 'Changes requested'),
    onSuccess: () => { setAsking(null); setNote('') }
  })

  return (
    <>
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
      {COLUMNS.map((col) => {
        const items = tasks.filter((t) => t.status === col.id)
        return (
          <section
            key={col.id}
            aria-label={col.title}
            onDragOver={(e) => { e.preventDefault(); setOver(col.id) }}
            onDragLeave={() => setOver(null)}
            onDrop={(e) => {
              e.preventDefault()
              setOver(null)
              const id = Number(e.dataTransfer.getData('text/task'))
              const t = tasks.find((x) => x.id === id)
              if (t && t.status !== col.id && col.id !== 'changes_requested') move.mutate({ id, status: col.id })
            }}
            className={`rounded-xl bg-slate-100 p-3 transition ${over === col.id ? 'ring-2 ring-brand-500' : ''}`}
          >
            <h3 className="mb-3 flex items-center justify-between text-sm font-semibold text-slate-700">
              {col.title}
              <span className="rounded-full bg-white px-2 py-0.5 text-xs text-slate-500">{items.length}</span>
            </h3>
            <div className="space-y-2.5">
              {items.map((t) => (
                <TaskCard
                  key={t.id}
                  task={t}
                  person={byId[t.assignee_id]}
                  canManage={canManage}
                  canMove={canManage || t.assignee_id === meId}
                  onOpen={() => onOpen(t)}
                  onMove={(status) => move.mutate({ id: t.id, status })}
                  onReview={(approved) => (approved ? review.mutate({ id: t.id, approved }) : setAsking(t))}
                />
              ))}
              {!items.length && (
                <p className="rounded-lg border border-dashed border-slate-300 py-6 text-center text-xs text-slate-500">
                  No tasks
                </p>
              )}
            </div>
          </section>
        )
      })}
    </div>
    <Modal open={!!asking} onClose={() => setAsking(null)} title="Request changes"
      footer={<><Button variant="secondary" onClick={() => setAsking(null)}>Cancel</Button><Button loading={review.isPending} disabled={!note.trim()} onClick={() => review.mutate({ id: asking.id, approved: false, note })}>Send back</Button></>}>
      <p className="mb-3 text-sm text-slate-600">{asking?.title}</p>
      <Field label="What needs to change?" required hint="The assignee sees this comment on the task.">
        <Textarea rows={4} maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} />
      </Field>
    </Modal>
    </>
  )
}

function Milestones({ project, canManage }) {
  const [open, setOpen] = useState(false)
  const [f, setF] = useState({ title: '', due_date: '' })
  const add = useAction(() => api.post(`/projects/${project.id}/milestones`, { title: f.title, due_date: f.due_date || null }), {
    invalidate: ['/projects'],
    success: 'Milestone added',
    onSuccess: () => { setOpen(false); setF({ title: '', due_date: '' }) }
  })
  const toggle = useAction(({ id, completed }) => api.patch(`/milestones/${id}`, { completed }), {
    invalidate: ['/projects'],
    success: 'Milestone updated'
  })
  const del = useAction(({ id }) => api.del(`/milestones/${id}`), {
    invalidate: ['/projects'],
    success: 'Milestone deleted'
  })

  return (
    <Card
      title="Milestones"
      action={canManage && <Button size="sm" onClick={() => setOpen(true)}>Add milestone</Button>}
    >
      {!project.milestones?.length ? (
        <EmptyState
          title="No milestones"
          description="Milestones help track major project checkpoints"
          action={canManage && <Button size="sm" onClick={() => setOpen(true)}>Add milestone</Button>}
        />
      ) : (
        <ol className="divide-y divide-slate-100">
          {project.milestones.map((m) => (
            <li key={m.id} className="flex items-center justify-between py-3 text-sm">
              <label className="flex items-center gap-3">
                <input
                  type="checkbox"
                  className="h-4 w-4 rounded accent-brand-600"
                  checked={m.completed}
                  disabled={!canManage}
                  onChange={(e) => toggle.mutate({ id: m.id, completed: e.target.checked })}
                />
                <span className={m.completed ? 'text-slate-500 line-through' : 'font-medium text-slate-900'}>
                  {m.title}
                </span>
              </label>
              <span className="flex items-center gap-3 text-slate-500">
                {fmtDate(m.due_date)}
                {canManage && (
                  <button
                    className="text-red-600 hover:underline"
                    onClick={() => window.confirm('Delete milestone?') && del.mutate(m)}
                  >
                    Delete
                  </button>
                )}
              </span>
            </li>
          ))}
        </ol>
      )}
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Add milestone"
        footer={
          <>
            <Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button>
            <Button loading={add.isPending} disabled={f.title.length < 2} onClick={() => add.mutate()}>Add</Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="Title" required>
            <Input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />
          </Field>
          <Field label="Due date">
            <Input type="date" value={f.due_date} onChange={(e) => setF({ ...f, due_date: e.target.value })} />
          </Field>
        </div>
      </Modal>
    </Card>
  )
}

function Team({ project, people, canManage }) {
  const [sel, setSel] = useState(null)
  const members = sel ?? project.member_ids
  const save = useAction(() => api.put(`/projects/${project.id}/members`, { member_ids: members }), {
    invalidate: ['/projects'],
    success: 'Team updated',
    onSuccess: () => setSel(null)
  })

  return (
    <Card title="Team" action={canManage && sel && <Button size="sm" loading={save.isPending} onClick={() => save.mutate()}>Save team</Button>}>
      <ul className="grid gap-2 sm:grid-cols-2">
        {people.filter((u) => u.role === 'employee').map((u) => {
          const checked = members.includes(u.id)
          const isOwner = u.id === project.owner_id
          return (
            <li key={u.id}>
              <label className={`flex items-center gap-3 rounded-lg border px-3 py-2 text-sm ${checked ? 'border-brand-500 bg-brand-50' : 'border-slate-200'} ${canManage && !isOwner ? 'cursor-pointer' : ''}`}>
                <input
                  type="checkbox"
                  className="h-4 w-4 accent-brand-600"
                  checked={checked}
                  disabled={!canManage || isOwner}
                  onChange={() => setSel(checked ? members.filter((x) => x !== u.id) : [...members, u.id])}
                />
                <Avatar name={u.full_name} />
                <span className="min-w-0">
                  <span className="block truncate font-medium">{u.full_name}</span>
                  <span className="block truncate text-xs text-slate-500">
                    {isOwner ? 'Project owner' : u.designation || label(u.role)}
                  </span>
                </span>
              </label>
            </li>
          )
        })}
      </ul>
    </Card>
  )
}

export default function ProjectDetailPage() {
  const { id } = useParams()
  const nav = useNavigate()
  const { user } = useAuth()
  const [tab, setTab] = useState('board')
  const [editing, setEditing] = useState(null) // task | 'new' | null
  const [editProject, setEditProject] = useState(false)
  const [filter, setFilter] = useState({ assignee: '', priority: '' })
  const { data: project, isLoading, error, refetch } = useApi(`/projects/${id}`)
  const { data: taskData } = useApi(`/projects/${id}/tasks`)
  const { data: dir } = useApi('/employees/directory')
  const people = dir?.items || []
  const byId = useMemo(() => Object.fromEntries(people.map((p) => [p.id, p])), [people])
  const del = useAction(() => api.del(`/projects/${id}`), {
    invalidate: ['/projects', '/dashboard'],
    success: 'Project deleted',
    onSuccess: () => nav('/projects')
  })
  const setStatus = useAction((status) => api.patch(`/projects/${id}`, { status }), {
    invalidate: ['/projects'],
    success: 'Status updated'
  })

  if (isLoading) return <PageLoader />
  if (error) return <ErrorState error={error} onRetry={refetch} />

  const canManage = Boolean(project.can_edit)
  const tasks = (taskData?.items || []).filter(
    (t) => (!filter.assignee || String(t.assignee_id) === filter.assignee) && (!filter.priority || t.priority === filter.priority)
  )

  return (
    <>
      <PageHeader
        title={project.name}
        description={project.description || 'No description'}
        actions={
          <>
            {canManage ? (
              <Select
                aria-label="Project status"
                className="w-36"
                value={project.status}
                onChange={(e) => setStatus.mutate(e.target.value)}
              >
                {['planning', 'active', 'on_hold', 'completed'].map((s) => (
                  <option key={s} value={s}>{label(s)}</option>
                ))}
              </Select>
            ) : (
              <StatusBadge value={project.status} />
            )}
            {canManage && (
              <Button variant="secondary" onClick={() => setEditProject(true)}>
                Edit project
              </Button>
            )}
            {canManage && (
              <Button onClick={() => setEditing('new')}>
                + New task
              </Button>
            )}
            {canManage && (
              <Button
                variant="danger"
                onClick={() =>
                  window.confirm(`Delete "${project.name}" and all its tasks? This cannot be undone.`) && del.mutate()
                }
              >
                Delete
              </Button>
            )}
          </>
        }
      />
      <div className="mb-6 grid gap-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm sm:grid-cols-4">
        <div className="sm:col-span-2">
          <p className="mb-1 text-sm text-slate-500">
            Overall progress • {project.done_count}/{project.task_count} tasks done
          </p>
          <ProgressBar value={project.progress} />
        </div>
        <div>
          <p className="text-sm text-slate-500">Owner</p>
          <p className="font-medium">{byId[project.owner_id]?.full_name || '—'}</p>
        </div>
        <div>
          <p className="text-sm text-slate-500">Timeline</p>
          <p className="font-medium">
            {fmtDate(project.start_date)} → {fmtDate(project.due_date)}
          </p>
        </div>
      </div>
      <Tabs
        value={tab}
        onChange={setTab}
        tabs={[
          { id: 'board', label: 'Board' },
          { id: 'list', label: 'List' },
          { id: 'milestones', label: 'Milestones' },
          { id: 'team', label: 'Team' }
        ]}
      />
      {(tab === 'board' || tab === 'list') && (
        <div className="mb-4 flex flex-wrap gap-3">
          <Select
            aria-label="Filter by assignee"
            className="w-48"
            value={filter.assignee}
            onChange={(e) => setFilter({ ...filter, assignee: e.target.value })}
          >
            <option value="">All assignees</option>
            {people.map((p) => (
              <option key={p.id} value={p.id}>{p.full_name}</option>
            ))}
          </Select>
          <Select
            aria-label="Filter by priority"
            className="w-40"
            value={filter.priority}
            onChange={(e) => setFilter({ ...filter, priority: e.target.value })}
          >
            <option value="">All priorities</option>
            {['low', 'medium', 'high', 'urgent'].map((p) => (
              <option key={p}>{p}</option>
            ))}
          </Select>
        </div>
      )}
      {tab === 'board' && (!taskData ? (
        <PageLoader />
      ) : (
        <Board tasks={tasks} byId={byId} canManage={canManage} meId={user.id} onOpen={setEditing} />
      ))}
      {tab === 'list' && (
        <Table
          caption="Project tasks"
          rows={tasks}
          onRowClick={setEditing}
          empty={<EmptyState title="No tasks match" />}
          columns={[
            { key: 'title', header: 'Task', render: (t) => <span className="font-medium text-slate-900">{t.title}</span> },
            { key: 'status', header: 'Status', render: (t) => <StatusBadge value={t.status} /> },
            { key: 'priority', header: 'Priority', render: (t) => <StatusBadge value={t.priority} /> },
            { key: 'assignee', header: 'Assignee', render: (t) => byId[t.assignee_id]?.full_name || '—' },
            { key: 'due', header: 'Due', render: (t) => <span className={t.overdue ? 'font-medium text-red-600' : ''}>{fmtDate(t.due_date)}</span> },
            { key: 'progress', header: 'Progress', className: 'w-40', render: (t) => <ProgressBar value={t.progress} /> },
          ]}
        />
      )}
      {tab === 'milestones' && <Milestones project={project} canManage={canManage} />}
      {tab === 'team' && <Team project={project} people={people} canManage={canManage} />}
      <ProjectModal
        open={editProject}
        onClose={() => setEditProject(false)}
        project={project}
        onDeleted={() => nav('/projects')}
      />
      <TaskModal
        open={!!editing}
        onClose={() => setEditing(null)}
        project={project}
        task={editing === 'new' ? null : editing}
        tasks={taskData?.items || []}
        milestones={project.milestones || []}
        people={people}
        canManage={canManage}
        meId={user.id}
      />
    </>
  )
}
