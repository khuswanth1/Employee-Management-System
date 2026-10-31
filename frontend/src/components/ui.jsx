import { createContext, useCallback, useContext, useEffect, useId, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchBlobUrl } from '../lib/api'
import { label } from '../lib/format'

export const cx = (...a) => a.filter(Boolean).join(' ')

/* ---------- buttons & form controls ---------- */
const BTN = {
  primary: 'bg-brand-600 text-white hover:bg-brand-700 disabled:bg-brand-600/50',
  secondary: 'bg-white text-slate-700 border border-slate-300 hover:bg-slate-50 disabled:opacity-50',
  danger: 'bg-red-600 text-white hover:bg-red-700 disabled:bg-red-600/50',
  ghost: 'text-slate-600 hover:bg-slate-100 disabled:opacity-50',
}
export function Button({ variant = 'primary', size = 'md', loading, className, children, ...p }) {
  return (
    <button
      {...p}
      disabled={p.disabled || loading}
      className={cx('inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors disabled:cursor-not-allowed',
        size === 'sm' ? 'px-2.5 py-1.5 text-xs' : 'px-4 py-2 text-sm', BTN[variant], className)}
    >
      {loading && <Spinner className="h-4 w-4" />}
      {children}
    </button>
  )
}

const inputCls = 'block w-full rounded-lg border border-slate-500 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm placeholder:text-slate-500 focus:border-brand-500 focus:ring-1 focus:ring-brand-500 disabled:bg-slate-100'

export function Field({ label: text, error, hint, children, required }) {
  const id = useId()
  const child = children && typeof children === 'object' && 'props' in children
    ? { ...children, props: { ...children.props, id, 'aria-invalid': !!error || undefined, 'aria-describedby': error ? `${id}-err` : undefined } }
    : children
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-medium text-slate-700">
        {text}{required && <span className="text-red-600" aria-hidden> *</span>}
      </label>
      {child}
      {hint && !error && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
      {error && <p id={`${id}-err`} role="alert" className="mt-1 text-xs text-red-600">{error}</p>}
    </div>
  )
}
export const Input = ({ className, ...p }) => <input {...p} className={cx(inputCls, className)} />

export function PasswordInput({ className, ...p }) {
  const [show, setShow] = useState(false)
  return (
    <div className="relative">
      <input
        {...p}
        type={show ? 'text' : 'password'}
        className={cx(inputCls, 'pr-10', className)}
      />
      <button
        type="button"
        onClick={() => setShow(!show)}
        className="absolute inset-y-0 right-0 flex items-center pr-3 text-slate-400 hover:text-slate-600 transition-colors focus:outline-hidden"
        aria-label={show ? 'Hide password' : 'Show password'}
        title={show ? 'Hide password' : 'Show password'}
        tabIndex={-1}
      >
        {show ? (
          <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
            <line x1="1" y1="1" x2="23" y2="23" />
          </svg>
        ) : (
          <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
            <circle cx="12" cy="12" r="3" />
          </svg>
        )}
      </button>
    </div>
  )
}

export const Textarea = ({ className, ...p }) => <textarea rows={3} {...p} className={cx(inputCls, className)} />
export const Select = ({ className, children, ...p }) => <select {...p} className={cx(className?.includes('w-') ? inputCls.replace('w-full', '') : inputCls, 'form-select', className)}>{children}</select>

export function SearchInput({ value, onChange, placeholder = 'Search…' }) {
  return (
    <div className="relative">
      <svg className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" viewBox="0 0 20 20" fill="currentColor" aria-hidden><path fillRule="evenodd" d="M9 3.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM2 9a7 7 0 1112.45 4.39l3.58 3.58-1.06 1.06-3.58-3.58A7 7 0 012 9z" clipRule="evenodd" /></svg>
      <input type="search" aria-label={placeholder} value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className={cx(inputCls, 'pl-9')} />
    </div>
  )
}

/* ---------- display ---------- */
export const Card = ({ title, action, children, className, pad = true }) => (
  <section className={cx('rounded-xl border border-slate-200 bg-white shadow-sm', className)}>
    {(title || action) && (
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-3">
        <h2 className="text-sm font-semibold text-slate-900">{title}</h2>{action}
      </header>
    )}
    <div className={pad ? 'p-5' : ''}>{children}</div>
  </section>
)

const TONES = {
  gray: 'bg-slate-100 text-slate-700', green: 'bg-emerald-100 text-emerald-800', red: 'bg-red-100 text-red-800',
  amber: 'bg-amber-100 text-amber-800', blue: 'bg-sky-100 text-sky-800', indigo: 'bg-brand-100 text-brand-700', purple: 'bg-purple-100 text-purple-800',
}
export const Badge = ({ tone = 'gray', children }) => <span className={cx('inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium', TONES[tone])}>{children}</span>

const STATUS_TONE = {
  active: 'green', approved: 'green', done: 'green', reviewed: 'green', success: 'green', completed: 'green',
  pending: 'amber', pending_approval: 'amber', review: 'amber', onboarding: 'amber', planning: 'gray', todo: 'gray', scheduled: 'blue',
  in_progress: 'blue', on_hold: 'amber', needs_changes: 'red', rejected: 'red', failed: 'red', offboarded: 'gray', suspended: 'red',
  changes_requested: 'red', critical: 'red', verified: 'green', expired: 'red', full_time: 'blue', part_time: 'blue', cancelled: 'gray', ended: 'gray', low: 'gray', medium: 'blue', high: 'amber', urgent: 'red',
}
export const StatusBadge = ({ value }) => <Badge tone={STATUS_TONE[value] || 'gray'}>{label(value)}</Badge>

export const Spinner = ({ className = 'h-5 w-5' }) => (
  <svg className={cx('animate-spin', className)} viewBox="0 0 24 24" fill="none" role="status" aria-label="Loading">
    <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" className="opacity-25" />
    <path d="M4 12a8 8 0 018-8" stroke="currentColor" strokeWidth="4" strokeLinecap="round" className="opacity-75" />
  </svg>
)
export const PageLoader = () => <div className="flex justify-center py-16 text-brand-600"><Spinner className="h-8 w-8" /></div>

export function EmptyState({ title, description, action }) {
  return (
    <div className="flex flex-col items-center rounded-xl border border-dashed border-slate-300 bg-white px-6 py-12 text-center">
      <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-slate-100 text-slate-400" aria-hidden>∅</div>
      <p className="text-sm font-semibold text-slate-900">{title}</p>
      {description && <p className="mt-1 max-w-sm text-sm text-slate-500">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

export function ErrorState({ error, onRetry }) {
  return (
    <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-5 text-sm text-red-800">
      <p className="font-semibold">Something went wrong</p>
      <p className="mt-1">{error?.message || 'Unexpected error'}</p>
      {onRetry && <Button variant="secondary" size="sm" className="mt-3" onClick={onRetry}>Try again</Button>}
    </div>
  )
}

export function Alert({ tone = 'red', children }) {
  const t = { red: 'border-red-200 bg-red-50 text-red-800', green: 'border-emerald-200 bg-emerald-50 text-emerald-800', amber: 'border-amber-200 bg-amber-50 text-amber-800' }[tone]
  return <div role={tone === 'red' ? 'alert' : 'status'} className={cx('rounded-lg border px-3 py-2 text-sm', t)}>{children}</div>
}

export function ProgressBar({ value = 0, tone = 'brand', label = 'Progress' }) {
  const color = value >= 100 ? 'bg-emerald-500' : tone === 'red' ? 'bg-red-500' : 'bg-brand-600'
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100" role="progressbar" aria-label={label} aria-valuenow={value} aria-valuemin={0} aria-valuemax={100}>
        <div className={cx('h-full rounded-full transition-all', color)} style={{ width: `${Math.min(100, value)}%` }} />
      </div>
      <span className="w-9 text-right text-xs tabular-nums text-slate-500">{value}%</span>
    </div>
  )
}

/** Profile photo when the person has uploaded one (`v` = their avatar_v), otherwise initials. */
export function Avatar({ name, size = 8, userId, v }) {
  const { data: src } = useQuery({
    queryKey: ['avatar', userId, v], queryFn: () => fetchBlobUrl(`/users/${userId}/avatar`),
    enabled: Boolean(userId && v), staleTime: Infinity, gcTime: Infinity, retry: false,
  })
  const dim = { width: size * 4, height: size * 4 }
  if (src) return <img src={src} alt="" aria-hidden className="inline-block shrink-0 rounded-full object-cover" style={dim} />
  const initials = (name || '?').split(' ').filter(Boolean).slice(0, 2).map((p) => p[0].toUpperCase()).join('')
  return <span aria-hidden className={cx('inline-flex shrink-0 items-center justify-center rounded-full bg-brand-100 text-xs font-semibold text-brand-700')} style={dim}>{initials}</span>
}

export function StatCard({ title, value, hint, tone = 'default' }) {
  const color = tone === 'danger' && value > 0 ? 'text-red-600' : 'text-slate-900'
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <p className="text-sm text-slate-500">{title}</p>
      <p className={cx('mt-1 text-3xl font-semibold tabular-nums', color)}>{value ?? '—'}</p>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  )
}

export function PageHeader({ title, description, actions }) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{title}</h1>
        {description && <p className="mt-1 text-sm text-slate-500">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

/** A titled group of related fields inside a form. Lays its children out in a responsive grid. */
export function FormSection({ title, description, children, cols = 2 }) {
  const id = useId()
  return (
    <section aria-labelledby={id} className="border-b border-slate-100 pb-5 last:border-b-0 last:pb-0">
      <h3 id={id} className="text-sm font-semibold text-slate-900">{title}</h3>
      {description && <p className="mt-0.5 text-xs text-slate-500">{description}</p>}
      <div className={cx('mt-3 grid gap-4', cols === 2 && 'sm:grid-cols-2', cols === 3 && 'sm:grid-cols-3')}>{children}</div>
    </section>
  )
}

/** Placeholder block shown while data loads; keeps the layout from jumping. */
export const Skeleton = ({ className }) => <div aria-hidden className={cx('animate-pulse rounded bg-slate-200/80', className)} />

export function TableSkeleton({ rows = 6, cols = 5 }) {
  return (
    <div role="status" aria-label="Loading" className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="h-10 border-b border-slate-200 bg-slate-50" />
      {Array.from({ length: rows }, (_, r) => (
        <div key={r} className="flex items-center gap-4 border-b border-slate-100 px-4 py-3 last:border-b-0">
          {Array.from({ length: cols }, (_, c) => <Skeleton key={c} className={cx('h-4', c === 0 ? 'w-40' : 'w-24 flex-1 max-w-[8rem]')} />)}
        </div>
      ))}
    </div>
  )
}

export function Tabs({ tabs, value, onChange }) {
  const onKey = (e) => {
    const i = tabs.findIndex((t) => t.id === value)
    const next = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[e.key]
    if (next === undefined) return
    e.preventDefault()
    const t = tabs[(next + tabs.length) % tabs.length]
    onChange(t.id)
    e.currentTarget.querySelector(`[data-tab="${t.id}"]`)?.focus()
  }
  return (
    <div role="tablist" onKeyDown={onKey} className="mb-4 flex gap-1 overflow-x-auto border-b border-slate-200">
      {tabs.map((t) => (
        <button key={t.id} role="tab" data-tab={t.id} aria-selected={value === t.id} tabIndex={value === t.id ? 0 : -1} onClick={() => onChange(t.id)}
          className={cx('-mb-px whitespace-nowrap border-b-2 px-4 py-2 text-sm font-medium', value === t.id ? 'border-brand-600 text-brand-700' : 'border-transparent text-slate-500 hover:text-slate-700')}>
          {t.label}
        </button>
      ))}
    </div>
  )
}

/* ---------- table & pagination ---------- */
/**
 * `columns[].sortKey` makes a header sortable; pass `sort={{ key, order }}` and `onSort(key)`. Sorting itself is the
 * caller's job (the server sorts, so it works across pages). Clickable rows are reachable and activatable by keyboard.
 */
export function Table({ caption, columns, rows, rowKey = (r) => r.id, empty, onRowClick, sort, onSort }) {
  if (!rows?.length) return empty || <EmptyState title="Nothing here yet" />
  return (
    // a scrollable region must be reachable by keyboard (WCAG 2.1.1), so the wrapper is a focusable, named region
    <div role="region" aria-label={caption} tabIndex={0} className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm focus-visible:outline-2 focus-visible:outline-brand-500">
      <table className="min-w-full divide-y divide-slate-200 text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-slate-50">
          <tr>{columns.map((c) => {
            const active = sort?.key === c.sortKey
            return (
              <th key={c.key} scope="col" aria-sort={c.sortKey ? (active ? (sort.order === 'desc' ? 'descending' : 'ascending') : 'none') : undefined}
                className={cx('px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500', c.className)}>
                {c.sortKey && onSort ? (
                  <button type="button" onClick={() => onSort(c.sortKey)} className="inline-flex items-center gap-1 uppercase tracking-wide hover:text-slate-800">
                    {c.header}<span aria-hidden className={active ? 'text-brand-600' : 'text-slate-300'}>{active ? (sort.order === 'desc' ? '▼' : '▲') : '↕'}</span>
                  </button>
                ) : c.header}
              </th>
            )
          })}</tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((r) => (
            <tr key={rowKey(r)} onClick={onRowClick ? () => onRowClick(r) : undefined}
              tabIndex={onRowClick ? 0 : undefined}
              onKeyDown={onRowClick ? (e) => { if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); onRowClick(r) } } : undefined}
              className={cx('hover:bg-slate-50 focus-visible:bg-slate-50 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-brand-500', onRowClick && 'cursor-pointer')}>
              {columns.map((c) => <td key={c.key} className={cx('px-4 py-3 align-middle text-slate-700', c.className)}>{c.render ? c.render(r) : r[c.key]}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function Pagination({ page, pageSize, total, onChange }) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  if (total <= pageSize) return null
  return (
    <nav aria-label="Pagination" className="mt-4 flex items-center justify-between text-sm text-slate-600">
      <span>Page {page} of {pages} · {total} total</span>
      <div className="flex gap-2">
        <Button variant="secondary" size="sm" disabled={page <= 1} onClick={() => onChange(page - 1)}>Previous</Button>
        <Button variant="secondary" size="sm" disabled={page >= pages} onClick={() => onChange(page + 1)}>Next</Button>
      </div>
    </nav>
  )
}

/* ---------- modal & confirm ---------- */
export function Modal({ open, onClose, title, children, footer, wide }) {
  const ref = useRef(null)
  const titleId = useId()
  const closeRef = useRef(onClose) // callers pass a new function every render; re-running the effect would steal focus on each keystroke
  closeRef.current = onClose
  useEffect(() => {
    if (!open) return
    const prev = document.activeElement
    const onKey = (e) => {
      if (e.key === 'Escape') closeRef.current()
      if (e.key === 'Tab' && ref.current) { // focus trap
        const f = ref.current.querySelectorAll('button,[href],input,select,textarea,[tabindex]:not([tabindex="-1"])')
        if (!f.length) return
        const first = f[0], last = f[f.length - 1]
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
      }
    }
    document.addEventListener('keydown', onKey)
    ref.current?.querySelector('input,select,textarea,button')?.focus()
    return () => { document.removeEventListener('keydown', onKey); prev?.focus?.() }
  }, [open])
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/50 p-0 sm:items-center sm:p-4" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} role="dialog" aria-modal="true" aria-labelledby={titleId}
        className={cx('flex max-h-[92vh] w-full flex-col rounded-t-2xl bg-white shadow-xl sm:rounded-2xl', wide ? 'max-w-3xl' : 'max-w-lg')}>
        <header className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
          <h2 id={titleId} className="text-base font-semibold text-slate-900">{title}</h2>
          <button onClick={onClose} aria-label="Close dialog" className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600">✕</button>
        </header>
        <div className="overflow-y-auto px-5 py-4">{children}</div>
        {footer && <footer className="flex justify-end gap-2 border-t border-slate-100 px-5 py-3">{footer}</footer>}
      </div>
    </div>
  )
}

export function ConfirmDialog({ open, title, message, confirmLabel = 'Confirm', danger, onConfirm, onClose, loading }) {
  return (
    <Modal open={open} onClose={onClose} title={title}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button variant={danger ? 'danger' : 'primary'} loading={loading} onClick={onConfirm}>{confirmLabel}</Button></>}>
      <p className="text-sm text-slate-600">{message}</p>
    </Modal>
  )
}

/* ---------- toasts ---------- */
const ToastCtx = createContext(() => {})
export const useToast = () => useContext(ToastCtx)
export function ToastProvider({ children }) {
  const [items, setItems] = useState([])
  const push = useCallback((message, tone = 'green') => {
    const id = Math.random().toString(36).slice(2)
    setItems((s) => [...s, { id, message, tone }])
    setTimeout(() => setItems((s) => s.filter((t) => t.id !== id)), 4500)
  }, [])
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2">
        {items.map((t) => (
          <div key={t.id} className={cx('pointer-events-auto rounded-lg px-4 py-3 text-sm text-white shadow-lg', t.tone === 'red' ? 'bg-red-600' : 'bg-slate-900')}>{t.message}</div>
        ))}
      </div>
    </ToastCtx.Provider>
  )
}
