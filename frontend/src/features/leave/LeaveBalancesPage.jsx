import { useState } from 'react'
import { Alert, Button, EmptyState, ErrorState, Field, Input, Modal, PageHeader, PageLoader, Select, Table, useToast } from '../../components/ui'
import { api, download, fieldErrors } from '../../lib/api'
import { useAction, useApi } from '../../lib/hooks'
import { useAuth } from '../auth/AuthContext'

function Adjust({ row, types, kind, onClose }) {
  const [f, setF] = useState({ days: '', note: '' })
  const typeId = types.find((t) => t.name === row.leave_type)?.id
  const send = useAction(() => api.post(`/leave/balances/${row.user_id}/${kind}`, kind === 'adjust'
    ? { leave_type_id: typeId, days: Number(f.days), note: f.note.trim() }
    : { leave_type_id: typeId, days: Number(f.days), note: f.note.trim() || null }),
  { invalidate: ['/leave'], success: kind === 'adjust' ? 'Balance adjusted' : 'Encashment recorded', onSuccess: onClose })
  const fe = fieldErrors(send.error)
  const ok = f.days !== '' && Number(f.days) !== 0 && (kind === 'encash' || f.note.trim().length >= 3)
  return (
    <Modal open onClose={onClose} title={`${kind === 'adjust' ? 'Adjust' : 'Encash'} ${row.leave_type} for ${row.employee}`}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={send.isPending} disabled={!ok} onClick={() => send.mutate()}>{kind === 'adjust' ? 'Adjust' : 'Record encashment'}</Button></>}>
      <div className="space-y-4">
        {send.error && !Object.keys(fe).length && <Alert>{send.error.message}</Alert>}
        <p className="text-sm text-slate-600">{row.remaining} days remaining. {kind === 'encash' ? 'This records that days were paid out; there is no payroll link yet.' : 'Use a negative number to remove days.'}</p>
        <Field label="Days" required error={fe.days}><Input type="number" step="0.5" min={kind === 'encash' ? '0.5' : undefined} value={f.days} onChange={(e) => setF((s) => ({ ...s, days: e.target.value }))} /></Field>
        <Field label={kind === 'adjust' ? 'Reason' : 'Note'} required={kind === 'adjust'} error={fe.note}><Input value={f.note} onChange={(e) => setF((s) => ({ ...s, note: e.target.value }))} maxLength={300} /></Field>
      </div>
    </Modal>
  )
}

export default function LeaveBalancesPage() {
  const { role } = useAuth()
  const toast = useToast()
  const canEdit = role === 'hr' || role === 'founder'
  const [year, setYear] = useState(new Date().getFullYear())
  const [dlg, setDlg] = useState(null)
  const { data, isLoading, error, refetch } = useApi('/leave/reports/balances', { year })
  const { data: types } = useApi('/leave/types')
  const t = types?.items || []
  return (
    <>
      <PageHeader title="Leave balances" description="Everyone in your scope, by leave type"
        actions={<Button variant="secondary" onClick={() => download('/leave/reports/balances.csv', `leave-balances-${year}.csv`, { year }).catch((e) => toast(e.message, 'red'))}>Export CSV</Button>} />
      <div className="mb-4 w-40"><Field label="Year"><Select value={year} onChange={(e) => setYear(Number(e.target.value))}>{[-1, 0, 1].map((o) => <option key={o} value={new Date().getFullYear() + o}>{new Date().getFullYear() + o}</option>)}</Select></Field></div>
      {isLoading ? <PageLoader /> : error ? <ErrorState error={error} onRetry={refetch} /> : (
        <Table caption="Leave balances" rows={data.items} rowKey={(r) => `${r.user_id}-${r.leave_type}`} empty={<EmptyState title="No balances" />}
          columns={[
            { key: 'employee', header: 'Employee' }, { key: 'leave_type', header: 'Type' }, { key: 'allocated', header: 'Granted' }, { key: 'carried_in', header: 'Carried in' },
            { key: 'used', header: 'Used' }, { key: 'pending', header: 'Pending' }, { key: 'expired', header: 'Lapsed' }, { key: 'encashed', header: 'Encashed' },
            { key: 'remaining', header: 'Remaining', render: (r) => <strong>{r.remaining}</strong> },
            ...(canEdit ? [{ key: 'a', header: '', render: (r) => (
              <div className="flex gap-1"><Button size="sm" variant="ghost" onClick={() => setDlg({ row: r, kind: 'adjust' })}>Adjust</Button>
                {t.find((x) => x.name === r.leave_type)?.encashable && <Button size="sm" variant="ghost" onClick={() => setDlg({ row: r, kind: 'encash' })}>Encash</Button>}</div>) }] : []),
          ]} />
      )}
      {dlg && <Adjust {...dlg} types={t} onClose={() => setDlg(null)} />}
    </>
  )
}
