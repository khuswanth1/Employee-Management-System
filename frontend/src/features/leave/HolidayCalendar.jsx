import { useEffect, useState } from 'react'
import { Alert, Button, Card, ConfirmDialog, Field, Input, Modal } from '../../components/ui'
import { api, fieldErrors } from '../../lib/api'
import { fmtDate } from '../../lib/format'
import { useAction, useApi } from '../../lib/hooks'

const isWeekend = (iso) => { if (!iso) return false; const d = new Date(`${iso}T00:00:00`).getDay(); return d === 0 || d === 6 }
const WEEKEND_MSG = 'Pick a weekday (Monday to Friday). Saturdays and Sundays are already days off.'
const weekday = (iso) => new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { weekday: 'short' })

export function HolidayModal({ open, onClose, holiday, year, presetDate }) {
  const isNew = !holiday
  const [f, setF] = useState({ name: '', date: '' })
  useEffect(() => { if (open) setF(holiday ? { name: holiday.name, date: holiday.date } : { name: '', date: presetDate || '' }) }, [open, holiday, presetDate])
  const save = useAction(() => (isNew ? api.post('/leave/holidays', f) : api.patch(`/leave/holidays/${holiday.id}`, f)),
    { invalidate: ['/leave', '/dashboard'], success: isNew ? 'Holiday added' : 'Holiday updated', onSuccess: onClose })
  const fe = fieldErrors(save.error)
  const weekend = isWeekend(f.date)
  return (
    <Modal open={open} onClose={onClose} title={isNew ? 'Add holiday' : 'Edit holiday'}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={save.isPending} disabled={weekend || !f.name.trim() || !f.date} onClick={() => save.mutate()}>{isNew ? 'Add holiday' : 'Save changes'}</Button></>}>
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (!weekend) save.mutate() }}>
        {save.error && !Object.keys(fe).length && <Alert>{save.error.message}</Alert>}
        <Field label="Name" required error={fe.name}><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required minLength={2} maxLength={120} /></Field>
        <Field label="Date" required error={weekend ? WEEKEND_MSG : fe.date} hint={`Working week is Monday to Friday. Showing ${year}.`}>
          <Input type="date" value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} required />
        </Field>
      </form>
    </Modal>
  )
}

/** Company holiday calendar. Everyone can view it; HR and founders (`canEdit`) add, edit and remove holidays. Working week is fixed Mon-Fri. */
export default function HolidayCalendar({ canEdit = false }) {
  const [year, setYear] = useState(new Date().getFullYear())
  const [editing, setEditing] = useState(null) // holiday | 'new' | null
  const [deleting, setDeleting] = useState(null)
  const { data } = useApi('/leave/holidays', { year })
  const del = useAction(() => api.del(`/leave/holidays/${deleting.id}`), { invalidate: ['/leave', '/dashboard'], success: 'Holiday removed', onSuccess: () => setDeleting(null) })
  return (
    <Card title={`Holiday calendar ${year}`} action={
      <div className="flex items-center gap-1">
        <Button size="sm" variant="secondary" aria-label="Previous year" onClick={() => setYear(year - 1)}>←</Button>
        <Button size="sm" variant="secondary" aria-label="Next year" onClick={() => setYear(year + 1)}>→</Button>
        {canEdit && <Button size="sm" onClick={() => setEditing('new')}>Add holiday</Button>}
      </div>}>
      <p className="mb-3 text-xs text-slate-500">Working days are Monday to Friday. Holidays are excluded from leave calculations.{canEdit ? '' : ' Only HR and founders can change this calendar.'}</p>
      {data?.items.length ? (
        <ul className="divide-y divide-slate-100 text-sm">
          {data.items.map((h) => (
            <li key={h.id} className="flex items-center justify-between gap-3 py-2">
              <span className="min-w-0 truncate">{h.name} · <span className="text-slate-500">{weekday(h.date)}, {fmtDate(h.date)}</span></span>
              {canEdit && <span className="flex shrink-0 gap-3">
                <button type="button" className="text-brand-700 hover:underline" aria-label={`Edit ${h.name}`} onClick={() => setEditing(h)}>Edit</button>
                <button type="button" className="text-red-600 hover:underline" aria-label={`Remove ${h.name}`} onClick={() => setDeleting(h)}>Remove</button>
              </span>}
            </li>
          ))}
        </ul>
      ) : <p className="text-sm text-slate-500">No holidays defined for {year}.</p>}
      {canEdit && <HolidayModal open={!!editing} onClose={() => setEditing(null)} holiday={editing === 'new' ? null : editing} year={year} />}
      {canEdit && <ConfirmDialog open={!!deleting} danger title="Remove holiday" confirmLabel="Remove" loading={del.isPending} onClose={() => setDeleting(null)} onConfirm={() => del.mutate()}
        message={`Remove "${deleting?.name}" (${deleting ? fmtDate(deleting.date) : ''}) from the calendar? Leave requests already approved are not recalculated.`} />}
    </Card>
  )
}
