import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Avatar, Button, EmptyState, ErrorState, Field, Modal, PageHeader, PageLoader, ProgressBar, Select, StatusBadge, Table, Tabs } from '../../components/ui'
import { api } from '../../lib/api'
import { fmtDate, label } from '../../lib/format'
import { useAction, useApi } from '../../lib/hooks'
import { useAuth } from '../auth/AuthContext'
import TaskEditor from './TaskEditor'

function PickProject({ open, onClose, projects, onPick }) {
  const [id, setId] = useState('')
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Create task"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button disabled={!id} onClick={() => { onPick(Number(id)); setId('') }}>Continue</Button>
        </>
      }
    >
      <Field label="Project" hint="Select which project this task belongs to">
        <Select value={id} onChange={(e) => setId(e.target.value)}>
          <option value="">Choose a project...</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </Select>
      </Field>
    </Modal>
  )
}

export default function MyTasksPage() {
  const { role, user } = useAuth()
  const isManagerOrAdmin = ['founder', 'manager', 'hr'].includes(role)
  const [scope, setScope] = useState(isManagerOrAdmin ? 'all' : 'mine')
  const [status, setStatus] = useState('')
  const [assigneeId, setAssigneeId] = useState('')
  const [projectId, setProjectId] = useState('')
  const [editing, setEditing] = useState(null) // task being edited
  const [picking, setPicking] = useState(false)
  const [newIn, setNewIn] = useState(null) // project id for a new task

  const { data: dir } = useApi('/employees/directory')
  const people = dir?.items || []
  const byId = useMemo(() => Object.fromEntries(people.map((p) => [p.id, p])), [people])

  const { data: projects } = useApi('/projects', { page_size: 100 })
  const projectList = projects?.items || []
  const projectNames = useMemo(() => Object.fromEntries(projectList.map((p) => [p.id, p.name])), [projectList])
  const manageableProjects = projectList.filter((p) => p.can_edit)
  const assignableProjects = projectList.filter((p) => p.can_assign_tasks)
  const selectableProjects = assignableProjects.length > 0 ? assignableProjects : projectList

  const params = {
    status: status || undefined,
    scope: isManagerOrAdmin ? scope : 'mine',
    assignee_id: assigneeId ? Number(assigneeId) : undefined,
    project_id: projectId ? Number(projectId) : undefined,
  }
  const { data, isLoading, error, refetch } = useApi('/tasks/mine', params)

  const update = useAction(
    ({ id, ...b }) => api.patch(`/tasks/${id}`, b),
    { invalidate: ['/tasks', '/projects', '/dashboard'], success: 'Task updated' }
  )
  const remove = useAction(
    (id) => api.del(`/tasks/${id}`),
    { invalidate: ['/tasks', '/projects', '/dashboard'], success: 'Task deleted' }
  )

  const canCreate = isManagerOrAdmin || assignableProjects.length > 0

  return (
    <>
      <PageHeader
        title="Tasks"
        description={
          isManagerOrAdmin
            ? 'Manage, assign, update, and track tasks across projects.'
            : 'Everything assigned to you across projects. Track your progress or submit finished work for review.'
        }
        actions={
          canCreate && (
            <Button onClick={() => setPicking(true)}>
              + New task
            </Button>
          )
        }
      />

      {isManagerOrAdmin && (
        <div className="mb-4">
          <Tabs
            value={scope}
            onChange={(s) => { setScope(s); setAssigneeId('') }}
            tabs={[
              { id: 'all', label: 'All team tasks' },
              { id: 'mine', label: 'Assigned to me' },
            ]}
          />
        </div>
      )}

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Select
          aria-label="Filter by project"
          className="w-48"
          value={projectId}
          onChange={(e) => setProjectId(e.target.value)}
        >
          <option value="">All projects</option>
          {projectList.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </Select>

        <Select
          aria-label="Filter by status"
          className="w-44"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        >
          <option value="">All statuses</option>
          {['todo', 'in_progress', 'review', 'changes_requested', 'done'].map((s) => (
            <option key={s} value={s}>{label(s)}</option>
          ))}
        </Select>

        {isManagerOrAdmin && scope === 'all' && (
          <Select
            aria-label="Filter by assignee"
            className="w-48"
            value={assigneeId}
            onChange={(e) => setAssigneeId(e.target.value)}
          >
            <option value="">All assignees</option>
            {people.map((u) => (
              <option key={u.id} value={u.id}>{u.full_name}</option>
            ))}
          </Select>
        )}
      </div>

      {isLoading ? (
        <PageLoader />
      ) : error ? (
        <ErrorState error={error} onRetry={refetch} />
      ) : (
        <Table
          caption="Tasks"
          rows={data?.items || []}
          empty={
            <EmptyState
              title={scope === 'mine' ? 'No tasks assigned to you' : 'No tasks match criteria'}
              description={
                canCreate
                  ? 'Create a new task above and assign it to a team member.'
                  : 'Tasks assigned to you will show up here.'
              }
              action={canCreate && <Button onClick={() => setPicking(true)}>+ New task</Button>}
            />
          }
          columns={[
            {
              key: 'title',
              header: 'Task',
              render: (t) => (
                <button
                  type="button"
                  className="text-left font-medium text-slate-900 hover:text-brand-700 hover:underline"
                  onClick={() => setEditing(t)}
                >
                  {t.title}
                </button>
              ),
            },
            {
              key: 'project',
              header: 'Project',
              render: (t) => (
                <Link className="text-brand-700 hover:underline font-medium text-xs" to={`/projects/${t.project_id}`}>
                  {projectNames[t.project_id] || `#${t.project_id}`}
                </Link>
              ),
            },
            {
              key: 'assignee',
              header: 'Assignee',
              render: (t) => {
                const person = byId[t.assignee_id]
                return person ? (
                  <div className="flex items-center gap-2">
                    <Avatar name={person.full_name} size={6} />
                    <span className="text-xs font-medium text-slate-700">{person.full_name}</span>
                  </div>
                ) : (
                  <span className="text-xs text-slate-500 italic">Unassigned</span>
                )
              },
            },
            {
              key: 'priority',
              header: 'Priority',
              render: (t) => <StatusBadge value={t.priority} />,
            },
            {
              key: 'due',
              header: 'Due',
              render: (t) => (
                <span className={t.overdue ? 'font-medium text-red-600' : 'text-slate-600'}>
                  {fmtDate(t.due_date)}{t.overdue && ' (overdue)'}
                </span>
              ),
            },
            {
              key: 'progress',
              header: 'Progress',
              className: 'w-36',
              render: (t) => <ProgressBar value={t.progress} />,
            },
            {
              key: 'status',
              header: 'Status',
              render: (t) => {
                const canDone = isManagerOrAdmin || manageableProjects.some((p) => p.id === t.project_id)
                if (t.status === 'done' && !canDone) {
                  return <StatusBadge value="done" />
                }
                return (
                  <Select
                    aria-label={`Status of ${t.title}`}
                    className="w-36 py-1"
                    value={t.status}
                    onChange={(e) => update.mutate({ id: t.id, status: e.target.value })}
                  >
                    <option value="todo">To do</option>
                    <option value="in_progress">In progress</option>
                    <option value="review">Submit for review</option>
                    {canDone && <option value="done">Done</option>}
                  </Select>
                )
              },
            },
            {
              key: 'actions',
              header: 'Actions',
              className: 'text-right whitespace-nowrap',
              render: (t) => {
                const canDelete = isManagerOrAdmin || manageableProjects.some((p) => p.id === t.project_id)
                return (
                  <div className="flex items-center justify-end gap-2">
                    <Button variant="secondary" size="sm" onClick={() => setEditing(t)}>
                      Edit
                    </Button>
                    {canDelete && (
                      <Button
                        variant="danger"
                        size="sm"
                        loading={remove.isPending}
                        onClick={() => {
                          if (window.confirm(`Delete task "${t.title}"?`)) {
                            remove.mutate(t.id)
                          }
                        }}
                      >
                        Delete
                      </Button>
                    )}
                  </div>
                )
              },
            },
          ]}
        />
      )}

      <PickProject
        open={picking}
        onClose={() => setPicking(false)}
        projects={selectableProjects}
        onPick={(id) => { setPicking(false); setNewIn(id) }}
      />

      <TaskEditor
        open={!!editing}
        onClose={() => setEditing(null)}
        projectId={editing?.project_id}
        task={editing}
      />
      <TaskEditor
        open={!!newIn}
        onClose={() => setNewIn(null)}
        projectId={newIn}
        task={null}
      />
    </>
  )
}
