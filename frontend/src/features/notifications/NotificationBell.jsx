import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useApi, useAction } from '../../lib/hooks'
import { api } from '../../lib/api'
import { fmtDateTime } from '../../lib/format'
import { useRealtime } from './NotificationsProvider'

export default function NotificationBell() {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const { connected } = useRealtime()
  const { data: count } = useApi('/notifications/unread-count', null, { refetchInterval: connected ? false : 30000 })
  const { data: list } = useApi('/notifications', { page_size: 8 }, { enabled: open })
  const readAll = useAction(() => api.post('/notifications/read-all'), { invalidate: ['/notifications'] })
  const markRead = useAction((id) => api.post(`/notifications/${id}/read`), { invalidate: ['/notifications'] })
  const n = count?.count || 0

  useEffect(() => {
    if (!open) return undefined
    const close = (e) => { if (!ref.current?.contains(e.target)) setOpen(false) }
    const esc = (e) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', close); document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', esc) }
  }, [open])

  return (
    <div className="relative" ref={ref}>
      <button onClick={() => setOpen(!open)} aria-haspopup="true" aria-expanded={open}
        aria-label={`Notifications${n ? `, ${n} unread` : ''}`} className="relative rounded-full p-2 text-slate-500 hover:bg-slate-100">
        <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M6 9a6 6 0 0112 0c0 5 2 6 2 6H4s2-1 2-6zM10 19a2 2 0 004 0" strokeLinecap="round" strokeLinejoin="round" /></svg>
        {n > 0 && <span className="absolute right-0.5 top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-bold text-white">{n > 99 ? '99+' : n}</span>}
        <span className={`absolute bottom-1 right-1 h-1.5 w-1.5 rounded-full ${connected ? 'bg-emerald-500' : 'bg-slate-300'}`} title={connected ? 'Live updates on' : 'Reconnecting…'} />
      </button>
      {open && (
        <div className="absolute right-0 z-40 mt-2 w-80 max-w-[calc(100vw-1.5rem)] rounded-xl border border-slate-200 bg-white shadow-xl">
          <div className="flex items-center justify-between border-b border-slate-100 px-4 py-2.5">
            <span className="text-sm font-semibold">Notifications</span>
            <button className="text-xs font-medium text-brand-700 hover:underline disabled:opacity-40" disabled={!n} onClick={() => readAll.mutate()}>Mark all read</button>
          </div>
          <ul className="custom-scrollbar max-h-96 divide-y divide-slate-100 overflow-y-auto">
            {list?.items?.length ? list.items.map((x) => (
              <li key={x.id}>
                <Link to={x.link || '/notifications'} onClick={() => { if (!x.is_read) markRead.mutate(x.id); setOpen(false) }}
                  className={`block px-4 py-3 text-sm hover:bg-slate-50 ${x.is_read ? '' : 'bg-brand-50/60'}`}>
                  <p className="font-medium text-slate-900">{x.title}</p>
                  {x.body && <p className="line-clamp-2 text-slate-600">{x.body}</p>}
                  <p className="mt-0.5 text-xs text-slate-500">{fmtDateTime(x.created_at)}</p>
                </Link>
              </li>
            )) : <li className="px-4 py-8 text-center text-sm text-slate-500">You're all caught up</li>}
          </ul>
          <Link to="/notifications" onClick={() => setOpen(false)} className="block border-t border-slate-100 px-4 py-2.5 text-center text-sm font-medium text-brand-700 hover:bg-slate-50">View all</Link>
        </div>
      )}
    </div>
  )
}
