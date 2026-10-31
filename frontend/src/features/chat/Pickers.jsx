import { useEffect, useMemo, useRef, useState } from 'react'
import { cx } from '../../components/ui'
import { useApi } from '../../lib/hooks'
import { EMOJI_GROUPS, favouriteStickers, frequentEmoji, recentEmoji, recentStickers, searchEmoji, toggleFavouriteSticker } from './emoji'

/** Moves focus between the buttons of a grid with the arrow keys (the grid is one tab stop group; Escape closes it). */
function useGridKeys(onClose) {
  const grid = useRef(null)
  const onKeyDown = (e) => {
    if (e.key === 'Escape') { e.stopPropagation(); onClose(); return }
    if (!['ArrowRight', 'ArrowLeft', 'ArrowDown', 'ArrowUp'].includes(e.key)) return
    const items = [...(grid.current?.querySelectorAll('button[data-cell]') || [])]
    const i = items.indexOf(document.activeElement)
    if (i < 0) return
    const cols = Math.max(1, Math.round(grid.current.clientWidth / (items[0]?.offsetWidth || 1)))
    const next = { ArrowRight: i + 1, ArrowLeft: i - 1, ArrowDown: i + cols, ArrowUp: i - cols }[e.key]
    if (items[next]) { e.preventDefault(); items[next].focus() }
  }
  return { grid, onKeyDown }
}

const Cell = ({ e, onPick, label }) => (
  <button type="button" data-cell aria-label={label || e} className="rounded p-1 text-xl hover:bg-slate-100 focus-visible:bg-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#008069]" onClick={() => onPick(e)}>{e}</button>
)

export function EmojiPicker({ userId, onPick, onClose }) {
  const [tab, setTab] = useState(EMOJI_GROUPS[0].id)
  const [q, setQ] = useState('')
  const search = useRef(null)
  const { grid, onKeyDown } = useGridKeys(onClose)
  useEffect(() => { search.current?.focus() }, [])
  const found = useMemo(() => searchEmoji(q), [q])
  const group = EMOJI_GROUPS.find((g) => g.id === tab)
  const frequent = useMemo(() => frequentEmoji(userId), [userId])
  const recent = useMemo(() => recentEmoji(userId), [userId])
  const grid_ = (title, list) => list.length > 0 && (
    <section aria-label={title}><h3 className="mb-0.5 mt-1 text-[11px] font-medium uppercase tracking-wide text-[#008069]">{title}</h3><div className="grid grid-cols-8 gap-0.5">{list.map((e) => <Cell key={title + e} e={e} onPick={onPick} />)}</div></section>
  )
  return (
    <div role="group" aria-label="Emoji" onKeyDown={onKeyDown} className="absolute bottom-full left-0 z-30 mb-2 w-[min(20rem,calc(100vw-2rem))] rounded-xl bg-white p-2 shadow-xl ring-1 ring-black/5">
      <input ref={search} type="search" aria-label="Search emoji" placeholder="Search emoji" value={q} onChange={(e) => setQ(e.target.value)} className="mb-1.5 w-full rounded-lg border-0 bg-[#f0f2f5] px-3 py-1.5 text-sm text-[#111b21] placeholder:text-[#54656f] focus:outline focus:outline-2 focus:outline-[#00a884]" />
      {!q && (
        <div className="mb-1 flex gap-1 border-b border-slate-100 pb-1" role="tablist" aria-label="Emoji categories">
          {EMOJI_GROUPS.map((g) => <button key={g.id} type="button" role="tab" aria-selected={g.id === tab} aria-label={g.label} onClick={() => setTab(g.id)} className={cx('rounded px-2 py-1 text-base', g.id === tab ? 'bg-[#d9fdd3]' : 'hover:bg-black/5')}>{g.icon}</button>)}
        </div>
      )}
      <div ref={grid} className="max-h-52 overflow-y-auto">
        {q ? (found.length ? <div className="grid grid-cols-8 gap-0.5" aria-label="Search results">{found.map((e) => <Cell key={e} e={e} onPick={onPick} />)}</div> : <p className="p-3 text-center text-sm text-slate-600">No emoji match “{q}”.</p>) : (
          <>
            {grid_('Frequently used', frequent)}
            {grid_('Recently used', recent)}
            <section aria-label={group.label}><h3 className="mb-0.5 mt-1 text-[11px] font-medium uppercase tracking-wide text-[#008069]">{group.label}</h3><div className="grid grid-cols-8 gap-0.5">{group.items.map((i) => <Cell key={i.e} e={i.e} onPick={onPick} label={`${i.e} ${i.w.split(' ')[0]}`} />)}</div></section>
          </>
        )}
      </div>
    </div>
  )
}

export function StickerPicker({ userId, onPick, onClose }) {
  const { data, isLoading, error } = useApi('/chat/stickers')
  const [tab, setTab] = useState('all')
  const [q, setQ] = useState('')
  const [favs, setFavs] = useState(() => favouriteStickers(userId))
  const search = useRef(null)
  const { grid, onKeyDown } = useGridKeys(onClose)
  useEffect(() => { search.current?.focus() }, [])
  const items = data?.items || []
  const byId = Object.fromEntries(items.map((s) => [s.id, s]))
  const cats = [...new Set(items.map((s) => s.category))]
  const recents = recentStickers(userId).map((id) => byId[id]).filter(Boolean)
  const shown = q.trim() ? items.filter((s) => `${s.label} ${s.category}`.toLowerCase().includes(q.trim().toLowerCase()))
    : tab === 'recent' ? recents : tab === 'fav' ? favs.map((id) => byId[id]).filter(Boolean) : tab === 'all' ? items : items.filter((s) => s.category === tab)
  const tabs = [['all', 'All'], ['recent', 'Recent'], ['fav', 'Favourites'], ...cats.map((c) => [c, c])]
  return (
    <div role="group" aria-label="Stickers" onKeyDown={onKeyDown} className="absolute bottom-full left-0 z-30 mb-2 w-[min(20rem,calc(100vw-2rem))] rounded-xl bg-white p-2 shadow-xl ring-1 ring-black/5">
      <input ref={search} type="search" aria-label="Search stickers" placeholder="Search stickers" value={q} onChange={(e) => setQ(e.target.value)} className="mb-1.5 w-full rounded-lg border-0 bg-[#f0f2f5] px-3 py-1.5 text-sm text-[#111b21] placeholder:text-[#54656f] focus:outline focus:outline-2 focus:outline-[#00a884]" />
      {!q && (
        <div className="mb-1 flex gap-1 overflow-x-auto border-b border-slate-100 pb-1" role="tablist" aria-label="Sticker categories">
          {tabs.map(([id, label]) => <button key={id} type="button" role="tab" aria-selected={id === tab} onClick={() => setTab(id)} className={cx('shrink-0 rounded-full px-2.5 py-1 text-xs', id === tab ? 'bg-[#008069] text-white' : 'bg-[#f0f2f5] text-[#111b21] hover:bg-[#e4e6e9]')}>{label}</button>)}
        </div>
      )}
      <div ref={grid} className="max-h-56 overflow-y-auto">
        {isLoading ? <p className="p-3 text-center text-sm text-slate-600">Loading…</p> : error ? <p className="p-3 text-center text-sm text-red-700">Stickers could not be loaded.</p> : shown.length === 0 ? (
          <p className="p-3 text-center text-sm text-slate-600">{q ? `No sticker matches “${q}”.` : tab === 'fav' ? 'Tap ☆ on a sticker to keep it here.' : tab === 'recent' ? 'Stickers you send appear here.' : 'Nothing here.'}</p>
        ) : (
          <div className="grid grid-cols-4 gap-1">
            {shown.map((s) => (
              <div key={s.id} className="group relative">
                <button type="button" data-cell aria-label={`Send sticker: ${s.label}`} title={s.label} className="w-full rounded-lg p-1 text-4xl hover:bg-slate-100 focus-visible:bg-slate-100" onClick={() => onPick(s.id)}>{s.emoji}</button>
                <button type="button" aria-label={`${favs.includes(s.id) ? 'Remove' : 'Add'} ${s.label} ${favs.includes(s.id) ? 'from' : 'to'} favourites`} aria-pressed={favs.includes(s.id)}
                  className="absolute right-0 top-0 rounded-full bg-white/90 px-1 text-xs text-amber-600 opacity-0 focus-visible:opacity-100 group-hover:opacity-100" onClick={() => setFavs(toggleFavouriteSticker(userId, s.id))}>{favs.includes(s.id) ? '★' : '☆'}</button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
