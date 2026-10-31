import { useId, useState } from 'react'
import { cx } from './ui'

/** Free-text chips: Enter or comma adds, Backspace on an empty box removes the last, each chip has a remove button. */
export default function TagInput({ value = [], onChange, placeholder = 'Type and press Enter', max = 50, disabled, label = 'Entries' }) {
  const [draft, setDraft] = useState('')
  const id = useId()
  const add = (raw) => {
    const t = raw.trim().replace(/,$/, '').trim()
    if (!t || value.length >= max || value.some((v) => v.toLowerCase() === t.toLowerCase())) { setDraft(''); return }
    onChange([...value, t.slice(0, 60)])
    setDraft('')
  }
  return (
    <div className={cx('flex min-h-[2.5rem] flex-wrap items-center gap-1.5 rounded-lg border border-slate-500 bg-white px-2 py-1.5 shadow-sm focus-within:border-brand-500 focus-within:ring-1 focus-within:ring-brand-500', disabled && 'bg-slate-100')}>
      <ul className="contents" aria-label={label}>
        {value.map((t) => (
          <li key={t} className="inline-flex items-center gap-1 rounded-full bg-brand-100 px-2 py-0.5 text-xs font-medium text-brand-700">
            {t}
            {!disabled && <button type="button" aria-label={`Remove ${t}`} className="rounded-full px-0.5 hover:bg-brand-200" onClick={() => onChange(value.filter((v) => v !== t))}>×</button>}
          </li>
        ))}
      </ul>
      {!disabled && (
        <input id={id} value={draft} placeholder={value.length ? '' : placeholder} aria-label={`Add to ${label.toLowerCase()}`} className="min-w-[8rem] flex-1 border-0 bg-transparent p-0.5 text-sm outline-none focus:ring-0"
          onChange={(e) => (e.target.value.endsWith(',') ? add(e.target.value) : setDraft(e.target.value))}
          onKeyDown={(e) => {
            if (e.key === 'Enter') { e.preventDefault(); add(draft) }
            else if (e.key === 'Backspace' && !draft && value.length) onChange(value.slice(0, -1))
          }}
          onBlur={() => add(draft)} />
      )}
    </div>
  )
}
