import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { Alert, Avatar, Badge, Button, Modal } from '../../components/ui'
import { api } from '../../lib/api'
import { useAction, useApi } from '../../lib/hooks'
import { useAuth } from '../auth/AuthContext'
import { useRealtime } from '../notifications/NotificationsProvider'
import RecipientPicker, { emptyPick, pickBody, pickCount } from './RecipientPicker'
import { useMeeting } from './useMeeting'

const NO_ANSWER_MS = 45000
const clock = (s) => { const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, x = s % 60; return `${h ? `${h}:${String(m).padStart(2, '0')}` : m}:${String(x).padStart(2, '0')}` }

const STATUS = {
  connecting: 'Connecting…', waiting: 'Waiting for others to join', negotiating: 'Connecting…', connected: 'Connected',
  reconnecting: 'Reconnecting… the connection is unstable', failed: 'Connection failed. Check your network and try again.',
}
const QUALITY = { good: ['Good connection', 'green'], fair: ['Fair connection', 'amber'], poor: ['Poor connection', 'red'] }

function Tile({ stream, name, muted, badge, avatarId, sinkId, large }) {
  const v = useRef(null)
  const hasVideo = !!stream && stream.getVideoTracks().some((t) => t.readyState === 'live')
  useEffect(() => { if (v.current) v.current.srcObject = stream || null }, [stream])
  useEffect(() => { if (v.current && sinkId && v.current.setSinkId) v.current.setSinkId(sinkId).catch(() => {}) }, [sinkId, stream])
  return (
    <figure className={`relative overflow-hidden rounded-xl bg-slate-900 ${large ? 'aspect-video' : 'aspect-video'}`}>
      <video ref={v} autoPlay playsInline muted={muted} className={`h-full w-full object-cover ${hasVideo ? '' : 'invisible'}`} />
      {!hasVideo && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-slate-200">
          <Avatar name={name} size={large ? 20 : 12} userId={avatarId} />
          {!stream && <span className="text-sm text-slate-300">Connecting…</span>}
        </div>
      )}
      <figcaption className="absolute bottom-2 left-2 flex items-center gap-2 rounded bg-black/70 px-2 py-0.5 text-xs text-white">{name}{badge}</figcaption>
    </figure>
  )
}

function DeviceMenu({ m }) {
  const { mics, cams, speakers } = m.devices
  const sel = 'w-full rounded border border-slate-300 bg-white px-2 py-1 text-sm'
  const current = (kind) => m.local?.[kind === 'audio' ? 'getAudioTracks' : 'getVideoTracks']()[0]?.getSettings?.().deviceId || ''
  return (
    <details className="relative">
      <summary className="inline-flex cursor-pointer list-none items-center rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">Devices</summary>
      <div className="absolute bottom-full right-0 z-20 mb-2 w-72 space-y-3 rounded-xl border border-slate-200 bg-white p-3 shadow-lg">
        <label className="block text-xs font-medium text-slate-700">Microphone
          <select aria-label="Microphone" className={sel} value={current('audio')} onChange={(e) => m.selectMic(e.target.value)}>{mics.length ? mics.map((d) => <option key={d.id} value={d.id}>{d.label}</option>) : <option value="">None found</option>}</select>
        </label>
        {m.hasCamera && (
          <label className="block text-xs font-medium text-slate-700">Camera
            <select aria-label="Camera" className={sel} value={current('video')} onChange={(e) => m.selectCamera(e.target.value)}>{cams.map((d) => <option key={d.id} value={d.id}>{d.label}</option>)}</select>
          </label>
        )}
        <label className="block text-xs font-medium text-slate-700">Speaker
          <select aria-label="Speaker" className={sel} value={m.speakerId} disabled={!speakers.length} onChange={(e) => m.setSpeakerId(e.target.value)}>
            {speakers.length ? speakers.map((d) => <option key={d.id} value={d.id}>{d.label}</option>) : <option value="">Default (this browser cannot choose)</option>}
          </select>
        </label>
      </div>
    </details>
  )
}

export default function MeetingRoomPage() {
  const { room } = useParams()
  const nav = useNavigate()
  const { user } = useAuth()
  const { lastCallEnd } = useRealtime()
  const { data: meeting, isLoading: loadingMeeting } = useApi(`/meetings/${room}`)
  const [inviting, setInviting] = useState(false)
  const [pick, setPick] = useState(emptyPick())
  const [query] = useSearchParams()
  // a voice call never opens the camera, whichever link brought you here (the chat, the ring, or a notification)
  const audioOnly = query.get('audio') === '1' || (meeting?.kind === 'call' && meeting.call_video === false)
  const m = useMeeting(room, { audioOnly, enabled: !loadingMeeting })
  const stage = useRef(null)
  const [now, setNow] = useState(Date.now())
  const [over, setOver] = useState(null) // { title, text } once a call has ended
  const [full, setFull] = useState(false)
  const hadPeer = useRef(false)
  const leaveTo = meeting?.kind === 'call' ? '/chat' : '/meetings'
  const end = useAction(() => api.post(`/meetings/${room}/end`), { invalidate: ['/meetings'], success: meeting?.kind === 'call' ? undefined : 'Meeting ended', onSuccess: () => nav(leaveTo) })
  const hangUp = useAction(() => api.post(`/meetings/${room}/end`), { invalidate: ['/meetings'] })
  const add = useAction((body) => api.post(`/meetings/${room}/participants`, body), {
    invalidate: [`/meetings/${room}`, '/meetings'], success: 'Invitations sent',
    onSuccess: () => { setInviting(false); setPick(emptyPick()) },
  })
  const remove = useAction((uid) => api.del(`/meetings/${room}/participants/${uid}`), { invalidate: [`/meetings/${room}`, '/meetings'], success: 'Removed' })
  const peers = Object.entries(m.remotes)
  const amHost = meeting?.host_id === user.id
  const canEnd = amHost || ['founder', 'hr'].includes(user.role)
  const isCall = meeting?.kind === 'call'
  const invited = meeting?.participants || []
  const other = invited.find((p) => p.id !== user.id)
  const secs = m.connectedAt ? Math.max(0, Math.floor((now - m.connectedAt) / 1000)) : 0

  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t) }, [])
  useEffect(() => { const f = () => setFull(!!document.fullscreenElement); document.addEventListener('fullscreenchange', f); return () => document.removeEventListener('fullscreenchange', f) }, [])
  if (peers.length) hadPeer.current = true

  // the call is over for the person who is left once the other side has gone for a few seconds
  useEffect(() => {
    if (!isCall || !hadPeer.current || peers.length || over) return undefined
    const t = setTimeout(() => setOver({ title: 'Call ended', text: `${other?.name || 'The other person'} left the call.${m.connectedAt ? ` Duration ${clock(secs)}.` : ''}` }), 2500)
    return () => clearTimeout(t)
  }, [isCall, peers.length, over]) // eslint-disable-line react-hooks/exhaustive-deps

  // the caller gives up after 45 s without an answer; the server records it as a missed call
  const ringing = isCall && amHost && !m.connectedAt && ['waiting', 'negotiating'].includes(m.callState) && !over
  useEffect(() => {
    if (!ringing) return undefined
    const t = setTimeout(() => { hangUp.mutate(undefined, { onSettled: () => setOver({ title: 'No answer', text: `${other?.name || 'They'} did not pick up. You can try again from the chat.` }) }) }, NO_ANSWER_MS)
    return () => clearTimeout(t)
  }, [ringing]) // eslint-disable-line react-hooks/exhaustive-deps

  // what the server tells us about this call: declined, or cancelled before we answered
  useEffect(() => {
    if (!lastCallEnd || lastCallEnd.room_id !== room || over) return
    if (lastCallEnd.outcome === 'declined') setOver({ title: 'Call declined', text: `${other?.name || 'They'} declined the call.` })
    else if (lastCallEnd.outcome === 'missed' && !amHost) setOver({ title: 'Call ended', text: 'The caller hung up before you joined.' })
  }, [lastCallEnd]) // eslint-disable-line react-hooks/exhaustive-deps

  if (m.status === 'error' || m.status === 'ended') {
    return <div className="mx-auto max-w-md py-16 text-center"><Alert>{m.error}</Alert><Button className="mt-4" onClick={() => nav(leaveTo)}>{isCall ? 'Back to chat' : 'Back to meetings'}</Button></div>
  }
  if (over) {
    return (
      <div className="mx-auto max-w-md py-16 text-center" role="status">
        <h1 className="text-xl font-semibold text-slate-900">{over.title}</h1>
        <p className="mt-2 text-sm text-slate-600">{over.text}</p>
        <Button className="mt-5" onClick={() => nav(leaveTo)}>{isCall ? 'Back to chat' : 'Back to meetings'}</Button>
      </div>
    )
  }

  const statusText = ringing && m.callState !== 'connecting' ? `Calling ${other?.name || ''}…` : STATUS[m.callState] || ''
  const q = m.quality && QUALITY[m.quality]
  const pipOk = typeof document !== 'undefined' && document.pictureInPictureEnabled
  const pip = async () => {
    const vid = stage.current?.querySelector('video[data-remote="1"]') || stage.current?.querySelector('video')
    try { document.pictureInPictureElement ? await document.exitPictureInPicture() : await vid?.requestPictureInPicture() } catch { /* not available for this stream */ }
  }
  const fullscreen = () => (document.fullscreenElement ? document.exitFullscreen() : stage.current?.requestFullscreen?.())
  const cols = peers.length <= 1 ? 'grid-cols-1' : peers.length < 4 ? 'sm:grid-cols-2' : 'sm:grid-cols-2 xl:grid-cols-3'

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <h1 className="truncate text-xl font-semibold">{isCall && other ? `${m.hasCamera ? 'Video' : 'Voice'} call with ${other.name}` : meeting?.title || 'Meeting'}</h1>
          <p className="text-sm text-slate-600">{peers.length + 1} in the room{isCall ? ' · private call' : ''}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2" aria-label="Call status">
          <span role="status" aria-live="polite" className="inline-flex items-center gap-2 rounded-full bg-slate-100 px-3 py-1 text-sm text-slate-800">
            <span aria-hidden className={`h-2 w-2 rounded-full ${m.callState === 'connected' ? 'bg-emerald-500' : m.callState === 'failed' ? 'bg-red-500' : 'animate-pulse bg-amber-500'}`} />
            {statusText}
          </span>
          {m.callState === 'connected' && <span className="font-mono text-sm tabular-nums text-slate-800" aria-label="Call duration">{clock(secs)}</span>}
          {q && <Badge tone={q[1]}>{q[0]}</Badge>}
        </div>
      </div>
      {m.callState === 'failed' && <div className="mb-3"><Alert>The call could not be connected. A restrictive network may need a TURN server (see the deployment notes). <button type="button" className="font-medium underline" onClick={() => window.location.reload()}>Try again</button></Alert></div>}

      <div ref={stage} className="rounded-2xl bg-slate-950/5 p-2 data-[full=true]:bg-slate-950" data-full={full}>
        <div className={`grid gap-3 ${peers.length ? 'lg:grid-cols-[1fr_15rem]' : 'mx-auto max-w-3xl'}`}>
          {peers.length ? (
            <div className={`grid gap-3 ${cols}`}>
              {peers.map(([id, p]) => <RemoteTile key={id} p={p} sinkId={m.speakerId} />)}
            </div>
          ) : null}
          <div className={peers.length ? 'self-start' : ''}>
            <Tile stream={m.local} name={`${user.full_name} (you)`} muted avatarId={user.id} badge={m.muted ? <Badge tone="red">Muted</Badge> : m.sharing ? <Badge tone="blue">Sharing</Badge> : null} />
          </div>
        </div>
      </div>

      {meeting && (
        <section aria-label="Invited people" className="mx-auto mt-6 max-w-3xl rounded-xl border border-slate-200 bg-white p-3">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-800">{isCall ? 'Call between' : `Invited (${invited.length})`}</h2>
            {amHost && !isCall && <Button variant="secondary" onClick={() => setInviting(true)}>Invite more</Button>}
          </div>
          <ul className="divide-y divide-slate-100">
            {invited.map((p) => (
              <li key={p.id} className="flex items-center gap-2 py-1.5 text-sm">
                <Avatar name={p.name} size={6} userId={p.id} v={p.avatar_v} />
                <span className="min-w-0 flex-1 truncate">{p.name}{p.id === user.id ? ' (you)' : ''}</span>
                {p.is_host && <Badge tone="blue">Host</Badge>}
                {amHost && !p.is_host && !isCall && <Button variant="secondary" loading={remove.isPending && remove.variables === p.id} onClick={() => remove.mutate(p.id)} aria-label={`Remove ${p.name}`}>Remove</Button>}
              </li>
            ))}
          </ul>
        </section>
      )}
      <Modal open={inviting} onClose={() => setInviting(false)} title="Invite more people"
        footer={<><Button variant="secondary" onClick={() => setInviting(false)}>Cancel</Button><Button loading={add.isPending} disabled={pickCount(pick) === 0} onClick={() => add.mutate(pickBody(pick))}>Invite</Button></>}>
        <RecipientPicker value={pick} onChange={setPick} enabled={inviting} exclude={invited.map((p) => p.id)} />
      </Modal>
      <div className="sticky bottom-4 mt-6 flex flex-wrap justify-center gap-2 rounded-2xl border border-slate-200 bg-white p-3 shadow-lg" role="toolbar" aria-label="Meeting controls">
        <Button variant={m.muted ? 'danger' : 'secondary'} onClick={m.toggleMic} aria-pressed={m.muted}>{m.muted ? 'Unmute' : 'Mute'}</Button>
        <Button variant={m.camOff ? 'danger' : 'secondary'} onClick={m.toggleCam} aria-pressed={m.camOff} disabled={!m.hasCamera} title={!m.hasCamera ? 'You joined without a camera (voice call or no camera found)' : undefined}>{!m.hasCamera ? 'No camera' : m.camOff ? 'Camera on' : 'Camera off'}</Button>
        {m.hasCamera && m.devices.cams.length > 1 && <Button variant="secondary" onClick={m.switchCamera}>Switch camera</Button>}
        <Button variant={m.sharing ? 'primary' : 'secondary'} onClick={m.toggleShare} aria-pressed={m.sharing} disabled={!m.hasCamera} title={!m.hasCamera ? 'Screen sharing needs a video call' : undefined}>{m.sharing ? 'Stop sharing' : 'Share screen'}</Button>
        <Button variant="secondary" onClick={fullscreen} aria-pressed={full}>{full ? 'Exit full screen' : 'Full screen'}</Button>
        {pipOk && peers.length > 0 && <Button variant="secondary" onClick={pip}>Picture in picture</Button>}
        <DeviceMenu m={m} />
        {!isCall && <Button variant="secondary" onClick={() => navigator.clipboard?.writeText(window.location.href)}>Copy link</Button>}
        <Button variant="secondary" onClick={() => nav(leaveTo)}>Leave</Button>
        {canEnd && <Button variant="danger" loading={end.isPending} onClick={() => (isCall || window.confirm('End the meeting for everyone?')) && end.mutate()}>{isCall ? 'End call' : 'End meeting'}</Button>}
      </div>
    </div>
  )
}

function RemoteTile({ p, sinkId }) {
  const badge = p.sharing ? <Badge tone="blue">Presenting</Badge> : p.muted ? <Badge tone="red">Muted</Badge> : p.state && p.state !== 'connected' ? <Badge tone="amber">{p.state === 'failed' ? 'Failed' : p.state === 'reconnecting' ? 'Reconnecting' : 'Connecting'}</Badge> : null
  return <Tile stream={p.stream} name={p.name} sinkId={sinkId} large badge={badge} />
}
