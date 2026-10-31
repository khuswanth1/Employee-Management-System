import { useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { download, fetchBlobUrl } from '../../lib/api'
import { fmtDateTime } from '../../lib/format'

export function useBlob(path) {
  return useQuery({ queryKey: ['chatfile', path], queryFn: () => fetchBlobUrl(path), staleTime: Infinity, gcTime: 600000, retry: false, enabled: !!path })
}

/** Full-size viewer over all the photos of a conversation: arrow keys / buttons to move, Escape to close, download. */
export default function ImageViewer({ items, index, onIndex, onClose }) {
  const item = items[index]
  const { data: src, isError } = useBlob(item?.file.url)
  const closeBtn = useRef(null)
  useEffect(() => {
    closeBtn.current?.focus()
    const onKey = (e) => {
      if (e.key === 'Escape') onClose()
      else if (e.key === 'ArrowLeft' && index > 0) onIndex(index - 1)
      else if (e.key === 'ArrowRight' && index < items.length - 1) onIndex(index + 1)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [index, items.length, onIndex, onClose])
  if (!item) return null
  return (
    <div role="dialog" aria-modal="true" aria-label={`Photo ${index + 1} of ${items.length}`} className="fixed inset-0 z-[70] flex flex-col bg-black/90" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="flex items-center justify-between gap-2 px-4 py-3 text-sm text-white">
        <div className="min-w-0"><p className="truncate font-medium">{item.file.name}</p><p className="text-xs text-slate-300">{item.sender_name} · {fmtDateTime(item.created_at)} · {index + 1} / {items.length}</p></div>
        <div className="flex shrink-0 gap-2">
          <button type="button" className="rounded-lg bg-white/15 px-3 py-1.5 hover:bg-white/25" onClick={() => download(item.file.url, item.file.name)}>Download</button>
          <button ref={closeBtn} type="button" aria-label="Close viewer" className="rounded-lg bg-white/15 px-3 py-1.5 hover:bg-white/25" onClick={onClose}>✕</button>
        </div>
      </div>
      <div className="relative flex min-h-0 flex-1 items-center justify-center p-4" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
        {index > 0 && <button type="button" aria-label="Previous photo" className="absolute left-3 rounded-full bg-white/15 px-3 py-2 text-xl text-white hover:bg-white/25" onClick={() => onIndex(index - 1)}>‹</button>}
        {isError ? <p className="text-white">This photo could not be loaded.</p> : src ? <img src={src} alt={item.file.name} className="max-h-full max-w-full object-contain" /> : <p className="text-white">Loading…</p>}
        {index < items.length - 1 && <button type="button" aria-label="Next photo" className="absolute right-3 rounded-full bg-white/15 px-3 py-2 text-xl text-white hover:bg-white/25" onClick={() => onIndex(index + 1)}>›</button>}
      </div>
    </div>
  )
}
