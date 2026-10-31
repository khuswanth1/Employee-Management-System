import { useState } from 'react'
import { Badge, Button, EmptyState, ErrorState, Field, Input, Modal, PageHeader, PageLoader, Pagination, Select, StatusBadge, Table, Textarea } from '../../components/ui'
import { api } from '../../lib/api'
import { fmtDate } from '../../lib/format'
import { useAction, useApi } from '../../lib/hooks'
import { useAuth } from '../auth/AuthContext'

function ReviewModal({ update, canReview, onClose }) {
  const [comment, setComment] = useState('')
  const review = useAction((status) => api.post(`/daily-updates/${update.id}/review`, { status, comment: comment || null }), {
    invalidate: ['/daily-updates', '/dashboard'], success: 'Review saved', onSuccess: onClose,
  })
  const Row = ({ title, text }) => text ? <div><h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h3><p className="mt-1 whitespace-pre-wrap text-sm">{text}</p></div> : null
  return (
    <Modal open onClose={onClose} title={`${update.user_name} — ${fmtDate(update.work_date)}`} wide
      footer={canReview ? <><Button variant="secondary" onClick={onClose}>Close</Button>
        <Button variant="secondary" loading={review.isPending} onClick={() => review.mutate('needs_changes')}>Request changes</Button>
        <Button loading={review.isPending} onClick={() => review.mutate('reviewed')}>Mark reviewed</Button></> : <Button variant="secondary" onClick={onClose}>Close</Button>}>
      <div className="space-y-4">
        <p className="text-sm text-slate-500">{update.hours_worked} hours worked · <StatusBadge value={update.review_status} /></p>
        <Row title="Completed" text={update.completed} /><Row title="Pending" text={update.pending} />
        <Row title="Blockers" text={update.blockers} /><Row title="Next-day plan" text={update.next_plan} />
        {update.review_comment && <Row title="Previous review comment" text={update.review_comment} />}
        {canReview && <Field label="Review comment"><Textarea value={comment} onChange={(e) => setComment(e.target.value)} /></Field>}
      </div>
    </Modal>
  )
}

export default function TeamUpdatesPage() {
  const { role } = useAuth()
  const [f, setF] = useState({ work_date: '', review_status: '' })
  const [page, setPage] = useState(1)
  const [open, setOpen] = useState(null)
  const { data, isLoading, error, refetch } = useApi('/daily-updates/team', { ...f, page, page_size: 15 })
  return (
    <>
      <PageHeader title="Team updates" description={role === 'manager' ? 'Daily reports from your direct reports' : 'Daily reports across the company'} />
      <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-12">
        <div className="sm:col-span-3">
          <Input
            type="date"
            aria-label="Date"
            value={f.work_date}
            onChange={(e) => { setF({ ...f, work_date: e.target.value }); setPage(1) }}
          />
        </div>
        <div className="sm:col-span-3">
          <Select
            aria-label="Review status"
            value={f.review_status}
            onChange={(e) => { setF({ ...f, review_status: e.target.value }); setPage(1) }}>
            <option value="">All statuses</option>
            <option value="pending">Pending</option>
            <option value="reviewed">Reviewed</option>
            <option value="needs_changes">Needs changes</option>
          </Select>
        </div>
        {(f.work_date || f.review_status) && (
          <div className="flex items-center sm:col-span-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => { setF({ work_date: '', review_status: '' }); setPage(1) }}>
              Clear filters
            </Button>
          </div>
        )}
      </div>
      {isLoading ? <PageLoader /> : error ? <ErrorState error={error} onRetry={refetch} /> : (
        <>
          <Table caption="Team daily updates" rows={data.items} onRowClick={setOpen} empty={<EmptyState title="No updates" description="Updates your team submits will be listed here." />}
            columns={[
              { key: 'user_name', header: 'Employee', render: (u) => <span className="font-medium text-slate-900">{u.user_name}</span> },
              { key: 'work_date', header: 'Date', render: (u) => fmtDate(u.work_date) },
              { key: 'hours_worked', header: 'Hours' },
              { key: 'summary', header: 'Summary', render: (u) => <span className="line-clamp-1 max-w-xs">{u.completed}</span> },
              { key: 'blockers', header: 'Blockers', render: (u) => u.has_blockers ? <Badge tone="red">Has blockers</Badge> : '—' },
              { key: 'review_status', header: 'Review', render: (u) => <StatusBadge value={u.review_status} /> },
            ]} />
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onChange={setPage} />
        </>
      )}
      {open && <ReviewModal update={open} canReview={role === 'manager'} onClose={() => setOpen(null)} />}
    </>
  )
}
