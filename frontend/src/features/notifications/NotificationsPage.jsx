import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, EmptyState, ErrorState, PageHeader, PageLoader, Pagination, Select } from '../../components/ui'
import { api } from '../../lib/api'
import { fmtDateTime } from '../../lib/format'
import { useAction, useApi } from '../../lib/hooks'

export default function NotificationsPage() {
  const nav = useNavigate()
  const [page, setPage] = useState(1)
  const [filter, setFilter] = useState('')
  const { data, isLoading, error, refetch } = useApi('/notifications', { page, page_size: 20, unread_only: filter === 'unread' || undefined })
  const readAll = useAction(() => api.post('/notifications/read-all'), { invalidate: ['/notifications'], success: 'All marked as read' })
  const read = useAction((id) => api.post(`/notifications/${id}/read`), { invalidate: ['/notifications'] })
  return (
    <>
      <PageHeader title="Notifications" actions={<Button variant="secondary" onClick={() => readAll.mutate()}>Mark all as read</Button>} />
      <div className="mb-4"><Select aria-label="Filter" className="w-40" value={filter} onChange={(e) => { setFilter(e.target.value); setPage(1) }}><option value="">All</option><option value="unread">Unread only</option></Select></div>
      {isLoading ? <PageLoader /> : error ? <ErrorState error={error} onRetry={refetch} /> : !data.items.length ? <EmptyState title="You're all caught up" /> : (
        <>
          <ul className="divide-y divide-slate-100 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
            {data.items.map((n) => (
              <li key={n.id}>
                <button className={`flex w-full items-start gap-3 px-5 py-4 text-left hover:bg-slate-50 ${n.is_read ? '' : 'bg-brand-50/50'}`}
                  onClick={() => { if (!n.is_read) read.mutate(n.id); if (n.link) nav(n.link) }}>
                  <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${n.is_read ? 'bg-transparent' : 'bg-brand-600'}`} aria-label={n.is_read ? 'Read' : 'Unread'} />
                  <span><span className="block text-sm font-medium text-slate-900">{n.title}</span>{n.body && <span className="block text-sm text-slate-600">{n.body}</span>}<span className="block text-xs text-slate-600">{fmtDateTime(n.created_at)}</span></span>
                </button>
              </li>
            ))}
          </ul>
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onChange={setPage} />
        </>
      )}
    </>
  )
}
