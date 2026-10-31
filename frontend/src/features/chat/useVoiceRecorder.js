import { useCallback, useEffect, useRef, useState } from 'react'

export const MAX_RECORD_SECONDS = 300
// The first type this browser can record: Chrome/Edge/Firefox give webm or ogg, Safari gives mp4 (m4a).
const CANDIDATES = [['audio/webm;codecs=opus', 'webm'], ['audio/webm', 'webm'], ['audio/ogg;codecs=opus', 'ogg'], ['audio/mp4', 'm4a']]
const pickType = () => (typeof MediaRecorder === 'undefined' ? null : CANDIDATES.find(([t]) => MediaRecorder.isTypeSupported?.(t)) || null)

/**
 * Records a voice message from the microphone, with pause / resume and a preview before sending.
 * state: idle -> recording <-> paused -> preview (-> idle after send or discard).
 * `result` is `{ file, seconds, url }` in the preview state. Every stream, recorder, timer and object URL is released on unmount.
 */
export function useVoiceRecorder() {
  const [state, setState] = useState('idle')
  const [seconds, setSeconds] = useState(0)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)
  const r = useRef({ rec: null, chunks: [], stream: null, timer: null, elapsed: 0, since: 0, type: null, cancelled: false })
  const supported = typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia && !!pickType()
  const canPause = typeof MediaRecorder !== 'undefined' && typeof MediaRecorder.prototype?.pause === 'function'

  const release = useCallback(() => {
    clearInterval(r.current.timer)
    r.current.stream?.getTracks().forEach((t) => t.stop())
    r.current.stream = null
    r.current.rec = null
  }, [])

  const elapsed = () => Math.round((r.current.elapsed + (r.current.since ? Date.now() - r.current.since : 0)) / 1000)

  const finish = useCallback(() => {
    const type = r.current.type
    const secs = Math.max(1, elapsed())
    const blob = new Blob(r.current.chunks, { type: type[0].split(';')[0] })
    release()
    if (r.current.cancelled) { setState('idle'); setSeconds(0); return }
    if (!blob.size) { setState('idle'); setSeconds(0); setError('Nothing was recorded. Check your microphone and try again.'); return }
    setResult({ file: new File([blob], `recording.${type[1]}`, { type: blob.type }), seconds: secs, url: URL.createObjectURL(blob) })
    setSeconds(secs)
    setState('preview')
  }, [release])

  const start = useCallback(async () => {
    setError(null)
    const type = pickType()
    if (!type) { setError('Voice messages are not supported in this browser'); return }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const rec = new MediaRecorder(stream, { mimeType: type[0] })
      Object.assign(r.current, { rec, stream, chunks: [], type, elapsed: 0, since: Date.now(), cancelled: false })
      rec.ondataavailable = (e) => { if (e.data?.size) r.current.chunks.push(e.data) }
      rec.onstop = finish
      rec.onerror = () => { release(); setState('idle'); setError('Recording failed. Please try again.') }
      rec.start()
      setSeconds(0); setState('recording')
      r.current.timer = setInterval(() => {
        const s = elapsed()
        setSeconds(s)
        if (s >= MAX_RECORD_SECONDS && r.current.rec?.state !== 'inactive') r.current.rec?.stop()  // the limit ends the recording and opens the preview
      }, 250)
    } catch (e) {
      release()
      setState('idle')
      setError(e?.name === 'NotAllowedError' ? 'Microphone access was blocked. Allow it in the browser to record.' : e?.name === 'NotFoundError' ? 'No microphone was found on this device.' : 'Could not start recording.')
    }
  }, [finish, release])

  const pause = useCallback(() => {
    const rec = r.current.rec
    if (rec?.state !== 'recording' || !canPause) return
    rec.pause()
    r.current.elapsed += Date.now() - r.current.since; r.current.since = 0
    setState('paused')
  }, [canPause])
  const resume = useCallback(() => {
    const rec = r.current.rec
    if (rec?.state !== 'paused') return
    rec.resume()
    r.current.since = Date.now()
    setState('recording')
  }, [])
  const stop = useCallback(() => {
    const rec = r.current.rec
    if (rec && rec.state !== 'inactive') {
      if (r.current.since) { r.current.elapsed += Date.now() - r.current.since; r.current.since = 0 }
      rec.stop()
    }
  }, [])
  /** Throws a recording or a preview away. */
  const discard = useCallback(() => {
    r.current.cancelled = true
    const rec = r.current.rec
    if (rec && rec.state !== 'inactive') { rec.onstop = null; rec.stop() }
    release()
    setResult((x) => { if (x?.url) URL.revokeObjectURL(x.url); return null })
    setState('idle'); setSeconds(0)
  }, [release])

  useEffect(() => () => {
    r.current.cancelled = true
    const rec = r.current.rec
    if (rec && rec.state !== 'inactive') { rec.onstop = null; rec.stop() }
    release()
  }, [release])
  useEffect(() => () => { if (result?.url) URL.revokeObjectURL(result.url) }, [result])

  return { supported, canPause, state, seconds, error, result, start, pause, resume, stop, discard }
}
