import { useState } from 'react'
import { Alert, Button, Field, Input, Modal, Select } from '../../components/ui'
import { api, fieldErrors } from '../../lib/api'
import { useAction } from '../../lib/hooks'

const blank = { name: '', annual_quota: 0, paid: true, accrual: 'annual_upfront', carry_forward_max: 0, carry_expiry_months: '', allow_half_day: true, count_all_days: false,
  min_notice_days: 0, max_consecutive_days: '', encashable: false, encash_max_days: '', is_active: true, apply_to_current_year: false }
const num = (v) => (v === '' || v == null ? null : Number(v))

export default function LeaveTypeDialog({ type, onClose }) {
  const [f, setF] = useState(type ? { ...blank, ...type, carry_expiry_months: type.carry_expiry_months ?? '', max_consecutive_days: type.max_consecutive_days ?? '', encash_max_days: type.encash_max_days ?? '' } : blank)
  const body = () => ({ ...f, name: f.name.trim(), annual_quota: Number(f.annual_quota), carry_forward_max: Number(f.carry_forward_max || 0), carry_expiry_months: num(f.carry_expiry_months),
    min_notice_days: Number(f.min_notice_days || 0), max_consecutive_days: num(f.max_consecutive_days), encash_max_days: num(f.encash_max_days) })
  const save = useAction(() => (type ? api.patch(`/leave/types/${type.id}`, body()) : api.post('/leave/types', body())),
    { invalidate: ['/leave'], success: type ? 'Leave type updated' : 'Leave type added', onSuccess: onClose })
  const fe = fieldErrors(save.error)
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }))
  const tick = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.checked }))
  const quotaChanged = type && Number(f.annual_quota) !== type.annual_quota
  return (
    <Modal open onClose={onClose} wide title={type ? `Edit ${type.name}` : 'New leave type'}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={save.isPending} disabled={f.name.trim().length < 2} onClick={() => save.mutate()}>Save</Button></>}>
      <div className="grid gap-4 sm:grid-cols-2">
        {save.error && !Object.keys(fe).length && <div className="sm:col-span-2"><Alert>{save.error.message}</Alert></div>}
        {type && <div className="sm:col-span-2"><Alert tone="amber">Policy changes apply from now on. Leave that is already approved or pending keeps the days it was counted with.</Alert></div>}
        <Field label="Name" required error={fe.name}><Input value={f.name} onChange={set('name')} maxLength={80} /></Field>
        <Field label="Days per year" required error={fe.annual_quota}><Input type="number" min="0" step="0.5" value={f.annual_quota} onChange={set('annual_quota')} /></Field>
        <Field label="How days are granted"><Select value={f.accrual} onChange={set('accrual')}><option value="annual_upfront">All at the start of the year</option><option value="monthly">Accrued monthly</option></Select></Field>
        <label className="flex items-center gap-2 pt-7 text-sm"><input type="checkbox" checked={f.paid} onChange={tick('paid')} /> Paid (has a balance; unpaid leave is tracked but not limited)</label>
        <Field label="Carry forward at most (days)" error={fe.carry_forward_max}><Input type="number" min="0" step="0.5" value={f.carry_forward_max} onChange={set('carry_forward_max')} /></Field>
        <Field label="Carried days lapse after month" hint="1–12; blank = never" error={fe.carry_expiry_months}><Input type="number" min="1" max="12" value={f.carry_expiry_months} onChange={set('carry_expiry_months')} disabled={!Number(f.carry_forward_max)} /></Field>
        <Field label="Minimum notice (days)" error={fe.min_notice_days}><Input type="number" min="0" value={f.min_notice_days} onChange={set('min_notice_days')} /></Field>
        <Field label="Longest stretch (days)" hint="Blank = no limit" error={fe.max_consecutive_days}><Input type="number" min="0.5" step="0.5" value={f.max_consecutive_days} onChange={set('max_consecutive_days')} /></Field>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.allow_half_day} onChange={tick('allow_half_day')} /> Half days allowed</label>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.count_all_days} onChange={tick('count_all_days')} /> Count weekends and holidays inside the range</label>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.encashable} onChange={tick('encashable')} /> Unused days can be encashed</label>
        <Field label="Encash at most (days / year)" error={fe.encash_max_days}><Input type="number" min="0.5" step="0.5" value={f.encash_max_days} onChange={set('encash_max_days')} disabled={!f.encashable} /></Field>
        {type && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.is_active} onChange={tick('is_active')} /> Available to employees</label>}
        {quotaChanged && f.accrual === 'annual_upfront' && (
          <label className="flex items-start gap-2 text-sm sm:col-span-2"><input className="mt-1" type="checkbox" checked={f.apply_to_current_year} onChange={tick('apply_to_current_year')} />
            <span>Also add the difference ({Number(f.annual_quota) - type.annual_quota > 0 ? '+' : ''}{Number(f.annual_quota) - type.annual_quota} days) to everyone's balance for this year. It is recorded as an adjustment in each person's history.</span></label>
        )}
      </div>
    </Modal>
  )
}
