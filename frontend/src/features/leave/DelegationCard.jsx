import { useState } from 'react'
import { Alert, Badge, Button, Card, EmptyState, Field, Input, Modal, Select, Table, cx } from '../../components/ui'
import { api, fieldErrors } from '../../lib/api'
import { fmtDate } from '../../lib/format'
import { useAction, useApi } from '../../lib/hooks'
import { useAuth } from '../auth/AuthContext'
import { iso } from './LeaveRequestDialog'

function NewDelegation({ onClose }) {
  const { user } = useAuth()
  const { data: dir } = useApi('/employees/directory')
  const [f, setF] = useState({ delegate_id: '', start_date: iso(new Date()), end_date: '' })
  const send = useAction(() => api.post('/leave/delegations', { ...f, delegate_id: Number(f.delegate_id) }), { invalidate: ['/leave/delegations'], success: 'Approvals delegated', onSuccess: onClose })
  const fe = fieldErrors(send.error)
  const people = (dir?.items || []).filter((u) => ['manager', 'hr', 'founder'].includes(u.role) && u.id !== user.id)
  return (
    <Modal open onClose={onClose} title="Delegate leave approvals"
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={send.isPending} disabled={!f.delegate_id || !f.end_date} onClick={() => send.mutate()}>Delegate</Button></>}>
      <div className="space-y-4">
        {send.error && !Object.keys(fe).length && <Alert>{send.error.message}</Alert>}
        <p className="text-sm text-slate-600">While this is active, the person you choose can approve or reject your direct reports&apos; leave. They never decide their own requests, and you can end it at any time.</p>
        <Field label="Delegate to" required><Select value={f.delegate_id} onChange={(e) => setF((s) => ({ ...s, delegate_id: e.target.value }))}><option value="">Select…</option>{people.map((u) => <option key={u.id} value={u.id}>{u.full_name} ({u.role})</option>)}</Select></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="From" required error={fe.start_date}><Input type="date" value={f.start_date} onChange={(e) => setF((s) => ({ ...s, start_date: e.target.value }))} /></Field>
          <Field label="Until" required error={fe.end_date}><Input type="date" min={f.start_date} value={f.end_date} onChange={(e) => setF((s) => ({ ...s, end_date: e.target.value }))} /></Field>
        </div>
      </div>
    </Modal>
  )
}

/** Shown to managers on the approvals page: who may decide for them, and what has been delegated to them. */
export default function DelegationCard({ className }) {
  const { role } = useAuth()
  const [adding, setAdding] = useState(false)
  const { data } = useApi('/leave/delegations')
  const revoke = useAction((id) => api.del(`/leave/delegations/${id}`), { invalidate: ['/leave'], success: 'Delegation ended' })
  const items = (data?.items || []).filter((d) => !d.revoked && d.end_date >= iso(new Date()))
  return (
    <Card title="Delegation" className={cx('flex min-w-0 flex-col', className)} action={role === 'manager' ? <Button size="sm" variant="secondary" onClick={() => setAdding(true)}>Delegate my approvals</Button> : null} pad={false}>
      <div className="p-1">
        <Table caption="Delegations" rows={items} empty={<EmptyState title="No active delegations" description={role === 'manager' ? 'Going away? Let a colleague approve your team’s leave.' : 'Nobody has delegated approvals to you.'} />}
          columns={[
            { key: 'who', header: 'Who', render: (d) => (d.direction === 'given' ? `You → ${d.delegate}` : `${d.delegator} → you`) },
            { key: 'dates', header: 'Period', render: (d) => `${fmtDate(d.start_date)} – ${fmtDate(d.end_date)}` },
            { key: 'active', header: '', render: (d) => (d.active ? <Badge tone="green">active</Badge> : <Badge tone="gray">scheduled</Badge>) },
            { key: 'a', header: '', render: (d) => (d.direction === 'given' ? <Button size="sm" variant="ghost" onClick={() => revoke.mutate(d.id)}>End</Button> : null) },
          ]} />
      </div>
      {adding && <NewDelegation onClose={() => setAdding(false)} />}
    </Card>
  )
}
