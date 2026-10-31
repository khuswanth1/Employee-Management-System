import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, wsUrl } from '../../lib/api'

/**
 * Mesh WebRTC over the WorkSphere signaling socket (one socket per room, see the backend meetings router).
 *
 * - The newcomer sends offers to everyone already in the room; existing peers answer.
 * - Every peer connection reports its real state. `callState` is only "connected" once media can actually flow.
 * - A peer that drops or fails gets an ICE restart from the side that made the original offer; if the signaling socket drops
 *   the hook reconnects it with back-off and renegotiates.
 * - Screen sharing swaps the outgoing video track (needs a camera track; a voice-only join cannot share its screen).
 * - Leaving or unmounting stops every track and closes every connection.
 */
const MAX_WS_RETRIES = 6
const SAMPLE_MS = 3000
const DISCONNECT_GRACE_MS = 3000
const GIVE_UP_MS = 15000

const peerState = (pc) => {
  const s = pc.connectionState
  if (s === 'connected') return 'connected'
  if (s === 'disconnected') return 'reconnecting'
  if (s === 'failed') return 'failed'
  return 'connecting'
}

/** `audioOnly` joins with the microphone only (a voice call). */
export function useMeeting(room, { audioOnly = false, enabled = true } = {}) {
  const [status, setStatus] = useState('connecting') // connecting | live | error | ended
  const [error, setError] = useState(null)
  const [wsState, setWsState] = useState('connecting') // connecting | open | reconnecting
  const [local, setLocal] = useState(null)
  const [remotes, setRemotes] = useState({}) // peerId -> {name, stream, sharing, state, muted}
  const [muted, setMuted] = useState(false)
  const [camOff, setCamOff] = useState(false)
  const [sharing, setSharing] = useState(false)
  const [quality, setQuality] = useState(null) // good | fair | poor
  const [connectedAt, setConnectedAt] = useState(null)
  const [devices, setDevices] = useState({ mics: [], cams: [], speakers: [] })
  const [speakerId, setSpeakerId] = useState('')
  const ref = useRef({ ws: null, pcs: {}, names: {}, pending: {}, offerer: {}, restarts: {}, timers: {}, stream: null, screen: null, ice: [], retries: 0, retryTimer: null, sample: null })

  const send = useCallback((msg) => { const ws = ref.current.ws; if (ws?.readyState === 1) ws.send(JSON.stringify(msg)) }, [])
  const patch = useCallback((peerId, p) => setRemotes((s) => (s[peerId] ? { ...s, [peerId]: { ...s[peerId], ...p } } : s)), [])

  const dropPeer = useCallback((peerId) => {
    const r = ref.current
    clearTimeout(r.timers[peerId])
    r.pcs[peerId]?.close()
    delete r.pcs[peerId]; delete r.pending[peerId]; delete r.offerer[peerId]; delete r.restarts[peerId]; delete r.timers[peerId]
    setRemotes((s) => { const { [peerId]: _gone, ...rest } = s; return rest })
  }, [])

  const restartIce = useCallback(async (peerId) => {
    const r = ref.current
    const pc = r.pcs[peerId]
    if (!pc || !r.offerer[peerId] || (r.restarts[peerId] || 0) >= 3) return
    r.restarts[peerId] = (r.restarts[peerId] || 0) + 1
    try {
      pc.restartIce?.()
      const offer = await pc.createOffer({ iceRestart: true })
      await pc.setLocalDescription(offer)
      send({ type: 'offer', to: peerId, data: pc.localDescription })
    } catch { /* the next state change tries again */ }
  }, [send])

  const watchPeer = useCallback((peerId, pc) => {
    const r = ref.current
    pc.onconnectionstatechange = () => {
      if (pc.connectionState === 'closed') return
      const st = peerState(pc)
      patch(peerId, { state: st })
      clearTimeout(r.timers[peerId])
      if (st === 'connected') {
        r.restarts[peerId] = 0
        setConnectedAt((t) => t ?? Date.now())
      } else if (st === 'reconnecting') {
        r.timers[peerId] = setTimeout(() => { if (r.pcs[peerId] && r.pcs[peerId].connectionState !== 'connected') restartIce(peerId) }, DISCONNECT_GRACE_MS)
      } else if (st === 'failed') {
        restartIce(peerId)
        r.timers[peerId] = setTimeout(() => { if (r.pcs[peerId] && r.pcs[peerId].connectionState !== 'connected') patch(peerId, { state: 'failed' }) }, GIVE_UP_MS)
        patch(peerId, { state: r.offerer[peerId] ? 'reconnecting' : 'failed' })
      }
    }
  }, [patch, restartIce])

  const makePeer = useCallback((peerId, name) => {
    const r = ref.current
    if (r.pcs[peerId]) return r.pcs[peerId]
    r.names[peerId] = name
    const pc = new RTCPeerConnection({ iceServers: r.ice })
    r.pcs[peerId] = pc
    r.pending[peerId] = []
    r.stream?.getTracks().forEach((t) => pc.addTrack(t, r.stream))
    pc.onicecandidate = (e) => e.candidate && send({ type: 'ice', to: peerId, data: e.candidate })
    pc.ontrack = (e) => setRemotes((s) => ({ ...s, [peerId]: { ...s[peerId], name: r.names[peerId], stream: e.streams[0] } }))
    watchPeer(peerId, pc)
    setRemotes((s) => ({ ...s, [peerId]: { ...s[peerId], name, state: 'connecting' } }))
    return pc
  }, [send, watchPeer])

  const refreshDevices = useCallback(async () => {
    try {
      const all = await navigator.mediaDevices.enumerateDevices()
      const pick = (kind, word) => all.filter((d) => d.kind === kind && d.deviceId).map((d, i) => ({ id: d.deviceId, label: d.label || `${word} ${i + 1}` }))
      setDevices({ mics: pick('audioinput', 'Microphone'), cams: pick('videoinput', 'Camera'), speakers: pick('audiooutput', 'Speaker') })
    } catch { /* device lists are a convenience */ }
  }, [])

  useEffect(() => {
    if (!enabled) return undefined // the caller is still finding out what kind of call this is
    const r = ref.current
    let closed = false // per effect run: React may mount, clean up and mount again, and a cancelled run must never open a socket
    r.retries = 0
    const handle = async (m) => {
      if (m.type === 'error') {
        setStatus(m.reason === 'ended' ? 'ended' : 'error')
        setError(m.reason === 'room_full' ? 'This meeting is full (max 8 participants).' : m.reason === 'ended' ? 'This meeting has ended.' : m.reason === 'removed' ? 'You were removed from this meeting.' : 'Meeting not found, or you have not been invited.')
        closed = true
        return
      }
      if (m.type === 'joined') {
        setStatus('live'); setWsState('open'); r.retries = 0
        for (const p of m.peers) {
          const pc = makePeer(p.peer_id, p.name)
          r.offerer[p.peer_id] = true
          const offer = await pc.createOffer()
          await pc.setLocalDescription(offer)
          send({ type: 'offer', to: p.peer_id, data: pc.localDescription })
        }
      } else if (m.type === 'peer-joined') makePeer(m.peer_id, m.name)
      else if (m.type === 'peer-left') dropPeer(m.peer_id)
      else if (m.type === 'offer') {
        const pc = makePeer(m.from, r.names[m.from] || 'Participant')
        await pc.setRemoteDescription(m.data)
        for (const c of r.pending[m.from].splice(0)) await pc.addIceCandidate(c)
        const ans = await pc.createAnswer()
        await pc.setLocalDescription(ans)
        send({ type: 'answer', to: m.from, data: pc.localDescription })
      } else if (m.type === 'answer') {
        const pc = r.pcs[m.from]
        if (pc) { await pc.setRemoteDescription(m.data); for (const c of r.pending[m.from].splice(0)) await pc.addIceCandidate(c) }
      } else if (m.type === 'ice') {
        const pc = r.pcs[m.from]
        if (!pc) return
        if (pc.remoteDescription) await pc.addIceCandidate(m.data).catch(() => {})
        else r.pending[m.from].push(m.data)
      } else if (m.type === 'screen-share') patch(m.from, { sharing: m.active })
      else if (m.type === 'mute') patch(m.from, { muted: m.active })
    }

    const openSocket = () => {
      const ws = new WebSocket(wsUrl(`/meetings/ws/${room}`))
      r.ws = ws
      ws.onopen = () => ws.send(JSON.stringify({ type: 'auth' }))
      ws.onmessage = (e) => { handle(JSON.parse(e.data)).catch(() => { /* one bad signal must not end the call */ }) }
      ws.onclose = () => {
        if (closed) return
        // the signaling socket dropped: media may still flow for a moment, but peer ids change on rejoin, so start clean and retry
        Object.keys(r.pcs).forEach(dropPeer)
        if (r.retries >= MAX_WS_RETRIES) { setStatus('error'); setError('Connection to the meeting was lost.'); return }
        setWsState('reconnecting')
        r.retryTimer = setTimeout(openSocket, Math.min(8000, 1000 * 2 ** r.retries++))
      }
    }

    ;(async () => {
      try {
        const [{ iceServers }, stream] = await Promise.all([
          api.get('/meetings/ice-config'),
          navigator.mediaDevices.getUserMedia({ audio: true, video: !audioOnly }).catch((e) => {
            if (e?.name === 'NotAllowedError' || audioOnly) throw e
            return navigator.mediaDevices.getUserMedia({ audio: true })  // no camera: join with the microphone only
          }),
        ])
        if (closed) { stream.getTracks().forEach((t) => t.stop()); return }
        r.ice = iceServers; r.stream = stream; setLocal(stream)
        refreshDevices()
        openSocket()
        r.sample = setInterval(async () => {
          const pcs = Object.values(r.pcs).filter((p) => p.connectionState === 'connected')
          if (!pcs.length) { setQuality(null); return }
          let rtt = 0, lost = 0, recv = 0
          for (const pc of pcs) {
            try {
              for (const st of (await pc.getStats()).values()) {
                if (st.type === 'candidate-pair' && st.state === 'succeeded' && st.nominated && typeof st.currentRoundTripTime === 'number') rtt = Math.max(rtt, st.currentRoundTripTime * 1000)
                if (st.type === 'inbound-rtp') { lost += st.packetsLost || 0; recv += st.packetsReceived || 0 }
              }
            } catch { /* stats are best-effort */ }
          }
          const loss = recv + lost ? lost / (recv + lost) : 0
          setQuality(rtt > 400 || loss > 0.08 ? 'poor' : rtt > 200 || loss > 0.03 ? 'fair' : 'good')
        }, SAMPLE_MS)
      } catch (e) {
        setStatus('error')
        setError(e?.name === 'NotAllowedError' ? 'Camera/microphone permission was denied.' : e?.name === 'NotFoundError' ? 'No microphone was found on this device.' : e?.message || 'Could not start the meeting.')
      }
    })()
    navigator.mediaDevices?.addEventListener?.('devicechange', refreshDevices)
    const cleanup = () => {
      closed = true
      clearInterval(r.sample); clearTimeout(r.retryTimer)
      Object.values(r.timers).forEach(clearTimeout)
      Object.values(r.pcs).forEach((pc) => pc.close())
      r.pcs = {}
      r.ws?.close()
      r.stream?.getTracks().forEach((t) => t.stop())
      r.screen?.getTracks().forEach((t) => t.stop())
      navigator.mediaDevices?.removeEventListener?.('devicechange', refreshDevices)
    }
    window.addEventListener('pagehide', cleanup)
    return () => { window.removeEventListener('pagehide', cleanup); cleanup() }
  }, [room, audioOnly, enabled, makePeer, dropPeer, patch, send, refreshDevices])

  const toggleMic = () => { const t = ref.current.stream?.getAudioTracks()[0]; if (t) { t.enabled = muted; setMuted(!muted); send({ type: 'mute', active: !muted }) } }
  const toggleCam = () => { const t = ref.current.stream?.getVideoTracks()[0]; if (t) { t.enabled = camOff; setCamOff(!camOff) } }
  const hasCamera = !!local && local.getVideoTracks().length > 0

  const swapTrack = async (kind, track) => {
    await Promise.all(Object.values(ref.current.pcs).map((pc) => pc.getSenders().find((s) => s.track?.kind === kind)?.replaceTrack(track)))
  }
  const stopShare = useCallback(async () => {
    const r = ref.current
    r.screen?.getTracks().forEach((t) => t.stop()); r.screen = null
    const cam = r.stream?.getVideoTracks()[0]
    if (cam) await swapTrack('video', cam)
    setSharing(false); send({ type: 'screen-share', active: false })
  }, [send])
  const toggleShare = async () => {
    if (sharing) return stopShare()
    if (!ref.current.stream?.getVideoTracks().length) return // a voice-only join has no video sender to swap
    try {
      const screen = await navigator.mediaDevices.getDisplayMedia({ video: true })
      ref.current.screen = screen
      const track = screen.getVideoTracks()[0]
      track.onended = stopShare
      await swapTrack('video', track)
      setSharing(true); send({ type: 'screen-share', active: true })
    } catch { /* user cancelled the picker */ }
  }

  /** Replace the microphone or camera with another device without renegotiating. */
  const useDevice = async (kind, deviceId) => {
    const r = ref.current
    const constraint = kind === 'audio' ? { audio: { deviceId: { exact: deviceId } } } : { video: { deviceId: { exact: deviceId } } }
    const fresh = (await navigator.mediaDevices.getUserMedia(constraint)).getTracks()[0]
    const old = kind === 'audio' ? r.stream.getAudioTracks()[0] : r.stream.getVideoTracks()[0]
    fresh.enabled = kind === 'audio' ? !muted : !camOff
    if (old) { r.stream.removeTrack(old); old.stop() }
    r.stream.addTrack(fresh)
    if (!(kind === 'video' && sharing)) await swapTrack(fresh.kind, fresh)
    setLocal(new MediaStream(r.stream.getTracks()))
    refreshDevices()
  }
  const switchCamera = async () => {
    if (devices.cams.length < 2) return
    const current = ref.current.stream?.getVideoTracks()[0]?.getSettings().deviceId
    const idx = devices.cams.findIndex((d) => d.id === current)
    await useDevice('video', devices.cams[(idx + 1) % devices.cams.length].id)
  }

  const callState = useMemo(() => {
    if (status === 'error' || status === 'ended') return status
    if (wsState === 'reconnecting') return 'reconnecting'
    if (status === 'connecting') return 'connecting'
    const peers = Object.values(remotes)
    if (!peers.length) return 'waiting'
    if (peers.some((p) => p.state === 'connected')) return 'connected'
    if (peers.some((p) => p.state === 'reconnecting')) return 'reconnecting'
    if (peers.every((p) => p.state === 'failed')) return 'failed'
    return 'negotiating'
  }, [status, wsState, remotes])

  return { status, callState, error, local, remotes, muted, camOff, sharing, quality, connectedAt, devices, speakerId, setSpeakerId, hasCamera,
    toggleMic, toggleCam, toggleShare, selectMic: (id) => useDevice('audio', id), selectCamera: (id) => useDevice('video', id), switchCamera }
}
