import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, Avatar, Button, EmptyState, Modal, PageLoader, cx } from '../../components/ui'
import { api } from '../../lib/api'
import { fmtDateTime, fmtTime } from '../../lib/format'
import { useAction, useApi, useDebounce } from '../../lib/hooks'
import { useAuth } from '../auth/AuthContext'
import { useRealtime } from '../notifications/NotificationsProvider'
import { DirectLines, NewChat } from './ChatDialogs'
import { Composer, MessageBubble } from './ChatParts'
import ImageViewer from './ImageViewer'
import { fmtDuration } from './emoji'
import Icon, { IconButton } from './icons'

const PAGE = 30
// the conversation background: a soft beige with a faint dot pattern
const WALLPAPER = { backgroundColor: '#efeae2', backgroundImage: 'radial-gradient(rgba(11,20,26,0.05) 1px, transparent 1px)', backgroundSize: '20px 20px' }
const dayLabel = (iso) => {
  const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : `${iso}Z`)
  const today = new Date()
  const y = new Date(); y.setDate(today.getDate() - 1)
  if (d.toDateString() === today.toDateString()) return 'Today'
  if (d.toDateString() === y.toDateString()) return 'Yesterday'
  return d.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' })
}

/** Avatar with a green dot when the person is online. */
function PresenceAvatar({ name, userId, v, online, size }) {
  return (
    <span className="relative inline-flex shrink-0">
      <Avatar name={name} userId={userId} v={v} size={size} />
      {online === true && <span className="absolute bottom-0 right-0 h-3 w-3 rounded-full bg-[#25d366] ring-2 ring-white" role="img" aria-label="Online" />}
      {online === false && <span className="sr-only" role="img" aria-label="Offline" />}
    </span>
  )
}

function useStatus(conv, me) {
  const { presence, typing } = useRealtime()
  const others = conv.members.filter((m) => m.id !== me)
  const online = (id) => presence[id]?.online === true
  const typists = Object.values(typing[conv.id] || {}).filter((t) => t).map((t) => t.name)
  let line
  if (typists.length) line = conv.kind === 'dm' ? 'typing…' : `${typists.join(', ')} ${typists.length > 1 ? 'are' : 'is'} typing…`
  else if (conv.kind === 'dm') {
    const p = others[0] && presence[others[0].id]
    line = online(others[0]?.id) ? 'Online' : p?.last_seen_at ? `Last seen ${fmtDateTime(p.last_seen_at)}` : 'Offline'
  } else line = `${conv.members.length} members · ${others.filter((o) => online(o.id)).length} online`
  return { line, typing: typists.length > 0, online: conv.kind === 'dm' ? online(others[0]?.id) : null }
}

function CallHistory({ open, onClose, onCall }) {
  const { data, isLoading, error } = useApi('/meetings/calls/history', { limit: 30 }, { enabled: open })
  return (
    <Modal open={open} onClose={onClose} title="Call history">
      {isLoading || !data ? (error ? <Alert>{error.message}</Alert> : <PageLoader />) : !data.items.length ? <EmptyState title="No calls yet" description="Voice and video calls you make or receive appear here." /> : (
        <ul className="divide-y divide-black/5" aria-label="Calls">
          {data.items.map((c) => {
            const missed = c.outcome === 'missed' && c.direction === 'incoming'
            return (
              <li key={c.id} className="flex items-center gap-3 py-2.5">
                <span aria-hidden className={cx('flex h-10 w-10 items-center justify-center rounded-full text-white', missed ? 'bg-[#ea0038]' : 'bg-[#00a884]')}><Icon name={c.video ? 'video' : 'phone'} size={20} /></span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[15px] font-medium text-[#111b21]">{c.peer?.name || 'Unknown'}</span>
                  <span className={cx('block text-xs', missed ? 'text-[#b3261e]' : 'text-[#54656f]')}>
                    {c.direction === 'outgoing' ? '↗ Outgoing' : '↙ Incoming'} · {c.outcome === 'answered' ? `Answered${c.duration_s != null ? ` · ${fmtDuration(c.duration_s)}` : ''}` : c.outcome === 'declined' ? 'Declined' : c.outcome === 'ringing' ? 'Ringing' : c.direction === 'incoming' ? 'Missed' : 'No answer'} · {fmtDateTime(c.started_at)}
                  </span>
                </span>
                {c.peer && <IconButton icon={c.video ? 'video' : 'phone'} label={`Call ${c.peer.name} back`} className="text-[#008069]" onClick={() => onCall(c.peer.id, c.video)} />}
              </li>
            )
          })}
        </ul>
      )}
    </Modal>
  )
}

const menuItem = 'block w-full px-4 py-2.5 text-left text-[14.5px] text-[#111b21] hover:bg-[#f5f6f6] disabled:opacity-50'

function Thread({ conv, me, onBack }) {
  const nav = useNavigate()
  const { typing } = useRealtime()
  const path = `/chat/conversations/${conv.id}/messages`
  const status = useStatus(conv, me)
  const box = useRef(null)
  const end = useRef(null)
  const top = useRef(null)
  const keep = useRef(null) // scroll height before older messages were added
  const inner = useRef(null)
  const stick = useRef(true) // the reader is at the bottom: keep following as media loads
  const [replyTo, setReplyTo] = useState(null)
  const [editing, setEditing] = useState(null)
  const [viewer, setViewer] = useState(null)
  const [searching, setSearching] = useState(false)
  const [q, setQ] = useState('')
  const [menu, setMenu] = useState(false)
  const [history, setHistory] = useState(false)
  const [dropping, setDropping] = useState(false)
  const [incoming, setIncoming] = useState(null)
  const [flash, setFlash] = useState(null)
  const dq = useDebounce(q)
  const pages = useInfiniteQuery({
    queryKey: [path, 'pages'],
    queryFn: ({ pageParam }) => api.get(path, { limit: PAGE, ...(pageParam ? { before_id: pageParam } : {}) }),
    initialPageParam: null,
    getNextPageParam: (last) => (last.has_more ? last.items[0]?.id : undefined),
  })
  const messages = useMemo(() => {
    const byId = new Map()
    ;[...(pages.data?.pages || [])].reverse().forEach((p) => p.items.forEach((m) => byId.set(m.id, m)))  // newer pages win, so edits and reactions are never stale
    return [...byId.values()].sort((a, b) => a.id - b.id)
  }, [pages.data])
  const results = useApi(path, { q: dq, limit: PAGE }, { enabled: searching && dq.trim().length > 0 })
  const photos = useMemo(() => messages.filter((m) => m.kind === 'image' && !m.deleted && m.file), [messages])
  const lastId = messages[messages.length - 1]?.id
  const read = useAction(() => api.post(`/chat/conversations/${conv.id}/read`), { invalidate: ['/chat/conversations', '/chat/unread'] })
  const react = useAction(({ id, emoji }) => api.post(`/chat/messages/${id}/reactions`, { emoji }), { invalidate: ['/chat'] })
  const del = useAction((id) => api.del(`/chat/messages/${id}`), { invalidate: ['/chat'] })
  const pin = useAction((pinned) => api.put(`/chat/conversations/${conv.id}/pin`, { pinned }), { invalidate: ['/chat/conversations'], onSuccess: () => setMenu(false) })
  const other = conv.kind === 'dm' ? conv.members.find((m) => m.id !== me) : null
  const call = useAction(({ video }) => (other ? api.post('/meetings/call', { user_id: other.id, video }) : api.post('/meetings', { title: `${conv.title} call`, scheduled_at: null, group_ids: [conv.id] })),
    { invalidate: ['/meetings'], onSuccess: (m, v) => nav(`/meetings/${m.room_id}${v.video ? '' : '?audio=1'}`) })
  const callBack = useAction(({ id, video }) => api.post('/meetings/call', { user_id: id, video }), { invalidate: ['/meetings'], onSuccess: (m, v) => nav(`/meetings/${m.room_id}${v.video ? '' : '?audio=1'}`) })
  const blocked = conv.can_send === false

  // keep the position when older messages are added above; follow new messages only while the reader is at the bottom (or wrote them)
  useLayoutEffect(() => {
    const el = box.current
    if (!el) return
    if (keep.current != null) { el.scrollTop += el.scrollHeight - keep.current; keep.current = null }
  }, [messages.length])
  useEffect(() => {
    const el = box.current
    if (!el) return
    const mine = messages[messages.length - 1]?.sender_id === me
    if (mine || el.scrollHeight - el.scrollTop - el.clientHeight < 200) end.current?.scrollIntoView({ block: 'end' })
  }, [lastId]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const el = inner.current
    if (!el || typeof ResizeObserver === 'undefined') return undefined
    const ro = new ResizeObserver(() => { if (stick.current && keep.current == null && box.current) box.current.scrollTop = box.current.scrollHeight })
    ro.observe(el)
    return () => ro.disconnect()
  }, [pages.isLoading])
  useEffect(() => { if (conv.unread > 0) read.mutate() }, [conv.unread, conv.id]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { stick.current = true; setReplyTo(null); setEditing(null); setSearching(false); setQ(''); setViewer(null) }, [conv.id])

  const loadOlder = useCallback(() => {
    if (!pages.hasNextPage || pages.isFetchingNextPage) return
    keep.current = box.current?.scrollHeight ?? null
    pages.fetchNextPage()
  }, [pages])
  useEffect(() => {
    const el = top.current
    if (!el || typeof IntersectionObserver === 'undefined') return undefined
    const io = new IntersectionObserver((e) => e[0].isIntersecting && loadOlder(), { root: box.current })
    io.observe(el)
    return () => io.disconnect()
  }, [loadOlder, pages.hasNextPage])

  const jump = useCallback(async (id) => {
    for (let tries = 0; tries < 6; tries++) {
      const el = box.current?.querySelector(`[data-mid="${id}"]`)
      if (el) { el.scrollIntoView({ block: 'center', behavior: 'smooth' }); setFlash(id); setTimeout(() => setFlash(null), 1600); return }
      if (!pages.hasNextPage) return
      keep.current = null
      await pages.fetchNextPage()
      await new Promise((r) => setTimeout(r, 50))
    }
  }, [pages])

  const receipt = (m) => {
    if (m.sender_id !== me) return null
    const others = conv.members.filter((x) => x.id !== me)
    if (!others.length) return 'sent'
    if (others.every((o) => o.last_read_id >= m.id)) return 'read'
    if (others.every((o) => o.last_delivered_id >= m.id)) return 'delivered'
    return 'sent'
  }
  const openImage = (id) => setViewer(Math.max(0, photos.findIndex((p) => p.id === id)))
  const onDrop = (e) => { e.preventDefault(); setDropping(false); if (!blocked && e.dataTransfer?.files?.length) setIncoming([...e.dataTransfer.files]) }
  const hasFiles = (e) => [...(e.dataTransfer?.types || [])].includes('Files')
  const typists = Object.values(typing[conv.id] || {}).map((t) => t.name)
  let lastDay = null

  return (
    <div className="relative flex h-full min-h-0 min-w-0 flex-col" onDragOver={(e) => { if (hasFiles(e)) { e.preventDefault(); setDropping(true) } }} onDragLeave={(e) => { if (e.currentTarget === e.target) setDropping(false) }} onDrop={onDrop}>
      <header className="flex min-w-0 items-center justify-between gap-1 bg-[#f0f2f5] px-2 py-2 sm:px-3">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <IconButton icon="back" label="All chats" dense className="md:hidden" onClick={onBack} />
          <PresenceAvatar name={conv.title} userId={other?.id} v={other?.avatar_v} online={status.online} size={10} />
          <div className="min-w-0">
            <p className="truncate text-base font-medium text-[#111b21]">{conv.title}</p>
            <p className={cx('truncate text-[13px]', status.typing ? 'font-medium text-[#008069]' : 'text-[#54656f]')} role="status" aria-live="polite">{status.line}</p>
          </div>
        </div>
        <div className="relative flex shrink-0 items-center">
          <IconButton icon="video" dense label={other ? `Video call ${conv.title}` : 'Start a group video call'} disabled={blocked || call.isPending} onClick={() => call.mutate({ video: true })} />
          <IconButton icon="phone" dense label={other ? `Voice call ${conv.title}` : 'Start a group voice call'} disabled={blocked || call.isPending} onClick={() => call.mutate({ video: false })} />
          <IconButton icon="search" dense label="Search in conversation" pressed={searching} onClick={() => { setSearching((v) => !v); setQ('') }} />
          <IconButton icon="more" dense label="More options" haspopup="menu" expanded={menu} onClick={() => setMenu((v) => !v)} />
          {menu && (
            <div role="menu" aria-label="Conversation options" className="absolute right-0 top-full z-30 mt-1 w-60 overflow-hidden rounded-md bg-white py-2 shadow-xl ring-1 ring-black/5">
              <button type="button" role="menuitem" className={menuItem} onClick={() => pin.mutate(!conv.pinned)}>{conv.pinned ? 'Unpin this chat' : 'Pin this chat'}</button>
              <button type="button" role="menuitem" className={menuItem} onClick={() => { setMenu(false); setSearching(true) }}>Search in conversation</button>
              <button type="button" role="menuitem" disabled={!photos.length} className={menuItem} onClick={() => { setMenu(false); setViewer(photos.length - 1) }}>Photos in this chat ({photos.length})</button>
              <button type="button" role="menuitem" className={menuItem} onClick={() => { setMenu(false); setHistory(true) }}>Call history</button>
            </div>
          )}
        </div>
      </header>
      {call.error && <div className="px-4 pt-2"><Alert>{call.error.message}</Alert></div>}
      {searching && (
        <div className="border-b border-black/5 bg-white px-4 py-2">
          <div className="flex items-center gap-2 rounded-lg bg-[#f0f2f5] px-3">
            <Icon name="search" size={18} className="text-[#54656f]" />
            <input type="search" autoFocus aria-label="Search messages" placeholder="Search in this conversation" value={q} onChange={(e) => setQ(e.target.value)} className="w-full bg-transparent py-2 text-sm text-[#111b21] placeholder:text-[#54656f] focus:outline-none" />
          </div>
          {dq.trim() && (
            <ul className="mt-2 max-h-40 divide-y divide-black/5 overflow-y-auto text-sm" aria-label="Search results">
              {results.isLoading ? <li className="px-3 py-2 text-[#54656f]">Searching…</li> : !results.data?.items.length ? <li className="px-3 py-2 text-[#54656f]">No messages match “{dq}”.</li> : [...results.data.items].reverse().map((r) => (
                <li key={r.id}><button type="button" className="block w-full px-3 py-1.5 text-left hover:bg-[#f5f6f6]" onClick={() => jump(r.id)}><span className="block truncate text-[#111b21]"><b>{r.sender_name}</b>: {r.body || r.preview}</span><span className="text-xs text-[#54656f]">{fmtDateTime(r.created_at)}</span></button></li>
              ))}
            </ul>
          )}
        </div>
      )}
      <div ref={box} style={WALLPAPER} onScroll={(e) => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120 }} className="min-w-0 flex-1 overflow-y-auto overflow-x-hidden px-3 py-4 sm:px-[7%]" role="log" aria-live="polite" aria-label="Messages">
       <div ref={inner} className="space-y-1.5">
        <div ref={top} aria-hidden />
        {pages.isLoading ? <PageLoader /> : pages.error ? <Alert>{pages.error.message} <button type="button" className="font-medium underline" onClick={() => pages.refetch()}>Retry</button></Alert> : !messages.length ? (
          <p className="mx-auto my-10 max-w-xs rounded-lg bg-[#fff5c4] px-3 py-2 text-center text-[12.5px] text-[#54656f] shadow-sm">No messages yet. Say hello! Drag a file here to share it.</p>
        ) : (
          <>
            {pages.hasNextPage && <div className="text-center"><button type="button" onClick={loadOlder} disabled={pages.isFetchingNextPage} className="rounded-full bg-white px-4 py-1.5 text-xs font-medium text-[#008069] shadow-sm hover:bg-[#f5f6f6] disabled:opacity-60">{pages.isFetchingNextPage ? 'Loading…' : 'Load earlier messages'}</button></div>}
            {messages.map((m) => {
              const day = dayLabel(m.created_at)
              const sep = day !== lastDay
              lastDay = day
              return (
                <div key={m.id} className={cx('rounded-lg transition-colors', flash === m.id && 'bg-[#00a884]/20 ring-2 ring-[#00a884]/50', editing?.id === m.id && 'bg-[#f5a623]/15 ring-2 ring-[#f5a623]/60')}>
                  {sep && <p className="my-3 text-center"><span className="rounded-lg bg-white px-3 py-1 text-[12.5px] uppercase tracking-wide text-[#54656f] shadow-sm">{day}</span></p>}
                  <MessageBubble m={m} me={me} mine={m.sender_id === me} showSender={m.sender_id !== me && conv.kind === 'group'} receipt={receipt(m)}
                    onReact={(id, emoji) => react.mutate({ id, emoji })} onReply={(msg) => { setEditing(null); setReplyTo({ id: msg.id, sender_name: msg.sender_name, preview: msg.preview }) }}
                    onEdit={(msg) => { setReplyTo(null); setEditing({ id: msg.id, body: msg.body, kind: msg.kind }) }} onDelete={(id) => del.mutate(id)} onOpenImage={openImage} onJump={jump} />
                </div>
              )
            })}
          </>
        )}
        {typists.length > 0 && <p className="inline-block rounded-lg bg-white px-3 py-1 text-xs italic text-[#54656f] shadow-sm" aria-live="polite">{typists.join(', ')} {typists.length > 1 ? 'are' : 'is'} typing…</p>}
        <div ref={end} />
       </div>
      </div>
      {dropping && !blocked && <div className="pointer-events-none absolute inset-0 z-40 flex items-center justify-center border-2 border-dashed border-[#00a884] bg-[#d9fdd3]/90 text-lg font-medium text-[#008069]" role="status">Drop files to attach them</div>}
      {blocked && <p className="border-t border-black/5 bg-[#fff5c4] px-4 py-2 text-xs text-[#54656f]">You can no longer message this person under the company's communication rules.</p>}
      <Composer convId={conv.id} me={me} disabled={blocked} replyTo={replyTo} onClearReply={() => setReplyTo(null)} editing={editing} onClearEdit={() => setEditing(null)} incoming={incoming} onIncomingHandled={() => setIncoming(null)} />
      {viewer != null && photos[viewer] && <ImageViewer items={photos} index={viewer} onIndex={setViewer} onClose={() => setViewer(null)} />}
      <CallHistory open={history} onClose={() => setHistory(false)} onCall={(id, video) => callBack.mutate({ id, video })} />
    </div>
  )
}

const sectionTitle = 'px-4 pb-1 pt-3 text-[12px] font-medium uppercase tracking-wide text-[#008069]'

export default function ChatPage() {
  const { user } = useAuth()
  const { connected, presence, typing } = useRealtime()
  const { data, isLoading, error } = useApi('/chat/conversations')
  const [activeId, setActiveId] = useState(null)
  const [creating, setCreating] = useState(false)
  const [lines, setLines] = useState(false)
  const [filter, setFilter] = useState('')
  const items = useMemo(() => data?.items || [], [data])
  const active = items.find((c) => c.id === activeId) || null
  useEffect(() => { if (activeId == null && items.length) setActiveId(items[0].id) }, [items, activeId])
  const online = (c) => presence[c.members.find((m) => m.id !== user.id)?.id]?.online === true
  const f = filter.trim().toLowerCase()
  const shown = items.filter((c) => !f || c.title.toLowerCase().includes(f) || (c.last_message?.preview || '').toLowerCase().includes(f))
  const pinned = shown.filter((c) => c.pinned)
  const recent = shown.filter((c) => !c.pinned)
  const onlineNow = items.filter((c) => c.kind === 'dm' && online(c))

  const row = (c) => {
    const other = c.members.find((m) => m.id !== user.id)
    const typists = Object.keys(typing[c.id] || {})
    const last = c.last_message
    const mineLast = last && last.sender_id === user.id
    return (
      <li key={c.id}>
        <button type="button" onClick={() => setActiveId(c.id)} aria-current={c.id === activeId}
          className={cx('flex w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-[#f5f6f6] focus-visible:bg-[#f5f6f6]', c.id === activeId && 'bg-[#f0f2f5]')}>
          <PresenceAvatar name={c.title} userId={c.kind === 'dm' ? other?.id : undefined} v={other?.avatar_v} online={c.kind === 'dm' ? online(c) : null} size={12} />
          <span className="min-w-0 flex-1 border-b border-black/5 pb-2.5 pt-0.5">
            <span className="flex items-center justify-between gap-2">
              <span className="truncate text-[16px] text-[#111b21]">{c.title}</span>
              {last && <span className={cx('shrink-0 text-xs', c.unread > 0 ? 'font-medium text-[#008069]' : 'text-[#54656f]')}>{fmtTime(last.created_at)}</span>}
            </span>
            <span className="flex items-center justify-between gap-2">
              <span className={cx('flex min-w-0 items-center gap-1 text-[14px]', typists.length ? 'font-medium text-[#008069]' : 'text-[#54656f]')}>
                {!typists.length && mineLast && <Icon name="checks" size={16} className="text-[#54656f]" />}
                <span className="truncate">{typists.length ? 'typing…' : last ? `${mineLast ? 'You: ' : ''}${last.preview ?? last.body}` : 'No messages yet'}</span>
              </span>
              <span className="flex shrink-0 items-center gap-1.5">
                {c.pinned && <Icon name="pin" size={15} className="rotate-45 text-[#54656f]" title="Pinned" />}
                {c.unread > 0 && <span className="inline-flex min-w-[20px] items-center justify-center rounded-full bg-[#008069] px-1.5 py-0.5 text-xs font-medium text-white" aria-label={`${c.unread} unread`}>{c.unread}</span>}
              </span>
            </span>
          </span>
        </button>
      </li>
    )
  }

  return (
    <>
      <h1 className="sr-only">Chat</h1>
      {!connected && <div className="mb-3"><Alert tone="amber">Reconnecting to live updates…</Alert></div>}
      {error ? <Alert>{error.message}</Alert> : isLoading ? <PageLoader /> : !items.length ? (
        <EmptyState title="No conversations yet" description="Start a chat with a colleague." action={<Button onClick={() => setCreating(true)}>New chat</Button>} />
      ) : (
        <div className="grid h-[calc(100vh-8.5rem)] min-h-[28rem] grid-cols-1 overflow-hidden rounded-xl bg-white shadow-lg ring-1 ring-black/10 md:grid-cols-[22rem_minmax(0,1fr)] lg:grid-cols-[26rem_minmax(0,1fr)]">
          <div className={cx('flex min-h-0 min-w-0 flex-col border-black/10 md:border-r', active && 'hidden md:flex')}>
            <header className="flex items-center justify-between bg-[#f0f2f5] px-3 py-2.5">
              <div className="flex min-w-0 items-center gap-3">
                <PresenceAvatar name={user.full_name} userId={user.id} v={user.avatar_v} online={connected ? true : null} size={10} />
                <div className="min-w-0"><p className="truncate text-sm font-medium text-[#111b21]">{user.full_name}</p><p className="text-xs text-[#54656f]">{connected ? 'You are online' : 'Connecting…'}</p></div>
              </div>
              <div className="flex shrink-0">
                {user.role === 'founder' && <IconButton icon="lock" label="Direct lines" onClick={() => setLines(true)} />}
                <IconButton icon="newChat" label="New chat" onClick={() => setCreating(true)} />
              </div>
            </header>
            <div className="bg-white px-3 py-2">
              <div className="flex items-center gap-3 rounded-lg bg-[#f0f2f5] px-3">
                <Icon name="search" size={18} className="text-[#54656f]" />
                <input type="search" aria-label="Search conversations" placeholder="Search or start a new chat" value={filter} onChange={(e) => setFilter(e.target.value)} className="w-full bg-transparent py-2 text-sm text-[#111b21] placeholder:text-[#54656f] focus:outline-none" />
              </div>
            </div>
            {!f && onlineNow.length > 0 && (
              <section aria-label="Online now" className="px-3 pb-2">
                <h2 className="mb-1 text-[12px] font-medium uppercase tracking-wide text-[#008069]">Online now</h2>
                <ul className="flex gap-2 overflow-x-auto">
                  {onlineNow.map((c) => { const o = c.members.find((m) => m.id !== user.id); return <li key={c.id}><button type="button" aria-label={`Chat with ${c.title}, online`} title={c.title} onClick={() => setActiveId(c.id)}><PresenceAvatar name={c.title} userId={o?.id} v={o?.avatar_v} online size={10} /></button></li> })}
                </ul>
              </section>
            )}
            <div className="min-h-0 flex-1 overflow-y-auto">
              {pinned.length > 0 && <section aria-label="Pinned conversations"><h2 className={sectionTitle}>Pinned</h2><ul>{pinned.map(row)}</ul></section>}
              <section aria-label="Recent conversations">{pinned.length > 0 && <h2 className={sectionTitle}>Recent</h2>}<ul aria-label="Conversations">{recent.map(row)}</ul></section>
              {shown.length === 0 && <p className="px-3 py-6 text-center text-sm text-[#54656f]">No chats match “{filter}”.</p>}
            </div>
          </div>
          <section className={cx('min-h-0 min-w-0', !active && 'hidden md:block')} aria-label="Conversation">
            {active ? <Thread key={active.id} conv={active} me={user.id} onBack={() => setActiveId(null)} /> : (
              <div className="flex h-full flex-col items-center justify-center gap-2 bg-[#f0f2f5] text-center">
                <span className="flex h-20 w-20 items-center justify-center rounded-full bg-white text-[#8696a0]"><Icon name="chat" size={40} /></span>
                <p className="text-xl text-[#41525d]">Select a conversation</p>
                <p className="max-w-xs text-sm text-[#667781]">Send and receive messages, files and voice notes, and start calls, with anyone you work with.</p>
              </div>
            )}
          </section>
        </div>
      )}
      <DirectLines open={lines} onClose={() => setLines(false)} />
      <NewChat open={creating} onClose={() => setCreating(false)} onCreated={setActiveId} />
    </>
  )
}
