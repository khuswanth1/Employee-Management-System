import { useEffect, useMemo, useRef, useState } from 'react'
import { cx } from './ui'

/** Searchable multi-select dropdown. options: [{ value, label, hint? }]; value: array of option values. */
export default function MultiSelect({ id, options, value, onChange, placeholder = 'Search and select…', emptyText = 'No matches', disabled }) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const root = useRef(null)
  const picked = useMemo(() => new Set(value), [value])
  const byValue = useMemo(() => new Map(options.map((o) => [o.value, o])), [options])
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return needle ? options.filter((o) => `${o.label} ${o.hint || ''}`.toLowerCase().includes(needle)) : options
  }, [options, q])

  useEffect(() => {
    if (!open) return undefined
    const away = (e) => { if (!root.current?.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', away)
    return () => document.removeEventListener('mousedown', away)
  }, [open])

  const toggle = (v) => onChange(picked.has(v) ? value.filter((x) => x !== v) : [...value, v])

  return (
    <div ref={root} className="relative" onKeyDown={(e) => { if (e.key === 'Escape') setOpen(false) }}>
      <div className={cx('flex min-h-[2.5rem] flex-wrap items-center gap-1.5 rounded-lg border bg-white px-2 py-1.5 shadow-sm', open ? 'border-brand-500 ring-1 ring-brand-500' : 'border-slate-300', disabled && 'bg-slate-100')}
        onClick={() => !disabled && setOpen(true)}>
        {value.map((v) => byValue.get(v) && (
          <span key={v} className="inline-flex items-center gap-1 rounded-full bg-brand-100 px-2 py-0.5 text-xs font-medium text-brand-700">
            {byValue.get(v).label}
            {!disabled && <button type="button" aria-label={`Remove ${byValue.get(v).label}`} className="rounded-full px-0.5 hover:bg-brand-200" onClick={(e) => { e.stopPropagation(); toggle(v) }}>×</button>}
          </span>
        ))}
        <input id={id} type="text" role="combobox" aria-expanded={open} aria-controls={`${id || 'ms'}-list`} autoComplete="off" disabled={disabled}
          value={q} onChange={(e) => { setQ(e.target.value); setOpen(true) }} onFocus={() => setOpen(true)}
          placeholder={value.length ? '' : placeholder} className="min-w-[8rem] flex-1 border-0 bg-transparent p-1 text-sm focus:outline-none focus:ring-0" />
      </div>
      {open && (
        <ul id={`${id || 'ms'}-list`} role="listbox" aria-multiselectable className="absolute z-30 mt-1 max-h-56 w-full overflow-auto rounded-lg border border-slate-200 bg-white py-1 shadow-lg">
          {shown.length === 0 && <li className="px-3 py-2 text-sm text-slate-500">{emptyText}</li>}
          {shown.map((o) => (
            <li key={o.value} role="option" aria-selected={picked.has(o.value)} onClick={() => toggle(o.value)}
              className={cx('flex cursor-pointer items-center gap-2 px-3 py-2 text-sm hover:bg-slate-50', picked.has(o.value) && 'bg-brand-50')}>
              <input type="checkbox" readOnly tabIndex={-1} checked={picked.has(o.value)} className="h-4 w-4 accent-brand-600" />
              <span className="min-w-0"><span className="block truncate text-slate-900">{o.label}</span>{o.hint && <span className="block truncate text-xs text-slate-500">{o.hint}</span>}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
