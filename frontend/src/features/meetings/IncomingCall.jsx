import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { Avatar } from '../../components/ui'
import Icon from '../chat/icons'
import { api } from '../../lib/api'
import { useAction } from '../../lib/hooks'
import { useRealtime } from '../notifications/NotificationsProvider'

const RING_LIMIT_MS = 60000

/** A soft two-tone ring made with the Web Audio API (no audio file). Browsers may block sound until the page was interacted with; that is fine. */
function useRingtone(active) {
  const ctx = useRef(null)
  useEffect(() => {
    if (!active) return undefined
    let timer
    const beep = () => {
      try {
        ctx.current ??= new (window.AudioContext || window.webkitAudioContext)()
        const c = ctx.current
        if (c.state === 'suspended') c.resume().catch(() => {})
        ;[[0, 880], [0.25, 660]].forEach(([at, hz]) => {
          const o = c.createOscillator(), g = c.createGain()
          o.frequency.value = hz; g.gain.value = 0.06
          o.connect(g); g.connect(c.destination)
          o.start(c.currentTime + at); o.stop(c.currentTime + at + 0.2)
        })
      } catch { /* no audio available */ }
    }
    beep(); timer = setInterval(beep, 2200)
    return () => { clearInterval(timer); ctx.current?.close?.().catch(() => {}); ctx.current = null }
  }, [active])
}

export default function IncomingCall() {
  const { incomingCall: call, dismissCall } = useRealtime()
  const nav = useNavigate()
  const accept = useRef(null)
  const decline = useAction((room) => api.post(`/meetings/${room}/decline`), { onSuccess: dismissCall })
  useRingtone(!!call)
  useEffect(() => {
    if (!call) return undefined
    accept.current?.focus()
    const t = setTimeout(dismissCall, RING_LIMIT_MS)           // stop ringing; the server records it as missed
    const onKey = (e) => { if (e.key === 'Escape') decline.mutate(call.room_id) }
    window.addEventListener('keydown', onKey)
    return () => { clearTimeout(t); window.removeEventListener('keydown', onKey) }
  }, [call, dismissCall]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!call) return null
  const go = () => { dismissCall(); nav(`/meetings/${call.room_id}${call.video ? '' : '?audio=1'}`) }
  return (
    <div role="alertdialog" aria-modal="false" aria-labelledby="incoming-call-title" aria-describedby="incoming-call-kind"
      className="fixed inset-x-3 bottom-4 z-[60] mx-auto max-w-sm rounded-2xl bg-[#111b21] p-5 text-white shadow-2xl ring-1 ring-white/10 sm:inset-x-auto sm:right-6">
      <div className="flex items-center gap-4">
        <span className="relative inline-flex"><Avatar name={call.from_name} size={14} userId={call.from_id} /><span className="absolute inset-0 animate-ping rounded-full ring-2 ring-[#25d366]/70" aria-hidden /></span>
        <div className="min-w-0">
          <p id="incoming-call-title" className="truncate text-lg font-medium">{call.from_name}</p>
          <p id="incoming-call-kind" className="flex items-center gap-1.5 text-sm text-[#aebac1]" role="status"><Icon name={call.video ? 'video' : 'phone'} size={16} />Incoming {call.video ? 'video' : 'voice'} call…</p>
        </div>
      </div>
      <div className="mt-5 flex justify-around">
        <button type="button" aria-label="Decline" onClick={() => decline.mutate(call.room_id)} disabled={decline.isPending} className="flex flex-col items-center gap-1.5 text-sm focus-visible:outline-none">
          <span className="flex h-14 w-14 items-center justify-center rounded-full bg-[#ea0038] shadow-lg transition-transform hover:scale-105 group-focus-visible:ring-2"><Icon name="phone" size={26} className="rotate-[135deg]" /></span>Decline
        </button>
        <button ref={accept} type="button" aria-label="Accept" onClick={go} className="flex flex-col items-center gap-1.5 text-sm focus-visible:outline-none">
          <span className="flex h-14 w-14 items-center justify-center rounded-full bg-[#00a884] shadow-lg transition-transform hover:scale-105"><Icon name={call.video ? 'video' : 'phone'} size={26} /></span>Accept
        </button>
      </div>
    </div>
  )
}
