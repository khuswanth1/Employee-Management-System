import { useState } from 'react'
import { Alert, Button, Card, Field, Input, Modal, Textarea } from '../../components/ui'
import { api, fieldErrors } from '../../lib/api'
import { fmtDate } from '../../lib/format'
import { useAction, useApi } from '../../lib/hooks'
import { useAuth } from './AuthContext'

/** Submit or withdraw your own resignation. HR and your manager are told; nothing else changes until HR offboards you. */
export default function ResignationCard() {
  const { user, role } = useAuth()
  const { data } = useApi(`/employees/${user.id}/lifecycle`, undefined, { enabled: !['board_member', 'platform_admin'].includes(role) })
  const [open, setOpen] = useState(false)
  const [f, setF] = useState({ last_working_date: '', reason: '' })
  const tomorrow = new Date().toISOString().slice(0, 10)
  const submit = useAction(() => api.post(`/employees/${user.id}/lifecycle/resignation`, { last_working_date: f.last_working_date, reason: f.reason || null }),
    { invalidate: [`/employees/${user.id}/lifecycle`, '/lifecycle'], success: 'Your resignation was submitted', onSuccess: () => setOpen(false) })
  const withdraw = useAction(() => api.post(`/employees/${user.id}/lifecycle/resignation/withdraw`, {}), { invalidate: [`/employees/${user.id}/lifecycle`], success: 'Resignation withdrawn' })
  const fe = fieldErrors(submit.error)
  if (!data || !['employee', 'manager', 'hr'].includes(role)) return null
  const resigned = data.state.resigned
  return (
    <Card title="Resignation">
      {resigned ? (
        <div className="space-y-3 text-sm">
          <p>Your resignation is on record. Your last working day is <strong>{data.state.last_working_date ? fmtDate(data.state.last_working_date) : '—'}</strong>.</p>
          <Button variant="secondary" loading={withdraw.isPending} onClick={() => window.confirm('Withdraw your resignation?') && withdraw.mutate()}>Withdraw resignation</Button>
        </div>
      ) : (
        <div className="space-y-3 text-sm"><p className="text-slate-600">Leaving? Tell HR and your manager here. This does not end your access: HR does that on your last day.</p>
          <Button variant="secondary" onClick={() => setOpen(true)}>Submit resignation</Button></div>
      )}
      {open && (
        <Modal open onClose={() => setOpen(false)} title="Submit your resignation"
          footer={<><Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button><Button variant="danger" loading={submit.isPending} disabled={!f.last_working_date} onClick={() => submit.mutate()}>Submit resignation</Button></>}>
          <div className="space-y-4">
            {submit.error && !Object.keys(fe).length && <Alert>{submit.error.message}</Alert>}
            <Alert tone="amber">HR and your manager are notified straight away.</Alert>
            <Field label="Last working day" required error={fe.last_working_date}><Input type="date" min={tomorrow} value={f.last_working_date} onChange={(e) => setF((s) => ({ ...s, last_working_date: e.target.value }))} /></Field>
            <Field label="Reason (optional)"><Textarea value={f.reason} onChange={(e) => setF((s) => ({ ...s, reason: e.target.value }))} maxLength={1000} /></Field>
          </div>
        </Modal>
      )}
    </Card>
  )
}
