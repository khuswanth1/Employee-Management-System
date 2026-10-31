import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Avatar, Badge, Button, EmptyState, ErrorState, Field, Input, Modal, PageHeader, PageLoader, SearchInput, StatusBadge, Table } from '../../components/ui'
import { api, fieldErrors } from '../../lib/api'
import { fmtDateTime } from '../../lib/format'
import { useAction, useApi } from '../../lib/hooks'
import { useAuth } from '../auth/AuthContext'
import RecipientPicker, { emptyPick, pickBody, pickCount } from './RecipientPicker'

function CallDialog({ open, onClose, onCall, busy }) {
  const [q, setQ] = useState('')
  const [who, setWho] = useState(null)
  const { data } = useApi('/chat/users', null, { enabled: open })
  const list = (data?.items || []).filter((u) => u.full_name.toLowerCase().includes(q.trim().toLowerCase()))
  return (
    <Modal open={open} onClose={onClose} title="Call someone"
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={busy} disabled={!who} onClick={() => onCall(who)}>Call</Button></>}>
      <p className="mb-3 text-sm text-slate-600">A private call between you and one person. Nobody else can join it.</p>
      <SearchInput value={q} onChange={setQ} placeholder="Search people" />
      <ul className="mt-2 max-h-64 overflow-y-auto rounded-lg border border-slate-200 p-1" role="radiogroup" aria-label="Person to call">
        {list.length === 0 ? <li className="px-2 py-3 text-sm text-slate-500">{data ? 'Nobody matches.' : 'Loading…'}</li> : list.map((u) => (
          <li key={u.id}>
            <label className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-slate-50">
              <input type="radio" name="call-target" className="h-4 w-4" checked={who === u.id} onChange={() => setWho(u.id)} />
              <Avatar name={u.full_name} size={6} userId={u.id} v={u.avatar_v} />
              <span className="min-w-0"><span className="block truncate">{u.full_name}</span>{u.designation && <span className="block truncate text-xs text-slate-500">{u.designation}</span>}</span>
            </label>
          </li>
        ))}
      </ul>
    </Modal>
  )
}

export function Participants({ m, meId }) {
  const others = m.participants.filter((p) => p.id !== meId)
  if (!others.length) return <span className="text-slate-500">Only you</span>
  const names = others.map((p) => p.name)
  return <span title={names.join(', ')}>{names.length <= 2 ? names.join(', ') : `${names.slice(0, 2).join(', ')} +${names.length - 2}`}</span>
}

export default function MeetingsPage() {
  const nav = useNavigate()
  const { user } = useAuth()
  const [open, setOpen] = useState(false)
  const [calling, setCalling] = useState(false)
  const [f, setF] = useState({ title: '', scheduled_at: '' })
  const [pick, setPick] = useState(emptyPick())
  const { data, isLoading, error, refetch } = useApi('/meetings')
  const reset = () => { setOpen(false); setF({ title: '', scheduled_at: '' }); setPick(emptyPick()) }
  const create = useAction((body) => api.post('/meetings', body), {
    invalidate: ['/meetings'], success: 'Meeting created',
    onSuccess: (m, body) => { reset(); if (!body.scheduled_at) nav(`/meetings/${m.room_id}`) },
  })
  const call = useAction((user_id) => api.post('/meetings/call', { user_id }), {
    invalidate: ['/meetings'], success: 'Calling…',
    onSuccess: (m) => { setCalling(false); nav(`/meetings/${m.room_id}`) },
  })
  const fe = fieldErrors(create.error)
  const submit = () => create.mutate({ ...pickBody(pick), title: f.title, scheduled_at: f.scheduled_at ? new Date(f.scheduled_at).toISOString() : null })
  const secure = window.isSecureContext

  return (
    <>
      <PageHeader title="Meetings" description="Private audio, video and screen sharing: only you and the people you invite can join"
        actions={<>
          <Button variant="secondary" onClick={() => setCalling(true)}>Call someone</Button>
          <Button variant="secondary" onClick={() => setOpen(true)}>New meeting</Button>
          <Button onClick={() => create.mutate({ title: `${user.full_name}'s meeting`, scheduled_at: null, invitee_ids: [], team_ids: [], group_ids: [] })}>Start instant meeting</Button>
        </>} />
      {!secure && <div role="alert" className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">Camera and screen sharing need HTTPS (or localhost). Open this site over a secure connection.</div>}
      {isLoading ? <PageLoader /> : error ? <ErrorState error={error} onRetry={refetch} /> : (
        <Table caption="Meetings" rows={data.items} empty={<EmptyState title="No upcoming meetings" description="Call someone, or start a meeting and choose who to invite." />}
          columns={[
            { key: 'title', header: 'Meeting', render: (m) => <span className="font-medium text-slate-900">{m.title}{m.kind === 'call' && <span className="ml-2"><Badge tone="blue">Call</Badge></span>}</span> },
            { key: 'with', header: 'With', render: (m) => <Participants m={m} meId={user.id} /> },
            { key: 'when', header: 'When', render: (m) => (m.scheduled_at ? fmtDateTime(m.scheduled_at) : 'On demand') },
            { key: 'status', header: 'Status', render: (m) => <StatusBadge value={m.status} /> },
            { key: 'join', header: '', render: (m) => <Link className="font-medium text-brand-700 hover:underline" to={`/meetings/${m.room_id}`}>Join</Link> },
          ]} />
      )}
      <CallDialog open={calling} onClose={() => setCalling(false)} onCall={(id) => call.mutate(id)} busy={call.isPending} />
      <Modal open={open} onClose={reset} title="New meeting"
        footer={<><Button variant="secondary" onClick={reset}>Cancel</Button><Button loading={create.isPending} disabled={f.title.trim().length < 2} onClick={submit}>{f.scheduled_at ? 'Schedule' : 'Start now'}</Button></>}>
        <div className="space-y-4">
          <Field label="Title" required error={fe.title}><Input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></Field>
          <Field label="Date & time" hint="Leave empty to start right away"><Input type="datetime-local" value={f.scheduled_at} onChange={(e) => setF({ ...f, scheduled_at: e.target.value })} /></Field>
          <div>
            <p className="mb-1 text-sm font-medium text-slate-700">Invite</p>
            <p className="mb-2 text-xs text-slate-500">Pick one person, several people, or a team or chat group. Only they will be able to see and join it.{pickCount(pick) === 0 ? '' : ' They are notified with the link.'}</p>
            <RecipientPicker value={pick} onChange={setPick} enabled={open} />
          </div>
        </div>
      </Modal>
    </>
  )
}
