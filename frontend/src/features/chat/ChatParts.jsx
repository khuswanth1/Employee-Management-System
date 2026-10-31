import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { Alert, cx } from '../../components/ui'
import { api, download, uploadWithProgress } from '../../lib/api'
import { fmtDateTime, fmtTime } from '../../lib/format'
import { useAction } from '../../lib/hooks'
import { useRealtime } from '../notifications/NotificationsProvider'
import AudioPlayer from './AudioPlayer'
import { useBlob } from './ImageViewer'
import { EmojiPicker, StickerPicker } from './Pickers'
import { checkFile, fmtDuration, fmtSize, insertAtCursor, kindOfFile, recordEmoji, recordSticker } from './emoji'
import Icon, { IconButton } from './icons'
import { useVoiceRecorder } from './useVoiceRecorder'

const QUICK = ['👍', '❤️', '😂', '😮', '😢', '🙏', '🎉', '👏']
const ACCEPT = {
  photo: 'image/png,image/jpeg,image/gif,image/webp',
  audio: 'audio/mpeg,audio/wav,audio/ogg,audio/mp4,.mp3,.wav,.ogg,.m4a,.opus',
  document: '.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.csv,.md',
}
// document colours: red PDF, blue Word, green Excel, orange PowerPoint, grey everything else
const DOC_COLOUR = { pdf: 'bg-[#e53935]', doc: 'bg-[#1e66c2]', docx: 'bg-[#1e66c2]', xls: 'bg-[#1b873f]', xlsx: 'bg-[#1b873f]', ppt: 'bg-[#d4511f]', pptx: 'bg-[#d4511f]' }
const extOf = (n = '') => (n.split('.').pop() || '').toLowerCase()
const GREEN = '#00a884'   // action green (icons, buttons)
const GREEN_DARK = '#008069' // text-bearing green (4.5:1 on white)

const DocBadge = ({ name, size = 'h-10 w-10' }) => (
  <span aria-hidden className={cx('flex shrink-0 items-center justify-center rounded-lg text-white', size, DOC_COLOUR[extOf(name)] || 'bg-[#667781]')}><Icon name="doc" size={22} /></span>
)

// ---- message bubble ----------------------------------------------------------------------------------------------

function Photo({ m, onOpen }) {
  const { data: src, isError } = useBlob(m.file.url)
  if (isError) return <p className="p-2 text-xs italic">Photo unavailable</p>
  if (!src) return <div className="h-36 w-52 animate-pulse rounded-lg bg-black/10" aria-label="Loading photo" />
  return (
    <button type="button" onClick={() => onOpen(m.id)} aria-label={`Open photo ${m.file.name}`} className="block overflow-hidden rounded-lg">
      <img src={src} alt={m.file.name} loading="lazy" className="max-h-72 max-w-full object-cover" />
    </button>
  )
}

function Doc({ file }) {
  const [state, setState] = useState('idle') // idle | busy | done | failed
  const ext = extOf(file.name)
  const get = async () => { setState('busy'); try { await download(file.url, file.name); setState('done') } catch { setState('failed') } }
  return (
    <button type="button" onClick={get} disabled={state === 'busy'} className="flex w-64 max-w-full items-center gap-3 rounded-lg bg-black/5 p-2 text-left text-sm hover:bg-black/10">
      <DocBadge name={file.name} />
      <span className="min-w-0 flex-1">
        <span className="block truncate font-medium">{file.name}</span>
        <span className="block text-xs text-[#54656f]">{ext.toUpperCase()} · {fmtSize(file.size)} · {state === 'busy' ? 'Downloading…' : state === 'done' ? 'Downloaded' : state === 'failed' ? 'Failed, tap to retry' : 'Tap to download'}</span>
      </span>
    </button>
  )
}

function Audio({ m }) {
  const { data: src, isError } = useBlob(m.file.url)
  const voice = (m.file.name || '').startsWith('voice-')
  if (isError) return <p className="p-2 text-xs italic">Audio unavailable</p>
  if (!src) return <p className="p-2 text-xs">Loading audio…</p>
  return <AudioPlayer src={src} name={m.file.name} duration={m.file.duration_s} voice={voice} onDownload={() => download(m.file.url, m.file.name)} />
}

const Ticks = ({ state }) => (
  <span role="img" aria-label={state === 'read' ? 'Read' : state === 'delivered' ? 'Delivered' : 'Sent'} title={state === 'read' ? 'Read' : state === 'delivered' ? 'Delivered' : 'Sent'}
    className={cx('ml-1 inline-flex', state === 'read' ? 'text-[#2f9ec6]' : 'text-[#54656f]')}><Icon name={state === 'sent' ? 'check' : 'checks'} size={16} /></span>
)

const tool = 'inline-flex h-7 w-7 items-center justify-center rounded-full text-[#54656f] hover:bg-black/5 focus-visible:bg-black/5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#008069]'

export function MessageBubble({ m, me, mine, showSender, receipt, onReact, onReply, onEdit, onDelete, onOpenImage, onJump }) {
  const [picking, setPicking] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const [copied, setCopied] = useState(false)
  const sticker = m.kind === 'sticker'
  const editable = mine && !m.deleted && ['text', 'image', 'audio', 'file'].includes(m.kind)
  const copy = async () => { try { await navigator.clipboard.writeText(m.body); setCopied(true); setTimeout(() => setCopied(false), 1500) } catch { /* clipboard blocked */ } }

  if (m.deleted) {
    return (
      <div className={cx('flex', mine ? 'justify-end' : 'justify-start')} data-mid={m.id}>
        <p className={cx('flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm italic text-[#54656f] shadow-sm', mine ? 'bg-[#d9fdd3]' : 'bg-white')}><Icon name="close" size={15} />{mine ? 'You deleted this message' : 'This message was deleted'}</p>
      </div>
    )
  }
  const tail = sticker ? '' : mine
    ? "rounded-tr-none after:absolute after:-right-2 after:top-0 after:h-0 after:w-0 after:border-b-[10px] after:border-l-[9px] after:border-b-transparent after:border-l-[#d9fdd3] after:content-['']"
    : "rounded-tl-none before:absolute before:-left-2 before:top-0 before:h-0 before:w-0 before:border-b-[10px] before:border-r-[9px] before:border-b-transparent before:border-r-white before:content-['']"
  return (
    <div className={cx('group flex', mine ? 'justify-end' : 'justify-start')} data-mid={m.id}>
      <div className="max-w-[80%] sm:max-w-[68%]">
        <div className={cx('relative rounded-lg text-[14.2px] leading-[19px] text-[#111b21]', sticker ? 'bg-transparent' : cx('px-2.5 pb-1 pt-1.5 shadow-[0_1px_0.5px_rgba(11,20,26,0.13)]', mine ? 'bg-[#d9fdd3]' : 'bg-white'), tail)}>
          {showSender && <p className="mb-0.5 text-[12.8px] font-medium text-[#1f7aa8]">{m.sender_name}</p>}
          {m.reply_to && (
            <button type="button" onClick={() => onJump?.(m.reply_to.id)} aria-label={`Replying to ${m.reply_to.sender_name}: ${m.reply_to.preview}`} className={cx('mb-1 block w-full rounded-md border-l-4 border-[#06cf9c] px-2 py-1 text-left text-[12.8px]', mine ? 'bg-black/[0.06]' : 'bg-[#f5f6f6]')}>
              <span className="block font-medium text-[#008069]">{m.reply_to.sender_name}</span>
              <span className="block truncate text-[#54656f]">{m.reply_to.preview}</span>
            </button>
          )}
          {sticker ? <span role="img" aria-label={`Sticker: ${m.sticker.label}`} className="block text-7xl leading-none drop-shadow-sm">{m.sticker.emoji}</span> : (
            <>
              {m.kind === 'image' && m.file && <Photo m={m} onOpen={onOpenImage} />}
              {m.kind === 'audio' && m.file && <Audio m={m} />}
              {m.kind === 'file' && m.file && <Doc file={m.file} />}
              {m.body && <p className={cx('whitespace-pre-wrap break-words', m.kind !== 'text' && 'mt-1')}>{m.body}</p>}
            </>
          )}
          <p className={cx('mt-0.5 flex items-center justify-end gap-0.5 text-[11px] text-[#54656f]', sticker && 'rounded-full bg-white/80 px-1.5')}>
            {m.edited_at && <span className="mr-1">edited</span>}
            <span title={fmtDateTime(m.created_at)}>{fmtTime(m.created_at)}</span>
            {mine && receipt && <Ticks state={receipt} />}
          </p>
        </div>
        {(m.reactions || []).length > 0 && (
          <div className={cx('relative z-10 -mt-1.5 flex flex-wrap gap-1 px-1.5', mine ? 'justify-end' : 'justify-start')}>
            {m.reactions.map((r) => {
              const reacted = r.user_ids.includes(me)
              return (
                <button key={r.emoji} type="button" aria-pressed={reacted} aria-label={`${r.emoji} ${r.user_ids.length}${reacted ? ', you reacted' : ''}`} title={reacted ? 'Click to remove your reaction' : 'React too'} onClick={() => onReact(m.id, r.emoji)}
                  className={cx('rounded-full border bg-white px-1.5 py-px text-xs shadow-sm', reacted ? 'border-[#008069] text-[#008069]' : 'border-black/10 text-[#111b21]')}>
                  {r.emoji}{r.user_ids.length > 1 ? ` ${r.user_ids.length}` : ' 1'}
                </button>
              )
            })}
          </div>
        )}
        <div className={cx('mt-0.5 flex flex-wrap items-center gap-1', mine ? 'justify-end' : 'justify-start')}>
          <span role="toolbar" aria-label="Message actions" className="flex items-center gap-0.5 rounded-full bg-white px-1 py-0.5 opacity-0 shadow-sm ring-1 ring-black/5 focus-within:opacity-100 group-hover:opacity-100 [@media(hover:none)]:opacity-100">
            <button type="button" aria-label="Add reaction" aria-expanded={picking} className={tool} onClick={() => setPicking((v) => !v)}><Icon name={picking ? 'close' : 'smile'} size={17} /></button>
            <button type="button" aria-label="Reply" className={tool} onClick={() => onReply(m)}><Icon name="reply" size={17} /></button>
            {m.body && m.kind === 'text' && <button type="button" aria-label="Copy text" className={tool} onClick={copy}>{copied ? <span className="px-1 text-[11px] font-medium text-[#008069]">Copied</span> : <Icon name="copy" size={16} />}</button>}
            {editable && <button type="button" aria-label="Edit message" className={tool} onClick={() => onEdit(m)}><Icon name="edit" size={16} /></button>}
            {mine && !confirm && <button type="button" aria-label="Delete message" className={cx(tool, 'text-[#c0392b]')} onClick={() => setConfirm(true)}><Icon name="trash" size={17} /></button>}
            {mine && confirm && (
              <span className="flex items-center gap-1 px-1 text-xs text-[#111b21]">
                <span>Delete for everyone?</span>
                <button type="button" className="rounded px-1.5 py-0.5 font-semibold text-[#c0392b] hover:bg-black/5" onClick={() => { setConfirm(false); onDelete(m.id) }}>Yes, delete</button>
                <button type="button" className="rounded px-1.5 py-0.5 hover:bg-black/5" onClick={() => setConfirm(false)}>Keep</button>
              </span>
            )}
          </span>
          {picking && (
            <span role="group" aria-label="Choose a reaction" className="flex gap-0.5 rounded-full bg-white px-1.5 py-0.5 shadow-md ring-1 ring-black/5">
              {QUICK.map((e) => <button key={e} type="button" aria-label={`React ${e}`} className="rounded-full px-1 text-lg transition-transform hover:scale-125" onClick={() => { onReact(m.id, e); setPicking(false) }}>{e}</button>)}
            </span>
          )}
        </div>
      </div>
    </div>
  )
}

// ---- composer ---------------------------------------------------------------------------------------------------------

let nextId = 1
const Chip = ({ f, onRemove, onCancel, onRetry }) => (
  <li className="flex items-center gap-2 rounded-lg bg-white p-1.5 text-sm shadow-sm" role="status" aria-label={`${f.file.name}, ${f.status}`}>
    {f.preview ? <img src={f.preview} alt="" className="h-11 w-11 rounded-md object-cover" /> : f.kind === 'audio' ? <span aria-hidden className="flex h-11 w-11 items-center justify-center rounded-lg bg-[#f5a623] text-white"><Icon name="music" size={22} /></span> : <DocBadge name={f.file.name} size="h-11 w-11" />}
    <span className="min-w-0 flex-1">
      <span className="block truncate">{f.file.name} <span className="text-xs text-[#54656f]">({fmtSize(f.file.size)})</span></span>
      {f.status === 'uploading' && <span className="mt-1 block h-1 overflow-hidden rounded bg-black/10" role="progressbar" aria-label={`Uploading ${f.file.name}`} aria-valuenow={f.progress} aria-valuemin={0} aria-valuemax={100}><span className="block h-full bg-[#00a884] transition-all" style={{ width: `${f.progress}%` }} /></span>}
      {f.status === 'error' && <span className="block text-xs text-[#b3261e]">{f.error}</span>}
    </span>
    {f.status === 'uploading' && <button type="button" className="px-2 text-xs font-medium text-[#008069] hover:underline" onClick={() => onCancel(f.id)}>Cancel</button>}
    {f.status === 'error' && <button type="button" className="px-2 text-xs font-medium text-[#008069] hover:underline" onClick={() => onRetry(f.id)}>Retry</button>}
    {f.status !== 'uploading' && <IconButton icon="close" label={`Remove ${f.file.name}`} size={18} className="h-8 w-8" onClick={() => onRemove(f.id)} />}
  </li>
)

const barCls = 'border-t border-black/5 bg-[#f0f2f5] px-3 py-2'

/** Text, emoji, stickers, a quick like, files (photo / audio / document, several at once, drag and drop) and voice messages. */
export function Composer({ convId, disabled, me, replyTo, onClearReply, editing, onClearEdit, incoming, onIncomingHandled }) {
  const qc = useQueryClient()
  const { sendTyping } = useRealtime()
  const [text, setText] = useState('')
  const [panel, setPanel] = useState(null) // emoji | sticker | attach
  const [files, setFiles] = useState([])
  const [problem, setProblem] = useState(null)
  const [voiceUp, setVoiceUp] = useState(null) // { progress, error }
  const aborts = useRef({})
  const voiceAbort = useRef(null)
  const area = useRef(null)
  const inputs = { photo: useRef(null), audio: useRef(null), document: useRef(null) }
  const voice = useVoiceRecorder()
  const base = `/chat/conversations/${convId}`
  const refresh = () => qc.invalidateQueries({ predicate: (q) => /^\/chat/.test(q.queryKey[0]) })
  const replyId = replyTo?.id

  const sendText = useAction((body) => (editing ? api.patch(`/chat/messages/${editing.id}`, { body }) : api.post(`${base}/messages`, { body, ...(replyId ? { reply_to_id: replyId } : {}) })),
    { invalidate: ['/chat'], onSuccess: () => { setText(''); onClearReply?.(); onClearEdit?.() } })
  const sendSticker = useAction((id) => api.post(`${base}/stickers`, { sticker: id, ...(replyId ? { reply_to_id: replyId } : {}) }), { invalidate: ['/chat'], onSuccess: () => { setPanel(null); onClearReply?.() } })
  const like = useAction(() => api.post(`${base}/stickers`, { sticker: 'thumbs_up', ...(replyId ? { reply_to_id: replyId } : {}) }), { invalidate: ['/chat'], onSuccess: () => onClearReply?.() })
  const busy = sendText.isPending || sendSticker.isPending || like.isPending
  const uploading = files.some((f) => f.status === 'uploading') || !!voiceUp?.progress
  const error = problem || sendText.error?.message || sendSticker.error?.message || like.error?.message || voice.error

  const update = (id, patch) => setFiles((fs) => fs.map((f) => (f.id === id ? { ...f, ...patch } : f)))
  const addFiles = (list) => {
    const bad = []
    const ok = []
    for (const f of list) {
      const why = checkFile(f)
      if (why) { bad.push(why); continue }
      const kind = kindOfFile(f.name)
      ok.push({ id: nextId++, file: f, kind, preview: kind === 'photo' ? URL.createObjectURL(f) : null, progress: 0, status: 'ready', error: null })
    }
    setProblem(bad.length ? bad.join(' ') : null)
    if (ok.length) { setFiles((fs) => [...fs, ...ok].slice(0, 10)); setPanel(null) }
  }
  const dropFile = (id) => setFiles((fs) => { const f = fs.find((x) => x.id === id); if (f?.preview) URL.revokeObjectURL(f.preview); return fs.filter((x) => x.id !== id) })
  useEffect(() => () => { Object.values(aborts.current).forEach((a) => a.abort()); voiceAbort.current?.abort() }, [])
  useEffect(() => { setText(''); setFiles([]); setPanel(null); setProblem(null); voice.discard() }, [convId]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (incoming?.length) { addFiles(incoming); onIncomingHandled?.() } }, [incoming]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (editing) { setText(editing.body || ''); area.current?.focus() } }, [editing])
  useEffect(() => { if (replyTo) area.current?.focus() }, [replyTo])
  useEffect(() => { const el = area.current; if (el) { el.style.height = 'auto'; el.style.height = `${Math.min(el.scrollHeight, 120)}px` } }, [text])   // grows with the text, up to about five lines

  const sendFiles = async () => {
    setProblem(null)
    const queue = files.filter((f) => f.status === 'ready' || f.status === 'error')
    let first = true
    for (const f of queue) {
      const ctl = new AbortController()
      aborts.current[f.id] = ctl
      update(f.id, { status: 'uploading', progress: 0, error: null })
      try {
        await uploadWithProgress(`${base}/attachments`, f.file, { caption: first ? text.trim() : '', ...(first && replyId ? { reply_to_id: String(replyId) } : {}) }, { signal: ctl.signal, onProgress: (p) => update(f.id, { progress: p }) })
        dropFile(f.id)
        if (first) { setText(''); onClearReply?.() }
        first = false
        refresh()
      } catch (e) {
        if (e.name === 'AbortError') { update(f.id, { status: 'ready', progress: 0 }); return }
        update(f.id, { status: 'error', error: e.message })
        return
      } finally { delete aborts.current[f.id] }
    }
  }
  const sendVoice = async () => {
    const res = voice.result
    if (!res) return
    const ctl = new AbortController()
    voiceAbort.current = ctl
    setVoiceUp({ progress: 1, error: null })
    try {
      await uploadWithProgress(`${base}/attachments`, res.file, { voice: 'true', duration: String(res.seconds), caption: '', ...(replyId ? { reply_to_id: String(replyId) } : {}) }, { signal: ctl.signal, onProgress: (p) => setVoiceUp({ progress: Math.max(1, p), error: null }) })
      setVoiceUp(null); voice.discard(); onClearReply?.(); refresh()
    } catch (e) {
      setVoiceUp(e.name === 'AbortError' ? null : { progress: 0, error: e.message })
    }
  }

  const addEmoji = (e) => {
    recordEmoji(me, e)
    const { value, cursor } = insertAtCursor(area.current, text, e)
    setText(value)
    area.current?.focus() // straight back to typing; the caret is placed after the emoji once React has rendered the new text
    requestAnimationFrame(() => area.current?.setSelectionRange?.(cursor, cursor))
  }
  const submit = (e) => {
    e?.preventDefault()
    if (busy || uploading || disabled) return
    if (editing) {  // saving: files queued earlier are not part of an edit, and an unchanged text is simply closed
      if (text.trim() === (editing.body || '').trim()) { setText(''); onClearEdit(); return }
      sendText.mutate(text)
    } else if (files.length) sendFiles()
    else if (text.trim()) sendText.mutate(text)
  }
  const choose = () => (ev) => { const list = [...(ev.target.files || [])]; ev.target.value = ''; if (list.length) addFiles(list) }
  const canSend = editing ? (editing.kind !== 'text' || !!text.trim()) : files.length > 0 || !!text.trim()
  const round = 'inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-[#00a884] text-white shadow-sm transition-colors hover:bg-[#008f6f] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#008069] disabled:opacity-50'

  if (voice.state === 'recording' || voice.state === 'paused') {
    return (
      <div className={cx(barCls, 'flex items-center gap-2')} role="group" aria-label="Recording a voice message">
        <IconButton icon="trash" label="Cancel" onClick={voice.discard} className="text-[#c0392b]" />
        <span className={cx('h-3 w-3 shrink-0 rounded-full bg-[#ea0038]', voice.state === 'recording' && 'animate-pulse')} aria-hidden />
        <span className="font-mono text-base tabular-nums text-[#111b21]" aria-label="Recording length">{fmtDuration(voice.seconds)}</span>
        <span className="flex-1 truncate text-sm text-[#54656f]" role="status">{voice.state === 'paused' ? 'Paused' : 'Recording…'}</span>
        {voice.canPause && (voice.state === 'recording' ? <IconButton icon="pause" label="Pause" onClick={voice.pause} /> : <IconButton icon="mic" label="Resume" onClick={voice.resume} className="text-[#ea0038]" />)}
        <button type="button" aria-label="Stop" title="Stop recording" onClick={voice.stop} className={round}><span aria-hidden className="h-3.5 w-3.5 rounded-[3px] bg-white" /></button>
      </div>
    )
  }
  if (voice.state === 'preview' && voice.result) {
    return (
      <div className={barCls} role="group" aria-label="Voice message ready to send">
        {voiceUp?.error && <div className="mb-2"><Alert>{voiceUp.error}</Alert></div>}
        <div className="flex items-center gap-2">
          {voiceUp?.progress ? null : <IconButton icon="trash" label="Delete" onClick={voice.discard} className="text-[#c0392b]" />}
          <div className="min-w-0 flex-1 rounded-full bg-white px-3 py-1.5"><AudioPlayer src={voice.result.url} name="Voice message" duration={voice.result.seconds} voice label="Voice message preview" /></div>
          {voiceUp?.progress ? (
            <>
              <span role="progressbar" aria-label="Uploading voice message" aria-valuenow={voiceUp.progress} aria-valuemin={0} aria-valuemax={100} className="text-sm text-[#54656f]">Sending {voiceUp.progress}%</span>
              <button type="button" className="px-2 text-sm font-medium text-[#008069] hover:underline" onClick={() => voiceAbort.current?.abort()}>Cancel upload</button>
            </>
          ) : <button type="button" aria-label={voiceUp?.error ? 'Retry' : 'Send voice message'} title={voiceUp?.error ? 'Retry' : 'Send voice message'} onClick={sendVoice} className={round}><Icon name="send" size={22} /></button>}
        </div>
      </div>
    )
  }
  return (
    <form onSubmit={submit} className={cx(barCls, 'relative')}>
      {error && <div className="mb-2"><Alert>{error}</Alert></div>}
      {replyTo && !editing && (
        <div className="mb-2 flex items-center gap-2 rounded-lg border-l-4 border-[#06cf9c] bg-white px-3 py-1.5 text-sm shadow-sm" role="status">
          <span className="min-w-0 flex-1"><span className="block text-xs font-medium text-[#008069]">Replying to {replyTo.sender_name}</span><span className="block truncate text-[#54656f]">{replyTo.preview}</span></span>
          <IconButton icon="close" label="Cancel reply" size={18} className="h-8 w-8" onClick={onClearReply} />
        </div>
      )}
      {editing && (
        <div className="mb-2 flex items-center gap-2 rounded-lg border-l-4 border-[#f5a623] bg-white px-3 py-1.5 text-sm shadow-sm" role="status">
          <span className="min-w-0 flex-1"><span className="block font-medium text-[#111b21]">Editing message</span>{editing.body && <span className="block truncate text-[#54656f]">{editing.body}</span>}</span>
          <IconButton icon="close" label="Cancel edit" size={18} className="h-8 w-8" onClick={() => { setText(''); onClearEdit() }} />
        </div>
      )}
      {files.length > 0 && <ul className="mb-2 space-y-1.5" aria-label="Attachments to send">{files.map((f) => <Chip key={f.id} f={f} onRemove={dropFile} onCancel={(id) => aborts.current[id]?.abort()} onRetry={(id) => update(id, { status: 'ready', error: null })} />)}</ul>}
      {panel === 'emoji' && <EmojiPicker userId={me} onPick={addEmoji} onClose={() => setPanel(null)} />}
      {panel === 'sticker' && <StickerPicker userId={me} onPick={(id) => { recordSticker(me, id); sendSticker.mutate(id) }} onClose={() => setPanel(null)} />}
      {panel === 'attach' && (
        <div role="menu" aria-label="Attach" className="absolute bottom-full left-12 z-30 mb-2 w-56 rounded-xl bg-white py-2 text-sm shadow-xl ring-1 ring-black/5">
          {[['photo', 'image', 'Photo', 'bg-[#bf59cf]'], ['document', 'doc', 'Document or PDF', 'bg-[#5157ae]'], ['audio', 'music', 'Music or audio', 'bg-[#f5a623]']].map(([k, icon, label, bg]) => (
            <button key={k} type="button" role="menuitem" className="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-black/5" onClick={() => inputs[k].current?.click()}>
              <span aria-hidden className={cx('flex h-9 w-9 items-center justify-center rounded-full text-white', bg)}><Icon name={icon} size={20} /></span>{label}
            </button>
          ))}
          <p className="border-t border-black/5 px-4 pt-2 text-xs text-[#54656f]">You can also drag files into the chat. Up to 25 MB each.</p>
        </div>
      )}
      {Object.keys(inputs).map((k) => <input key={k} ref={inputs[k]} type="file" multiple={k !== 'audio'} className="sr-only" tabIndex={-1} aria-label={`Choose ${k}`} accept={ACCEPT[k]} onChange={choose()} />)}
      <div className="flex items-end gap-1">
        <IconButton icon="smile" label="Emoji" expanded={panel === 'emoji'} disabled={disabled} onClick={() => setPanel(panel === 'emoji' ? null : 'emoji')} />
        <IconButton icon="attach" label="Attach a file" haspopup="menu" expanded={panel === 'attach'} disabled={disabled || !!editing} onClick={() => setPanel(panel === 'attach' ? null : 'attach')} />
        <IconButton icon="sticker" label="Stickers" expanded={panel === 'sticker'} disabled={disabled || !!editing} onClick={() => setPanel(panel === 'sticker' ? null : 'sticker')} />
        <textarea ref={area} aria-label="Message" rows={1} disabled={disabled} maxLength={4000} value={text} placeholder={editing ? (editing.kind === 'text' ? 'Edit your message' : 'Edit the caption') : files.length ? 'Add a caption (optional)…' : 'Type a message'}
          className="max-h-[120px] min-h-[42px] flex-1 resize-none rounded-lg border-0 bg-white px-3 py-2.5 text-[15px] leading-5 text-[#111b21] placeholder:text-[#54656f] focus:outline focus:outline-2 focus:outline-[#00a884] disabled:bg-[#e9edef]"
          onChange={(e) => { setText(e.target.value); if (e.target.value && !editing) sendTyping(convId) }}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(e) } if (e.key === 'Escape') { setPanel(null); if (editing) { setText(''); onClearEdit() } else onClearReply?.() } }} />
        {canSend ? (
          <button type="submit" aria-label={editing ? 'Save' : 'Send'} title={editing ? 'Save' : 'Send'} disabled={disabled || busy || uploading} className={round}>
            <Icon name={editing ? 'check' : 'send'} size={22} />
          </button>
        ) : (
          <>
            <IconButton icon="like" label="Send a like" disabled={disabled || busy} onClick={() => like.mutate()} />
            {voice.supported && <button type="button" aria-label="Record a voice message" title="Record a voice message" disabled={disabled} onClick={voice.start} className={round}><Icon name="mic" size={22} /></button>}
          </>
        )}
      </div>
    </form>
  )
}
