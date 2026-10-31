import { useEffect, useState } from 'react'
import { Alert, Button, Field, Input, Modal, Select, Textarea } from '../../components/ui'
import { api, fieldErrors } from '../../lib/api'
import { useAction } from '../../lib/hooks'

export const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const blank = { leave_type_id: '', start_date: '', end_date: '', half_day: '', reason: '' }

/**
 * mode 'new'    -> POST /leave/requests
 * mode 'edit'   -> PATCH /leave/requests/:id           (pending request)
 * mode 'revise' -> POST /leave/requests/:id/revise     (approved, not started: a new request replaces it once approved)
 */
export default function LeaveRequestDialog({ open, onClose, types, mode = 'new', request }) {
  const [f, setF] = useState(blank)
  useEffect(() => {
    if (open) setF(request ? { leave_type_id: String(request.leave_type_id), start_date: request.start_date, end_date: request.end_date, half_day: request.half_day || '', reason: request.reason || '' } : blank)
  }, [open, request])
  const body = () => ({ leave_type_id: Number(f.leave_type_id), start_date: f.start_date, end_date: f.end_date, half_day: f.half_day || null, reason: f.reason || null })
  const send = useAction(() => {
    if (mode === 'edit') return api.patch(`/leave/requests/${request.id}`, body())
    if (mode === 'revise') return api.post(`/leave/requests/${request.id}/revise`, body())
    return api.post('/leave/requests', body())
  }, {
    invalidate: ['/leave', '/dashboard'],
    success: { new: 'Leave request submitted', edit: 'Request updated', revise: 'Revision sent for approval' }[mode],
    onSuccess: onClose,
  })
  const fe = fieldErrors(send.error)
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }))
  const type = types.find((t) => String(t.id) === String(f.leave_type_id))
  const single = f.start_date && f.start_date === f.end_date
  const title = { new: 'Apply for leave', edit: 'Edit leave request', revise: 'Request a change to approved leave' }[mode]
  return (
    <Modal open={open} onClose={onClose} title={title}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button loading={send.isPending} disabled={!f.leave_type_id || !f.start_date || !f.end_date} onClick={() => send.mutate()}>{mode === 'revise' ? 'Send revision' : mode === 'edit' ? 'Save changes' : 'Submit request'}</Button></>}>
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); send.mutate() }}>
        {send.error && !Object.keys(fe).length && <Alert>{send.error.message}</Alert>}
        {mode === 'revise' && <Alert tone="amber">Your approved leave stays in place, and its days stay deducted, until the new dates are approved.</Alert>}
        <Field label="Leave type" required><Select value={f.leave_type_id} onChange={set('leave_type_id')} required><option value="">Select…</option>{types.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</Select></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="From" required error={fe.start_date}><Input type="date" min={iso(new Date())} value={f.start_date} onChange={(e) => setF((s) => ({ ...s, start_date: e.target.value, end_date: s.end_date < e.target.value ? e.target.value : s.end_date, half_day: '' }))} required /></Field>
          <Field label="To" required error={fe.end_date}><Input type="date" min={f.start_date || iso(new Date())} value={f.end_date} onChange={(e) => setF((s) => ({ ...s, end_date: e.target.value, half_day: e.target.value === s.start_date ? s.half_day : '' }))} required /></Field>
        </div>
        {single && type?.allow_half_day !== false && (
          <Field label="Length" hint="A half day is for a single date">
            <Select value={f.half_day} onChange={set('half_day')}><option value="">Full day</option><option value="first">First half</option><option value="second">Second half</option></Select>
          </Field>
        )}
        <Field label="Reason"><Textarea value={f.reason} onChange={set('reason')} /></Field>
        <p className="text-xs text-slate-500">
          {type?.count_all_days ? 'Every calendar day in the range counts for this leave type.' : 'Days off in your branch’s working week and company holidays are not counted.'}
          {type?.min_notice_days ? ` Needs ${type.min_notice_days} days’ notice.` : ''}
        </p>
      </form>
    </Modal>
  )
}
