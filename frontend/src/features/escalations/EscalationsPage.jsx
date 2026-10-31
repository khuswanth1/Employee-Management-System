import { useState } from 'react'
import { Alert, Badge, Button, Card, EmptyState, ErrorState, Field, Input, Modal, PageHeader, PageLoader, Select, Tabs, Textarea } from '../../components/ui'
import { api, fieldErrors } from '../../lib/api'
import { fmtDateTime } from '../../lib/format'
import { useAction, useApi } from '../../lib/hooks'
import { useAuth } from '../auth/AuthContext'

const TONE = { open: 'amber', escalated: 'red', resolved: 'green' }
const LEVEL = { manager: 'With your manager', hr: 'With HR', founder: 'With the founder' }

function NewEscalation({ open, onClose, role }) {
  const [f, setF] = useState({ subject: '', body: '', route: role === 'manager' ? 'hr' : 'manager' })
  const create = useAction(() => api.post('/escalations', f), { invalidate: ['/escalations'], success: 'Escalation sent', onSuccess: () => { onClose(); setF({ ...f, subject: '', body: '' }) } })
  const fe = fieldErrors(create.error)
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }))
  return (
    <Modal open={open} onClose={onClose} title="Raise an escalation"
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={create.isPending} onClick={() => create.mutate()}>Send</Button></>}>
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); create.mutate() }}>
        {create.error && !Object.keys(fe).length && <Alert>{create.error.message}</Alert>}
        <p className="text-xs text-slate-500">Escalations go to your branch manager or HR first. They can pass it on to the founder.</p>
        {role !== 'manager' && (
          <Field label="Send to"><Select value={f.route} onChange={set('route')}><option value="manager">My manager</option><option value="hr">HR</option></Select></Field>
        )}
        <Field label="Subject" required error={fe.subject}><Input value={f.subject} onChange={set('subject')} required minLength={3} maxLength={200} /></Field>
        <Field label="What is the issue?" required error={fe.body}><Textarea rows={5} value={f.body} onChange={set('body')} required minLength={3} maxLength={4000} /></Field>
      </form>
    </Modal>
  )
}

function ActionModal({ open, onClose, item, mode }) {
  const [text, setText] = useState('')
  const isEsc = mode === 'escalate'
  const act = useAction(() => api.post(`/escalations/${item.id}/${isEsc ? 'escalate' : 'resolve'}`, isEsc ? { note: text } : { resolution: text }),
    { invalidate: ['/escalations', '/notifications'], success: isEsc ? 'Escalated to the founder' : 'Marked as resolved', onSuccess: () => { setText(''); onClose() } })
  if (!item) return null
  return (
    <Modal open={open} onClose={onClose} title={isEsc ? 'Escalate to the founder' : 'Resolve escalation'}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={act.isPending} disabled={text.trim().length < 3} onClick={() => act.mutate()}>{isEsc ? 'Escalate' : 'Resolve'}</Button></>}>
      {act.error && <div className="mb-3"><Alert>{act.error.message}</Alert></div>}
      <p className="mb-3 text-sm text-slate-600">{item.subject}</p>
      <Field label={isEsc ? 'Why does the founder need to step in?' : 'Resolution'} required><Textarea rows={4} value={text} onChange={(e) => setText(e.target.value)} maxLength={4000} /></Field>
    </Modal>
  )
}

function Item({ e, box, onAct }) {
  return (
    <Card title={<span className="flex flex-wrap items-center gap-2">{e.subject}<Badge tone={TONE[e.status]}>{e.status}</Badge><Badge tone="gray">{LEVEL[e.level]}</Badge></span>}>
      <p className="whitespace-pre-wrap text-sm text-slate-700">{e.body}</p>
      <p className="mt-2 text-xs text-slate-500">{box === 'inbox' ? `From ${e.created_by_name} · ` : ''}{fmtDateTime(e.created_at)}{e.assignee_name ? ` · Assigned to ${e.assignee_name}` : ''}</p>
      {e.escalation_note && <p className="mt-2 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-900"><b>Escalated by {e.escalated_by_name}:</b> {e.escalation_note}</p>}
      {e.resolution && <p className="mt-2 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-900"><b>Resolved by {e.resolved_by_name}:</b> {e.resolution}</p>}
      {e.can_act && (
        <div className="mt-3 flex gap-2">
          <Button size="sm" onClick={() => onAct(e, 'resolve')}>Resolve</Button>
          {e.level !== 'founder' && <Button size="sm" variant="secondary" onClick={() => onAct(e, 'escalate')}>Escalate to founder</Button>}
        </div>
      )}
    </Card>
  )
}

export default function EscalationsPage() {
  const { role } = useAuth()
  const handler = role !== 'employee'
  const [tab, setTab] = useState(handler ? 'inbox' : 'mine')
  const [creating, setCreating] = useState(false)
  const [action, setAction] = useState(null)
  const { data, isLoading, error, refetch } = useApi('/escalations', { box: tab, page_size: 50 })
  const canCreate = role === 'employee' || role === 'manager'
  return (
    <>
      <PageHeader title="Escalations" description="Raise issues up the chain: manager or HR first, then the founder"
        actions={canCreate && <Button onClick={() => setCreating(true)}>New escalation</Button>} />
      {handler && canCreate && <Tabs value={tab} onChange={setTab} tabs={[{ id: 'inbox', label: 'Inbox' }, { id: 'mine', label: 'Raised by me' }]} />}
      {handler && !canCreate && <Tabs value={tab} onChange={setTab} tabs={[{ id: 'inbox', label: 'Inbox' }]} />}
      {isLoading ? <PageLoader /> : error ? <ErrorState error={error} onRetry={refetch} /> : !data.items.length ? (
        <EmptyState title={tab === 'inbox' ? 'Nothing waiting for you' : 'No escalations yet'} description={tab === 'mine' ? 'Use New escalation to raise something with your manager or HR.' : undefined} />
      ) : (
        <div className="space-y-4">{data.items.map((e) => <Item key={e.id} e={e} box={tab} onAct={(item, mode) => setAction({ item, mode })} />)}</div>
      )}
      <NewEscalation open={creating} onClose={() => setCreating(false)} role={role} />
      <ActionModal open={!!action} onClose={() => setAction(null)} item={action?.item} mode={action?.mode} />
    </>
  )
}
