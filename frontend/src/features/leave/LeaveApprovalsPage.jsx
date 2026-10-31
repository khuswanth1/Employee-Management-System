import { useState } from 'react'
import { Alert, Button, Card, EmptyState, ErrorState, Modal, PageHeader, PageLoader, Pagination, Select, StatusBadge, Table, Textarea, Field } from '../../components/ui'
import { api } from '../../lib/api'
import { fmtDate } from '../../lib/format'
import { useAction, useApi } from '../../lib/hooks'
import { useAuth } from '../auth/AuthContext'
import DelegationCard from './DelegationCard'

export default function LeaveApprovalsPage() {
  const { user } = useAuth()
  const [status, setStatus] = useState('pending')
  const [page, setPage] = useState(1)
  const [target, setTarget] = useState(null) // {request, approved}
  const [note, setNote] = useState('')
  const { data, isLoading, error, refetch } = useApi('/leave/requests', { status, page, page_size: 15 })
  const decide = useAction(() => api.post(`/leave/requests/${target.request.id}/decision`, { approved: target.approved, note: note || null }), {
    invalidate: ['/leave', '/dashboard'], success: 'Decision recorded', refreshOnError: true, onSuccess: () => { setTarget(null); setNote('') },
  })
  const close = () => { setTarget(null); decide.reset() }
  const open = (request, approved) => { decide.reset(); setTarget({ request, approved }) }
  return (
    <>
      <PageHeader title="Leave approvals" description="Review requests from the people you manage" />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <DelegationCard className="flex min-w-0 flex-col" />
        <Card
          title="Leave requests"
          pad={false}
          className="flex min-w-0 flex-col"
          action={
            <Select
              aria-label="Status"
              className="w-36"
              value={status}
              onChange={(e) => { setStatus(e.target.value); setPage(1) }}
            >
              <option value="pending">Pending</option>
              <option value="approved">Approved</option>
              <option value="rejected">Rejected</option>
              <option value="">All</option>
            </Select>
          }
        >
          <div className="p-1">
            {isLoading ? (
              <PageLoader />
            ) : error ? (
              <ErrorState error={error} onRetry={refetch} />
            ) : (
              <>
                <Table
                  caption="Leave requests"
                  rows={data.items}
                  empty={<EmptyState title="Nothing to review" description="New leave requests will appear here." />}
                  columns={[
                    { key: 'user_name', header: 'Employee', render: (r) => <span className="font-medium text-slate-900">{r.user_name}</span> },
                    { key: 'leave_type', header: 'Type' },
                    { key: 'dates', header: 'Dates', render: (r) => `${fmtDate(r.start_date)} → ${fmtDate(r.end_date)}` },
                    { key: 'days', header: 'Days', render: (r) => (r.half_day ? `0.5 (${r.half_day} half)` : r.days) },
                    { key: 'reason', header: 'Reason', render: (r) => <span className="line-clamp-1 max-w-48">{r.reason || '—'}</span> },
                    { key: 'status', header: 'Status', render: (r) => <><StatusBadge value={r.status} />{r.supersedes_id && <span className="ml-1 text-xs text-slate-500">(revision)</span>}{r.decided_via && <span className="ml-1 text-xs text-slate-500">(delegated)</span>}</> },
                    { key: 'act', header: '', render: (r) => r.status === 'pending' && r.user_id !== user.id && (
                      <div className="flex gap-2">
                        <Button size="sm" onClick={() => open(r, true)}>Approve</Button>
                        <Button size="sm" variant="secondary" onClick={() => open(r, false)}>Reject</Button>
                      </div>
                    ) },
                  ]}
                />
                {data && (
                  <div className="mt-auto px-5 pb-4">
                    <Pagination page={data.page} pageSize={data.page_size} total={data.total} onChange={setPage} />
                  </div>
                )}
              </>
            )}
          </div>
        </Card>
      </div>
      <Modal open={!!target} onClose={close} title={target?.approved ? 'Approve leave' : 'Reject leave'}
        footer={<><Button variant="secondary" onClick={close}>Cancel</Button><Button variant={target?.approved ? 'primary' : 'danger'} loading={decide.isPending} onClick={() => decide.mutate()}>{target?.approved ? 'Approve' : 'Reject'}</Button></>}>
        {decide.error && (
          <div className="mb-3">
            <Alert>{decide.error.message}{decide.error.code === 'insufficient_balance' ? ' You can reject the request with a note, or ask HR to adjust the balance first.' : ''}</Alert>
          </div>
        )}
        {target && <p className="mb-3 text-sm text-slate-600">{target.request.user_name} · {target.request.days} day(s) · {fmtDate(target.request.start_date)} → {fmtDate(target.request.end_date)}</p>}
        <Field label="Note to employee"><Textarea value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      </Modal>
    </>
  )
}
