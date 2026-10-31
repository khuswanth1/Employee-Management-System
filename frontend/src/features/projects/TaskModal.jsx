import { useEffect, useRef, useState } from 'react'
import { Alert, Button, Field, FormSection, Input, Modal, Select, StatusBadge, Textarea } from '../../components/ui'
import TagInput from '../../components/TagInput'
import { api, download, fieldErrors } from '../../lib/api'
import { label } from '../../lib/format'
import { useAction, useApi } from '../../lib/hooks'
import TaskComments from './TaskComments'

const TYPES = ['feature', 'bug', 'improvement', 'research', 'documentation', 'administrative']
const blank = { title: '', description: '', priority: 'medium', task_type: 'feature', labels: [], start_date: '', estimated_hours: '', actual_hours: '', assignee_id: '', milestone_id: '', due_date: '', status: 'todo', progress: 0, is_blocked: false, blocker_note: '' }

/** Create (task == null) or edit a task. `canManage`: project manager / HR / founder. Assignees get progress/status view. */
export default function TaskModal({ open, onClose, project, task, tasks = [], milestones = [], people = [], canManage, isOwner = canManage, meId }) {
  const [f, setF] = useState(blank)
  const [deps, setDeps] = useState([])
  const fileRef = useRef(null)
  const isNew = !task
  const isAssignee = task?.assignee_id === meId
  const { data: files, refetch: refetchFiles } = useApi(task ? `/tasks/${task.id}/attachments` : null, null, { enabled: !!task && open })

  useEffect(() => {
    if (!open) return
    setF(
      task
        ? {
            title: task.title,
            description: task.description || '',
            priority: task.priority || 'medium',
            task_type: task.task_type || 'feature',
            labels: task.labels || [],
            start_date: task.start_date || '',
            estimated_hours: task.estimated_hours ?? '',
            actual_hours: task.actual_hours ?? '',
            assignee_id: task.assignee_id || '',
            milestone_id: task.milestone_id || '',
            due_date: task.due_date || '',
            status: task.status || 'todo',
            progress: task.progress || 0,
            is_blocked: Boolean(task.is_blocked),
            blocker_note: task.blocker_note || ''
          }
        : blank
    )
    setDeps(task?.depends_on || [])
  }, [open, task])

  const inv = { invalidate: ['/projects', '/tasks', '/dashboard'], onSuccess: onClose }
  const save = useAction(
    async () => {
      const hours = (v) => (v === '' ? null : Number(v))
      const body = {
        ...f,
        start_date: f.start_date || null,
        estimated_hours: hours(f.estimated_hours),
        actual_hours: hours(f.actual_hours),
        assignee_id: f.assignee_id ? Number(f.assignee_id) : null,
        milestone_id: f.milestone_id ? Number(f.milestone_id) : null,
        due_date: f.due_date || null,
        blocker_note: f.is_blocked ? f.blocker_note || null : null
      }
      if (isNew) {
        return api.post(`/projects/${project.id}/tasks`, body)
      }
      if (canManage) {
        const saved = await api.patch(`/tasks/${task.id}`, { ...body, progress: Number(f.progress), status: f.status })
        if (isOwner && JSON.stringify([...deps].sort()) !== JSON.stringify([...(task.depends_on || [])].sort())) {
          await api.put(`/tasks/${task.id}/dependencies`, { depends_on: deps })
        }
        return saved
      }
      return api.patch(`/tasks/${task.id}`, { status: f.status, progress: Number(f.progress), actual_hours: hours(f.actual_hours), is_blocked: f.is_blocked, blocker_note: f.is_blocked ? f.blocker_note || null : null })
    },
    { ...inv, success: isNew ? 'Task created' : 'Task updated' }
  )

  const remove = useAction(() => api.del(`/tasks/${task.id}`), { ...inv, success: 'Task deleted' })
  const upload = useAction((file) => api.upload(`/tasks/${task.id}/attachments`, file), { success: 'File attached', onSuccess: refetchFiles })
  const fe = fieldErrors(save.error)
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }))
  const readOnlyFields = !isNew && !canManage
  // 'changes requested' is only set by a reviewer (with a comment); the assignee moves the task on from there
  const statusOptions = [...(isOwner ? ['todo', 'in_progress', 'review', 'done'] : ['todo', 'in_progress', 'review']), ...(task?.status === 'changes_requested' ? ['changes_requested'] : [])]

  return (
    <Modal
      open={open}
      onClose={onClose}
      wide
      title={isNew ? 'New task' : `Task #${task.id}`}
      footer={
        <>
          {!isNew && isOwner && (
            <Button
              variant="danger"
              className="mr-auto"
              loading={remove.isPending}
              onClick={() => window.confirm('Delete this task?') && remove.mutate()}
            >
              Delete
            </Button>
          )}
          <Button variant="secondary" onClick={onClose}>Close</Button>
          {(canManage || isAssignee) && (
            <Button loading={save.isPending} onClick={() => save.mutate()}>
              {isNew ? 'Create task' : 'Save changes'}
            </Button>
          )}
        </>
      }
    >
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
        {save.error && !Object.keys(fe).length && <Alert>{save.error.message}</Alert>}
        {task?.status === 'changes_requested' && <Alert tone="amber"><strong>Changes requested:</strong> {task.review_notes}</Alert>}
        <Field label="Title" required error={fe.title}>
          <Input value={f.title} onChange={set('title')} disabled={readOnlyFields} required placeholder="What needs to be done?" />
        </Field>
        <Field label="Description" error={fe.description}>
          <Textarea value={f.description} onChange={set('description')} disabled={readOnlyFields} placeholder="Add detailed instructions..." />
        </Field>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Task type" error={fe.task_type}>
            <Select value={f.task_type} onChange={set('task_type')} disabled={readOnlyFields || !canManage}>
              {TYPES.map((t) => <option key={t} value={t}>{label(t)}</option>)}
            </Select>
          </Field>
          <div className="sm:col-span-2">
            <Field label="Labels" error={fe.labels} hint="Press Enter to add">
              <TagInput label="Labels" max={20} value={f.labels} onChange={(v) => setF((s) => ({ ...s, labels: v }))} disabled={readOnlyFields || !canManage} />
            </Field>
          </div>
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Priority">
            <Select value={f.priority} onChange={set('priority')} disabled={readOnlyFields}>
              {['low', 'medium', 'high', 'urgent'].map((p) => (
                <option key={p} value={p}>{p.toUpperCase()}</option>
              ))}
            </Select>
          </Field>
          <Field label="Assignee">
            <Select value={f.assignee_id} onChange={set('assignee_id')} disabled={readOnlyFields}>
              <option value="">Unassigned</option>
              {people.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.full_name} ({u.designation || label(u.role)})
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Due date" error={fe.due_date}>
            <Input type="date" min={f.start_date || undefined} value={f.due_date} onChange={set('due_date')} disabled={readOnlyFields} />
          </Field>
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Start date" error={fe.start_date}>
            <Input type="date" value={f.start_date} onChange={set('start_date')} disabled={readOnlyFields} />
          </Field>
          <Field label="Estimated hours" error={fe.estimated_hours}>
            <Input type="number" min={0} max={10000} step="0.25" inputMode="decimal" value={f.estimated_hours} onChange={set('estimated_hours')} disabled={readOnlyFields} />
          </Field>
          <Field label="Actual hours" error={fe.actual_hours} hint={isNew ? undefined : 'Time spent so far'}>
            <Input type="number" min={0} max={10000} step="0.25" inputMode="decimal" value={f.actual_hours} onChange={set('actual_hours')} disabled={!isNew && !(canManage || isAssignee)} />
          </Field>
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Milestone">
            <Select value={f.milestone_id} onChange={set('milestone_id')} disabled={readOnlyFields}>
              <option value="">None</option>
              {milestones.map((m) => (
                <option key={m.id} value={m.id}>{m.title}</option>
              ))}
            </Select>
          </Field>
          {!isNew && (
            <Field label="Status">
              <Select value={f.status} onChange={set('status')}>
                {statusOptions.map((s) => (
                  <option key={s} value={s}>{label(s)}</option>
                ))}
              </Select>
            </Field>
          )}
          {!isNew && (
            <Field label={`Progress (${f.progress}%)`}>
              <input
                type="range"
                min="0"
                max="100"
                step="5"
                value={f.progress}
                onChange={set('progress')}
                className="w-full accent-brand-600 cursor-pointer"
                aria-label="Progress"
              />
            </Field>
          )}
        </div>
        {!isNew && isOwner && (
          <Field label="Depends on" hint="This task can't start until these are done">
            <Select
              multiple
              className="h-24"
              value={deps.map(String)}
              onChange={(e) => setDeps([...e.target.selectedOptions].map((o) => Number(o.value)))}
            >
              {tasks.filter((t) => t.id !== task.id).map((t) => (
                <option key={t.id} value={t.id}>#{t.id} {t.title}</option>
              ))}
            </Select>
          </Field>
        )}
        {!isNew && (canManage || isAssignee) && (
          <div className="rounded-lg border border-slate-200 p-3">
            <label className="flex items-center gap-2 text-sm font-medium text-slate-700">
              <input type="checkbox" checked={f.is_blocked} onChange={(e) => setF((s) => ({ ...s, is_blocked: e.target.checked }))} className="accent-brand-600" />
              I am blocked on this task
            </label>
            {f.is_blocked && (
              <Field label="What is blocking you?" hint="Your team leader and the project owner are notified">
                <Textarea rows={2} maxLength={1000} value={f.blocker_note} onChange={set('blocker_note')} placeholder="e.g. Waiting for API credentials" />
              </Field>
            )}
          </div>
        )}
        {!isNew && (
          <div>
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-sm font-medium text-slate-700">Attachments</h3>
              {(canManage || isAssignee) && (
                <>
                  <input
                    ref={fileRef}
                    type="file"
                    className="sr-only"
                    aria-label="Attach file"
                    onChange={(e) => {
                      if (e.target.files[0]) upload.mutate(e.target.files[0])
                      e.target.value = ''
                    }}
                  />
                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    loading={upload.isPending}
                    onClick={() => fileRef.current.click()}
                  >
                    Attach file
                  </Button>
                </>
              )}
            </div>
            {files?.items?.length ? (
              <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 text-sm">
                {files.items.map((a) => (
                  <li key={a.id} className="flex items-center justify-between px-3 py-2">
                    <span className="truncate">{a.filename}</span>
                    <button
                      type="button"
                      className="text-brand-700 hover:underline"
                      onClick={() => download(`/attachments/${a.id}/download`, a.filename)}
                    >
                      Download
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-slate-500">No attachments</p>
            )}
            {task.depends_on?.length > 0 && (
              <p className="mt-3 text-xs text-slate-500">
                Blocked until: {task.depends_on.map((id) => `#${id}`).join(', ')} <StatusBadge value={task.status} />
              </p>
            )}
            <TaskComments taskId={task.id} isOwner={isOwner} />
          </div>
        )}
      </form>
    </Modal>
  )
}
