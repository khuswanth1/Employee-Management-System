import { useEffect, useRef, useState } from 'react'
import { cx } from '../../components/ui'
import { fmtDuration } from './emoji'
import Icon from './icons'

// Only one player makes sound at a time: starting another one pauses the previous.
let nowPlaying = null
const SPEEDS = [1, 1.5, 2]
const BARS = 40

/** Peaks of the real audio, drawn as a waveform. Returns null when the browser cannot decode it (the plain progress bar is used). */
async function peaksOf(src) {
  const Ctx = window.AudioContext || window.webkitAudioContext
  if (!Ctx) return null
  const ctx = new Ctx()
  try {
    const data = await (await fetch(src)).arrayBuffer()
    const buf = await ctx.decodeAudioData(data)
    const ch = buf.getChannelData(0)
    const size = Math.floor(ch.length / BARS) || 1
    const peaks = Array.from({ length: BARS }, (_, i) => { let m = 0; for (let j = i * size; j < (i + 1) * size && j < ch.length; j += 16) m = Math.max(m, Math.abs(ch[j])); return m })
    const top = Math.max(...peaks) || 1
    return peaks.map((p) => Math.max(0.12, p / top))
  } catch {
    return null
  } finally {
    ctx.close?.().catch(() => {})
  }
}

/** Play/pause, seek, elapsed and total time, playback speed, volume and download for one audio file or voice message. */
export default function AudioPlayer({ src, name, duration, voice = false, mine = false, onDownload, label }) {
  const audio = useRef(null)
  const [playing, setPlaying] = useState(false)
  const [time, setTime] = useState(0)
  const [total, setTotal] = useState(duration || 0)
  const [speed, setSpeed] = useState(1)
  const [volume, setVolume] = useState(1)
  const [peaks, setPeaks] = useState(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => () => { if (nowPlaying === audio.current) nowPlaying = null }, [])
  useEffect(() => { if (voice && src) peaksOf(src).then(setPeaks) }, [voice, src])

  const toggle = async () => {
    const a = audio.current
    if (!a) return
    if (a.paused) {
      if (nowPlaying && nowPlaying !== a) nowPlaying.pause()
      nowPlaying = a
      try { await a.play() } catch { setFailed(true) }
    } else a.pause()
  }
  const seek = (t) => { if (audio.current) { audio.current.currentTime = t; setTime(t) } }
  const cycleSpeed = () => { const next = SPEEDS[(SPEEDS.indexOf(speed) + 1) % SPEEDS.length]; setSpeed(next); if (audio.current) audio.current.playbackRate = next }
  const setVol = (v) => { setVolume(v); if (audio.current) audio.current.volume = v }
  const length = Number.isFinite(total) && total > 0 ? total : duration || 0
  const tone = 'text-[#111b21]'
  const btn = 'inline-flex items-center gap-1 rounded-full bg-black/10 px-2 py-0.5 text-[11px] font-semibold text-[#111b21] hover:bg-black/15 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#008069]'

  return (
    <div className={cx('min-w-[15rem] max-w-full', tone)} role="group" aria-label={label || (voice ? 'Voice message' : `Audio ${name}`)}>
      {!voice && <p className="mb-1 flex items-center gap-1.5 truncate text-xs font-medium"><Icon name="music" size={14} className="text-[#f5a623]" />{name}</p>}
      <audio ref={audio} src={src} preload="metadata" className="sr-only" aria-hidden tabIndex={-1}
        onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={() => { setPlaying(false); setTime(0) }}
        onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)} onLoadedMetadata={(e) => setTotal(e.currentTarget.duration)}
        onDurationChange={(e) => setTotal(e.currentTarget.duration)} onError={() => setFailed(true)} />
      {failed ? <p className="text-xs italic">This audio could not be played.</p> : (
        <>
          <div className="flex items-center gap-2">
            <button type="button" onClick={toggle} aria-label={playing ? 'Pause' : 'Play'} className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[#00a884] text-white hover:bg-[#008f6f] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#008069]"><Icon name={playing ? 'pause' : 'play'} size={22} /></button>
            <div className="min-w-0 flex-1">
              {peaks ? (
                <div className="flex h-8 cursor-pointer items-center gap-px" aria-hidden onClick={(e) => { const r = e.currentTarget.getBoundingClientRect(); seek(((e.clientX - r.left) / r.width) * length) }}>
                  {peaks.map((p, i) => <span key={i} className={cx('w-full rounded-sm', i / BARS <= (length ? time / length : 0) ? 'bg-[#008069]' : 'bg-[#8696a0]')} style={{ height: `${Math.round(p * 100)}%` }} />)}
                </div>
              ) : null}
              <input type="range" aria-label="Seek" min={0} max={length || 1} step={0.1} value={Math.min(time, length || 1)} onChange={(e) => seek(Number(e.target.value))} className={cx('h-1.5 w-full accent-[#00a884]', peaks && 'sr-only')} />
            </div>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px]">
            <span className="tabular-nums" aria-label="Elapsed and total time">{fmtDuration(time)} / {fmtDuration(length)}</span>
            <button type="button" onClick={cycleSpeed} aria-label={`Playback speed ${speed}x`} className={btn}>{speed}x</button>
            {!voice && (
              <label className="flex items-center gap-1">
                <span className="text-[#54656f]">Vol</span>
                <input type="range" aria-label="Volume" min={0} max={1} step={0.05} value={volume} onChange={(e) => setVol(Number(e.target.value))} className="h-1.5 w-16 accent-[#00a884]" />
              </label>
            )}
            {onDownload && <button type="button" onClick={onDownload} aria-label={`Download ${name}`} className={cx(btn, 'ml-auto')}><Icon name="download" size={13} />Download</button>}
          </div>
        </>
      )}
    </div>
  )
}
