import { useState } from 'react'
import { Alert, Button, Field, Input, Select, Textarea, cx } from '../../components/ui'
import { fieldErrors } from '../../lib/api'
import { fmtMinutes, splitMinutes, toMinutes } from '../../lib/todoTree'

export const PRIORITIES = [['high', 'High'], ['medium', 'Medium'], ['low', 'Low']]
export const STATUSES = [['todo', 'To do'], ['in_progress', 'In progress'], ['completed', 'Completed']]
export const PRIORITY_LABEL = Object.fromEntries(PRIORITIES)

/* ---------- icons (inline, decorative) ---------- */
const PATHS = {
  plus: 'M12 5v14M5 12h14',
  clock: 'M12 7v5l3 2M21 12a9 9 0 11-18 0 9 9 0 0118 0z',
  edit: 'M4 20h4l10.5-10.5a2.1 2.1 0 00-3-3L5 17v3zM13.5 8.5l3 3',
  trash: 'M5 7h14M10 11v6M14 11v6M6 7l1 12a2 2 0 002 2h6a2 2 0 002-2l1-12M9 7V4h6v3',
  up: 'M12 19V5M6 11l6-6 6 6',
  down: 'M12 5v14M6 13l6 6 6-6',
  chevron: 'M6 9l6 6 6-6',
  search: 'M21 21l-4.3-4.3M17 10.5a6.5 6.5 0 11-13 0 6.5 6.5 0 0113 0z',
  grip: 'M9 6h.01M9 12h.01M9 18h.01M15 6h.01M15 12h.01M15 18h.01',
  list: 'M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01',
  check: 'M5 13l4 4L19 7',
  flag: 'M5 21V4m0 0h11l-2 4 2 4H5',
}
export function Icon({ name, className = 'h-4 w-4', stroke = 2 }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true" focusable="false">
      <path d={PATHS[name]} />
    </svg>
  )
}

/* ---------- visual vocabulary: one place for the priority and status colours ---------- */
export const PRIORITY_STYLE = {
  high: { edge: 'border-l-red-500', chip: 'bg-red-50 text-red-700 ring-red-200', dot: 'bg-red-500' },
  medium: { edge: 'border-l-amber-400', chip: 'bg-amber-50 text-amber-800 ring-amber-200', dot: 'bg-amber-500' },
  low: { edge: 'border-l-slate-300', chip: 'bg-slate-100 text-slate-700 ring-slate-200', dot: 'bg-slate-400' },
}
export const STATUS_STYLE = {
  todo: 'bg-slate-100 text-slate-800 ring-slate-300',
  in_progress: 'bg-sky-50 text-sky-800 ring-sky-300',
  completed: 'bg-emerald-50 text-emerald-800 ring-emerald-300',
}

export function PriorityChip({ priority }) {
  const s = PRIORITY_STYLE[priority]
  return (
    <span className={cx('inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset', s.chip)}>
      <span className={cx('h-1.5 w-1.5 rounded-full', s.dot)} aria-hidden="true" />{PRIORITY_LABEL[priority]} priority
    </span>
  )
}

export function TimeChip({ minutes }) {
  if (!minutes) return null
  return (
    <span className="inline-flex items-center gap-1 rounded-md bg-brand-50 px-2 py-0.5 text-xs font-medium text-brand-700 ring-1 ring-inset ring-brand-100">
      <Icon name="clock" className="h-3.5 w-3.5" /><span className="sr-only">Estimated time </span>{fmtMinutes(minutes)}
    </span>
  )
}

export function Meter({ value, label }) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-200" role="progressbar" aria-label={label} aria-valuenow={value} aria-valuemin={0} aria-valuemax={100}>
      <div className={cx('h-full rounded-full transition-all', value >= 100 ? 'bg-emerald-500' : 'bg-brand-600')} style={{ width: `${Math.min(100, value)}%` }} />
    </div>
  )
}

export function IconButton({ icon, label, onClick, disabled, tone = 'default', pressed }) {
  return (
    <button type="button" onClick={onClick} disabled={disabled} aria-label={label} title={label} aria-expanded={pressed}
      className={cx('inline-flex h-8 w-8 items-center justify-center rounded-lg border border-transparent transition-colors disabled:cursor-not-allowed disabled:opacity-30',
        tone === 'danger' ? 'text-red-700 hover:bg-red-50' : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900')}>
      <Icon name={icon} />
    </button>
  )
}

/* ---------- time input ---------- */
export function Duration({ value, onChange, idPrefix, compact }) {
  const set = (k) => (e) => onChange({ ...value, [k]: e.target.value.replace(/\D/g, '').slice(0, 4) })
  const cls = cx('text-center', compact ? 'w-14 !px-2 !py-1.5' : 'w-16')
  return (
    <div className="flex items-center gap-1.5">
      <Input aria-label="Hours" id={`${idPrefix}-h`} inputMode="numeric" className={cls} placeholder="0" value={value.h} onChange={set('h')} />
      <span className="text-xs font-medium text-slate-600">h</span>
      <Input aria-label="Minutes" id={`${idPrefix}-m`} inputMode="numeric" className={cls} placeholder="0" value={value.m} onChange={set('m')} />
      <span className="text-xs font-medium text-slate-600">min</span>
    </div>
  )
}

/* ---------- the edit dialog's form ---------- */
export function TaskForm({ initial, kind = 'task', submitLabel, onSubmit, onCancel, pending, error }) {
  const [f, setF] = useState(() => ({
    title: initial?.title || '', notes: initial?.notes || '', priority: initial?.priority || 'medium', status: initial?.status || 'todo',
    dur: splitMinutes(initial?.duration_minutes),
  }))
  const fe = fieldErrors(error)
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }))
  const submit = (e) => {
    e.preventDefault()
    onSubmit({ title: f.title, notes: f.notes || null, priority: f.priority, status: f.status, duration_minutes: toMinutes(f.dur.h, f.dur.m) })
  }
  return (
    <form id="todo-form" onSubmit={submit} className="space-y-4" noValidate>
      {error && !Object.keys(fe).length && <Alert>{error.message}</Alert>}
      <Field label={kind === 'subtask' ? 'Subtask title' : 'Task title'} required error={fe.title}>
        <Input value={f.title} onChange={set('title')} maxLength={200} required autoFocus />
      </Field>
      <Field label="Notes" error={fe.notes}><Textarea value={f.notes} onChange={set('notes')} maxLength={2000} placeholder="Details, links or anything worth remembering" /></Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Priority"><Select value={f.priority} onChange={set('priority')}>{PRIORITIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select></Field>
        <Field label="Status"><Select value={f.status} onChange={set('status')}>{STATUSES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select></Field>
      </div>
      <div>
        <p className="mb-1 text-sm font-medium text-slate-700" id="dur-label">Estimated time</p>
        <div role="group" aria-labelledby="dur-label"><Duration value={f.dur} onChange={(dur) => setF((s) => ({ ...s, dur }))} idPrefix="edit-dur" /></div>
        {fe.duration_minutes && <p role="alert" className="mt-1 text-xs text-red-600">{fe.duration_minutes}</p>}
      </div>
      <div className="flex justify-end gap-2 border-t border-slate-100 pt-4">
        <Button type="button" variant="secondary" onClick={onCancel}>Cancel</Button>
        <Button type="submit" loading={pending}>{submitLabel}</Button>
      </div>
    </form>
  )
}

/* ---------- the "add" bar: new tasks (large) and new subtasks (compact) ---------- */
export function QuickAdd({ placeholder, label, onAdd, pending, compact }) {
  const [title, setTitle] = useState('')
  const [priority, setPriority] = useState('medium')
  const [dur, setDur] = useState({ h: '', m: '' })
  const [err, setErr] = useState('')
  const submit = (e) => {
    e.preventDefault()
    if (!title.trim()) { setErr('Enter a title'); return }
    setErr('')
    onAdd({ title, priority, duration_minutes: toMinutes(dur.h, dur.m) }, () => { setTitle(''); setDur({ h: '', m: '' }) })
  }
  const lab = 'mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-600'
  return (
    <form onSubmit={submit} noValidate
      className={cx('flex flex-wrap items-end gap-x-4 gap-y-3', compact ? 'rounded-lg border border-dashed border-slate-300 bg-slate-50 p-3' : 'rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5')}>
      <div className="min-w-[12rem] max-w-full flex-1">
        <label className="sr-only [overflow-wrap:anywhere]" htmlFor={`qa-${label}`}>{label}</label>
        <div className="relative">
          <span className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-slate-500"><Icon name="plus" /></span>
          <Input id={`qa-${label}`} value={title} onChange={(e) => setTitle(e.target.value)} placeholder={placeholder} maxLength={200}
            aria-invalid={!!err || undefined} className={cx('pl-9', compact ? '' : '!py-2.5 text-base')} />
        </div>
        {err && <p role="alert" className="mt-1 text-xs text-red-600">{err}</p>}
      </div>
      <div>
        <label className={lab} htmlFor={`qp-${label}`}>Priority</label>
        <Select id={`qp-${label}`} value={priority} onChange={(e) => setPriority(e.target.value)} className={cx('w-32', compact && '!py-1.5')}>{PRIORITIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select>
      </div>
      <div>
        <p className={lab}>Estimate</p>
        <Duration value={dur} onChange={setDur} idPrefix={`qa-${label}`} compact={compact} />
      </div>
      <Button type="submit" loading={pending} className={compact ? '' : '!px-5 !py-2.5'}>{compact ? 'Add subtask' : 'Add task'}</Button>
    </form>
  )
}

/* ---------- one task / subtask card ---------- */
export function Row({ t, sub, canReorder, first, last, onToggle, onStatus, onEdit, onDelete, onMove, subOpen, onToggleSub, drag, children }) {
  const done = t.status === 'completed'
  const name = t.title
  const pct = t.subtask_count ? Math.round((100 * t.subtasks_done) / t.subtask_count) : 0
  const hover = drag.hover?.id === t.id ? drag.hover.pos : null
  return (
    <div
      draggable={canReorder}
      onDragStart={(e) => { if (!canReorder || e.target.closest?.('input,textarea,select')) { e.preventDefault(); return } e.stopPropagation(); e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', String(t.id)); drag.start(t) }}
      onDragEnd={drag.end}
      onDragOver={(e) => drag.over(e, t, sub)}
      onDragLeave={() => drag.leave(t)}
      onDrop={(e) => drag.drop(e, t, sub)}
      data-task-id={t.id}
      className={cx('relative rounded-xl border border-l-4 bg-white transition-shadow', PRIORITY_STYLE[t.priority].edge,
        sub ? 'border-slate-200 px-3 py-2.5' : 'border-slate-200 p-4 shadow-sm hover:shadow-md',
        done && 'bg-slate-50', drag.dragId === t.id && 'opacity-40',
        hover === 'before' && 'before:absolute before:inset-x-0 before:-top-2 before:h-1 before:rounded before:bg-brand-600',
        hover === 'after' && 'after:absolute after:inset-x-0 after:-bottom-2 after:h-1 after:rounded after:bg-brand-600',
        hover === 'inside' && 'bg-brand-50 ring-2 ring-brand-600')}
    >
      <div className="flex flex-wrap items-start gap-x-3 gap-y-3">
        <span className={cx('mt-0.5 select-none', canReorder ? 'cursor-grab text-slate-500 active:cursor-grabbing' : 'text-slate-300')} title={canReorder ? 'Drag to reorder' : 'Clear filters to reorder'}>
          <Icon name="grip" className="h-5 w-5" stroke={3} />
        </span>
        <input type="checkbox" checked={done} onChange={(e) => onToggle(t, e.target.checked)} aria-label={`Mark "${name}" as completed`}
          className="mt-0.5 h-5 w-5 shrink-0 cursor-pointer rounded-full border-slate-500 accent-emerald-600" />
        <div className="min-w-0 flex-1 basis-56">
          <p data-role="title" className={cx('min-w-0 [overflow-wrap:anywhere] font-semibold leading-snug', sub ? 'text-sm' : 'text-base', done ? 'text-slate-500 line-through decoration-slate-400' : 'text-slate-900')}>{name}</p>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            <PriorityChip priority={t.priority} />
            <TimeChip minutes={t.duration_minutes} />
          </div>
          {t.notes && <p className="mt-2 whitespace-pre-line text-sm text-slate-600 [overflow-wrap:anywhere]">{t.notes}</p>}
          {!sub && t.subtask_count > 0 && (
            <div className="mt-3 max-w-md">
              <Meter value={pct} label={`Subtasks completed for ${name}`} />
              <p className="mt-1 text-xs text-slate-600">{t.subtasks_done} of {t.subtask_count} subtasks done · time needed {fmtMinutes(t.total_minutes)}{t.remaining_minutes === 0 ? ' · all done' : t.remaining_minutes !== t.total_minutes ? ` (${fmtMinutes(t.remaining_minutes)} left)` : ''}</p>
            </div>
          )}
        </div>
        <div className="flex w-full flex-wrap items-center gap-1 sm:w-auto sm:justify-end">
          <label className="sr-only" htmlFor={`st-${t.id}`}>Status of {name}</label>
          <select id={`st-${t.id}`} value={t.status} onChange={(e) => onStatus(t, e.target.value)}
            className={cx('h-8 cursor-pointer appearance-none rounded-full border-0 py-0 px-3 text-center text-xs font-semibold ring-1 ring-inset focus:ring-2 focus:ring-brand-600', STATUS_STYLE[t.status])}>
            {STATUSES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
          {!sub && (
            <button type="button" aria-expanded={subOpen} onClick={onToggleSub}
              className="inline-flex h-8 items-center gap-1 rounded-lg px-2 text-xs font-medium text-slate-700 hover:bg-slate-100">
              <Icon name="list" className="h-4 w-4" />{subOpen ? 'Hide subtasks' : `Subtasks (${t.subtask_count || 0})`}
              <Icon name="chevron" className={cx('h-3.5 w-3.5 transition-transform', subOpen && 'rotate-180')} />
            </button>
          )}
          <span className="mx-0.5 hidden h-5 w-px bg-slate-200 sm:block" aria-hidden="true" />
          <div className="ml-auto flex items-center sm:ml-0">
          <IconButton icon="up" label={`Move "${name}" up`} disabled={!canReorder || first} onClick={() => onMove(t, -1)} />
          <IconButton icon="down" label={`Move "${name}" down`} disabled={!canReorder || last} onClick={() => onMove(t, 1)} />
          <IconButton icon="edit" label={`Edit "${name}"`} onClick={() => onEdit(t)} />
          <IconButton icon="trash" tone="danger" label={`Delete "${name}"`} onClick={() => onDelete(t)} />
          </div>
        </div>
      </div>
      {children}
    </div>
  )
}
