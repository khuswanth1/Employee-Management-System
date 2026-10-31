import { useState } from 'react'
import { Alert, Badge, Button, EmptyState, ErrorState, Field, Modal, PageHeader, PageLoader, Pagination, Select, Table, Textarea } from '../../components/ui'
import { api } from '../../lib/api'
import { fmtDate, fmtDateTime, fmtTimeIn } from '../../lib/format'
import { useAction, useApi } from '../../lib/hooks'

const TONE = { pending: 'amber', approved: 'green', rejected: 'red', cancelled: 'gray' }

function Decide({ item, approve, onClose }) {
  const [note, setNote] = useState('')
  const send = useAction(() => api.post(`/attendance/corrections/${item.id}/decision`, { approve, note: note.trim() || null }),
    { invalidate: ['/attendance'], success: approve ? 'Correction approved' : 'Correction rejected', onSuccess: onClose })
  return (
    <Modal open onClose={onClose} title={approve ? 'Approve correction' : 'Reject correction'}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button variant={approve ? 'primary' : 'danger'} loading={send.isPending} disabled={!approve && !note.trim()} onClick={() => send.mutate()}>{approve ? 'Approve' : 'Reject'}</Button></>}>
      <div className="space-y-3 text-sm">
        {send.error && <Alert>{send.error.message}</Alert>}
        <p><strong>{item.user_name}</strong> · {fmtDate(item.work_date)} · {fmtTimeIn(item.check_in, item.timezone)} – {fmtTimeIn(item.check_out, item.timezone)}</p>
        <p className="rounded bg-slate-50 p-2 text-slate-700">“{item.reason}”</p>
        {approve && <p className="text-slate-600">The day's check-in and check-out are replaced and the hours recalculated.</p>}
        <Field label={approve ? 'Note (optional)' : 'Reason for rejecting'} required={!approve}><Textarea value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} /></Field>
      </div>
    </Modal>
  )
}

export default function CorrectionsQueuePage() {
  const [status, setStatus] = useState('pending')
  const [page, setPage] = useState(1)
  const [dlg, setDlg] = useState(null) // { item, approve }
  const { data, isLoading, error, refetch } = useApi('/attendance/corrections', { status, page, page_size: 15 })
  return (
    <>
      <PageHeader title="Attendance corrections" description="Requests from people in your scope to fix their recorded times." />
      <div className="mb-4 w-52">
        <Field label="Show"><Select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }}>
          <option value="pending">Pending</option><option value="approved">Approved</option><option value="rejected">Rejected</option><option value="all">All</option>
        </Select></Field>
      </div>
      {isLoading ? <PageLoader /> : error ? <ErrorState error={error} onRetry={refetch} /> : (
        <>
          <Table caption="Correction requests" rows={data.items} empty={<EmptyState title="Nothing to review" />}
            columns={[
              { key: 'user_name', header: 'Employee' },
              { key: 'work_date', header: 'Day', render: (c) => fmtDate(c.work_date) },
              { key: 'times', header: 'Requested times', render: (c) => `${fmtTimeIn(c.check_in, c.timezone)} – ${fmtTimeIn(c.check_out, c.timezone)}` },
              { key: 'reason', header: 'Reason' },
              { key: 'created_at', header: 'Asked', render: (c) => fmtDateTime(c.created_at) },
              { key: 'status', header: 'Status', render: (c) => <Badge tone={TONE[c.status]}>{c.status}</Badge> },
              { key: 'actions', header: '', render: (c) => (c.status === 'pending' ? (
                <div className="flex gap-2"><Button size="sm" onClick={() => setDlg({ item: c, approve: true })}>Approve</Button><Button size="sm" variant="secondary" onClick={() => setDlg({ item: c, approve: false })}>Reject</Button></div>
              ) : (c.decided_by_name || '—')) },
            ]} />
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onChange={setPage} />
        </>
      )}
      {dlg && <Decide {...dlg} onClose={() => setDlg(null)} />}
    </>
  )
}
