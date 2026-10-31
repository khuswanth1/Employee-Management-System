import { useMemo, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Button, ConfirmDialog, ErrorState, Modal, PageHeader, PageLoader, Select, cx, useToast } from '../../components/ui'
import { api } from '../../lib/api'
import { useAction, useApi } from '../../lib/hooks'
import { applyMove, dropIndex } from '../../lib/todoTree'
import { Icon, PRIORITIES, QuickAdd, Row, STATUSES, TaskForm } from './parts'

function EmptyBoard({ title, children }) {
  return (
    <div className="flex flex-col items-center rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-14 text-center">
      <span className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-brand-50 text-brand-600"><Icon name="check" className="h-6 w-6" /></span>
      <p className="text-base font-semibold text-slate-900">{title}</p>
      <div className="mt-1 max-w-sm text-sm text-slate-600">{children}</div>
    </div>
  )
}

/* ---------- the page ---------- */
export default function TodoPage() {
  const qc = useQueryClient()
  const toast = useToast()
  const { data, isLoading, error, refetch } = useApi('/todos')
  const KEY = ['/todos', {}]
  const [open, setOpen] = useState({}) // which main tasks show their subtasks
  const [editing, setEditing] = useState(null)
  const [deleting, setDeleting] = useState(null)
  const [fStatus, setFStatus] = useState('')
  const [fPriority, setFPriority] = useState('')
  const [q, setQ] = useState('')
  const [dragId, setDragId] = useState(null)
  const [hover, setHover] = useState(null)
  const dragRef = useRef(null)

  const create = useAction(({ body }) => api.post('/todos', body), { invalidate: ['/todos'], onSuccess: (_d, v) => v.done?.() })
  const update = useAction(({ id, body }) => api.patch(`/todos/${id}`, body), { invalidate: ['/todos'], onSuccess: (_d, v) => v.done?.() })
  const remove = useAction((t) => api.del(`/todos/${t.id}`), { invalidate: ['/todos'], success: 'Task deleted', onSuccess: () => setDeleting(null) })
  const move = useMutation({
    mutationFn: ({ id, parentId, index }) => api.post(`/todos/${id}/move`, { parent_id: parentId, index }),
    onMutate: async ({ id, parentId, index }) => {
      await qc.cancelQueries({ queryKey: KEY })
      const before = qc.getQueryData(KEY)
      if (before) qc.setQueryData(KEY, { ...before, items: applyMove(before.items, id, parentId, index) })
      return { before }
    },
    onError: (e, _v, ctx) => { if (ctx?.before) qc.setQueryData(KEY, ctx.before); toast(e.message, 'red') },
    onSettled: () => qc.invalidateQueries({ queryKey: KEY }),
  })

  const items = data?.items || []
  const filtersOn = Boolean(fStatus || fPriority || q.trim())
  const matches = (t) => (!fStatus || t.status === fStatus) && (!fPriority || t.priority === fPriority) && (!q.trim() || t.title.toLowerCase().includes(q.trim().toLowerCase()))
  const visible = useMemo(() => {
    if (!filtersOn) return items
    return items.map((t) => ({ ...t, subtasks: t.subtasks.filter(matches) })).filter((t) => matches(t) || t.subtasks.length)
  }, [items, fStatus, fPriority, q]) // eslint-disable-line react-hooks/exhaustive-deps
  const canReorder = !filtersOn

  const counts = useMemo(() => Object.fromEntries(STATUSES.map(([v]) => [v, items.filter((t) => t.status === v).length])), [items])

  const onToggle = (t, checked) => update.mutate({ id: t.id, body: { status: checked ? 'completed' : 'todo' } })
  const onStatus = (t, status) => update.mutate({ id: t.id, body: { status } })
  const siblingsOf = (t) => (t.parent_id ? items.find((x) => x.id === t.parent_id)?.subtasks || [] : items)
  const onMove = (t, delta) => {
    const list = siblingsOf(t)
    const at = list.findIndex((x) => x.id === t.id)
    move.mutate({ id: t.id, parentId: t.parent_id ?? null, index: at + delta })
  }

  // Where a drop would land, from the pointer position: top quarter = before, bottom quarter = after, middle of a main task = inside it
  // (becomes its last subtask). Subtask rows only offer before/after. Computed from the event so it is never stale.
  const zoneOf = (e, t, sub) => {
    const d = dragRef.current
    const r = e.currentTarget.getBoundingClientRect()
    const y = (e.clientY - r.top) / (r.height || 1)
    const canNest = !sub && d && !d.subtask_count && d.id !== t.id
    if (canNest && y >= 0.25 && y <= 0.75) return 'inside'
    return y < 0.5 ? 'before' : 'after'
  }
  const drag = {
    dragId, hover,
    start: (t) => { dragRef.current = t; setDragId(t.id) },
    end: () => { dragRef.current = null; setDragId(null); setHover(null) },
    over: (e, t, sub) => {
      const d = dragRef.current
      if (!d || d.id === t.id) return
      e.preventDefault(); e.stopPropagation()
      e.dataTransfer.dropEffect = 'move'
      const pos = zoneOf(e, t, sub)
      setHover((h) => (h && h.id === t.id && h.pos === pos ? h : { id: t.id, pos }))
    },
    leave: (t) => setHover((h) => (h?.id === t.id ? null : h)),
    drop: (e, t, sub) => {
      const d = dragRef.current
      if (!d || d.id === t.id) return
      e.preventDefault(); e.stopPropagation()
      const pos = zoneOf(e, t, sub)
      if (pos === 'inside') {
        move.mutate({ id: d.id, parentId: t.id, index: (t.subtasks || []).filter((x) => x.id !== d.id).length })
        setOpen((o) => ({ ...o, [t.id]: true }))
      } else {
        const parentId = sub ? t.parent_id : null
        const list = sub ? items.find((x) => x.id === t.parent_id)?.subtasks || [] : items
        move.mutate({ id: d.id, parentId, index: dropIndex(list, d.id, t.id, pos === 'after') })
      }
      drag.end()
    },
  }

  if (isLoading) return <PageLoader />
  if (error) return <ErrorState error={error} onRetry={refetch} />

  const clear = () => { setFStatus(''); setFPriority(''); setQ('') }
  return (
    <>
      <PageHeader title="My tasks" description="Plan your own work: tasks with subtasks, priority, estimated time and status. Drag to reorder. Changes save automatically." />

      <QuickAdd label="New task" placeholder="Add a new task…" pending={create.isPending}
        onAdd={(body, reset) => create.mutate({ body, done: reset })} />

      <div className="mb-4 mt-6 flex flex-wrap items-center gap-3">
        <div role="group" aria-label="Filter by status" className="inline-flex flex-wrap gap-1 rounded-xl bg-slate-100 p-1">
          {[['', 'All', items.length], ...STATUSES.map(([v, l]) => [v, l, counts[v]])].map(([v, l, n]) => (
            <button key={v || 'all'} type="button" aria-pressed={fStatus === v} onClick={() => setFStatus(v)}
              className={cx('rounded-lg px-3 py-1.5 text-sm transition-colors', fStatus === v ? 'bg-white font-semibold text-brand-700 shadow-sm' : 'text-slate-700 hover:bg-white/60')}>
              {l} <span className={cx('ml-0.5 text-xs', fStatus === v ? 'text-brand-700' : 'text-slate-600')}>({n})</span>
            </button>
          ))}
        </div>
        <div className="w-full sm:w-40 md:w-44">
          <label className="sr-only" htmlFor="todo-prio">Filter by priority</label>
          <Select id="todo-prio" value={fPriority} onChange={(e) => setFPriority(e.target.value)} className="h-10 w-full">
            <option value="">All priorities</option>{PRIORITIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </Select>
        </div>
        <div className="relative min-w-[12rem] flex-1 sm:max-w-xs">
          <span className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-slate-500"><Icon name="search" /></span>
          <label className="sr-only" htmlFor="todo-search">Search tasks</label>
          <input id="todo-search" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search tasks…"
            className="h-10 w-full rounded-lg border border-slate-500 bg-white pl-9 pr-3 text-sm text-slate-900 shadow-sm placeholder:text-slate-500 focus:border-brand-500 focus:ring-1 focus:ring-brand-500" />
        </div>
        {filtersOn && <Button variant="ghost" size="sm" onClick={clear}>Clear filters</Button>}
      </div>
      {filtersOn && items.length > 0 && <p className="mb-3 text-sm text-slate-600">Reordering is paused while filters are on.</p>}

      {!items.length ? (
        <EmptyBoard title="No tasks yet">Add your first task above. Break it into subtasks, give it a priority and an estimated time, then drag to put things in order.</EmptyBoard>
      ) : !visible.length ? (
        <EmptyBoard title="No tasks match your filters"><Button variant="secondary" onClick={clear}>Clear filters</Button></EmptyBoard>
      ) : (
        <ul className="space-y-3" aria-label="Task list">
          {visible.map((t, i) => {
            const expanded = open[t.id] ?? false
            const subs = t.subtasks || []
            return (
              <li key={t.id}>
                <Row t={t} canReorder={canReorder} first={i === 0} last={i === visible.length - 1} drag={drag}
                  onToggle={onToggle} onStatus={onStatus} onEdit={(x) => setEditing(x)} onDelete={setDeleting} onMove={onMove}
                  subOpen={expanded} onToggleSub={() => setOpen((o) => ({ ...o, [t.id]: !expanded }))}>
                  {expanded && (
                    <div className="mt-4 border-l-2 border-slate-200 pl-4 sm:ml-8">
                      <ul className="space-y-2" aria-label={`Subtasks of ${t.title}`}>
                        {subs.map((st, j) => (
                          <li key={st.id}>
                            <Row t={st} sub canReorder={canReorder} first={j === 0} last={j === subs.length - 1} drag={drag}
                              onToggle={onToggle} onStatus={onStatus} onEdit={(x) => setEditing(x)} onDelete={setDeleting} onMove={onMove} />
                          </li>
                        ))}
                      </ul>
                      {subs.length === 0 && <p className="mb-3 text-sm text-slate-600">No subtasks yet. Add one below, or drop a task on the middle of this card to nest it.</p>}
                      <div className="mt-3"><QuickAdd compact label={`New subtask for ${t.title}`} placeholder="Add a subtask" pending={create.isPending}
                        onAdd={(body, reset) => create.mutate({ body: { ...body, parent_id: t.id }, done: reset })} /></div>
                    </div>
                  )}
                </Row>
              </li>
            )
          })}
        </ul>
      )}

      {editing && (
        <Modal open onClose={() => setEditing(null)} title={editing.parent_id ? 'Edit subtask' : 'Edit task'}>
          <TaskForm initial={editing} kind={editing.parent_id ? 'subtask' : 'task'} submitLabel="Save changes" pending={update.isPending} error={update.error}
            onCancel={() => setEditing(null)} onSubmit={(body) => update.mutate({ id: editing.id, body, done: () => { setEditing(null); toast('Task saved') } })} />
        </Modal>
      )}
      <ConfirmDialog open={!!deleting} danger title={deleting?.parent_id ? 'Delete subtask' : 'Delete task'} confirmLabel="Delete" loading={remove.isPending}
        message={deleting ? `Delete “${deleting.title}”?${deleting.subtask_count ? ` Its ${deleting.subtask_count} subtask(s) will be deleted too.` : ''} This cannot be undone.` : ''}
        onClose={() => setDeleting(null)} onConfirm={() => remove.mutate(deleting)} />
    </>
  )
}
