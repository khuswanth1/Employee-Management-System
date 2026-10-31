import { useEffect, useState } from 'react'
import { Alert, Avatar, Badge, Button, Card, ConfirmDialog, EmptyState, ErrorState, Field, Input, Modal, PageHeader, PageLoader, Textarea } from '../../components/ui'
import { api, fieldErrors } from '../../lib/api'
import { fmtDate } from '../../lib/format'
import { useAction, useApi } from '../../lib/hooks'

const blank = { full_name: '', email: '', password: '', designation: '', phone: '', responsibilities: '', term_start: '', permissions: ['analytics.view', 'reports.view'] }

function MemberModal({ open, onClose, member }) {
  const isNew = !member
  const { data: catalog } = useApi('/board/permissions-catalog', null, { enabled: open })
  const [f, setF] = useState(blank)
  useEffect(() => {
    if (open) setF(member ? { ...blank, full_name: member.full_name, designation: member.designation || '', phone: member.phone || '', responsibilities: member.responsibilities || '', term_start: member.term_start || '', permissions: member.permissions || [] } : blank)
  }, [open, member])
  const save = useAction(() => {
    const shared = { designation: f.designation || null, phone: f.phone || null, responsibilities: f.responsibilities || null, term_start: f.term_start || null, permissions: f.permissions }
    return isNew ? api.post('/board/members', { ...shared, full_name: f.full_name, email: f.email, password: f.password }) : api.patch(`/board/members/${member.id}`, { ...shared, full_name: f.full_name })
  }, { invalidate: ['/board/members'], success: isNew ? 'Board member added' : 'Board member updated', onSuccess: onClose })
  const fe = fieldErrors(save.error)
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }))
  const toggle = (k) => setF((s) => ({ ...s, permissions: s.permissions.includes(k) ? s.permissions.filter((x) => x !== k) : [...s.permissions, k] }))
  return (
    <Modal open={open} onClose={onClose} wide title={isNew ? 'Add board member' : 'Edit board member'}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={save.isPending} onClick={() => save.mutate()}>{isNew ? 'Add board member' : 'Save changes'}</Button></>}>
      <form className="grid gap-4 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
        {save.error && !Object.keys(fe).length && <div className="sm:col-span-2"><Alert>{save.error.message}</Alert></div>}
        <Field label="Full name" required error={fe.full_name}><Input value={f.full_name} onChange={set('full_name')} required minLength={2} /></Field>
        <Field label="Designation" error={fe.designation}><Input value={f.designation} onChange={set('designation')} placeholder="e.g. Chair, Audit committee" /></Field>
        {isNew && <>
          <Field label="Email" required error={fe.email}><Input type="email" value={f.email} onChange={set('email')} required autoComplete="off" /></Field>
          <Field label="Temporary password" required error={fe.password} hint="Min 10 chars with upper/lower case and a digit"><Input type="password" value={f.password} onChange={set('password')} required autoComplete="new-password" /></Field>
        </>}
        <Field label="Phone"><Input type="tel" value={f.phone} onChange={set('phone')} /></Field>
        <Field label="Term start"><Input type="date" value={f.term_start} onChange={set('term_start')} /></Field>
        <div className="sm:col-span-2"><Field label="Responsibilities" error={fe.responsibilities}><Textarea value={f.responsibilities} onChange={set('responsibilities')} maxLength={4000} /></Field></div>
        <fieldset className="sm:col-span-2">
          <legend className="mb-2 text-sm font-medium text-slate-700">Access</legend>
          <ul className="space-y-2">{catalog?.items.map((p) => (
            <li key={p.key}><label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-0.5 h-4 w-4 accent-brand-600" checked={f.permissions.includes(p.key)} onChange={() => toggle(p.key)} />
              <span><span className="font-medium">{p.key}</span><span className="block text-xs text-slate-500">{p.description}</span></span></label></li>))}</ul>
          <p className="mt-2 text-xs text-slate-500">Board members only ever see aggregated figures. Individual employee records stay hidden.</p>
        </fieldset>
      </form>
    </Modal>
  )
}

export default function BoardMembersPage() {
  const { data, isLoading, error, refetch } = useApi('/board/members')
  const [editing, setEditing] = useState(null) // member | 'new' | null
  const [deleting, setDeleting] = useState(null)
  const toggle = useAction((m) => api.patch(`/board/members/${m.id}`, { is_active: !m.is_active }), { invalidate: ['/board/members'], success: 'Board member updated' })
  const del = useAction(() => api.del(`/board/members/${deleting.id}`), { invalidate: ['/board/members'], success: 'Board member deleted', onSuccess: () => setDeleting(null) })
  return (
    <>
      <PageHeader title="Board members" description="Profiles, responsibilities and what each member may see" actions={<Button onClick={() => setEditing('new')}>Add board member</Button>} />
      {isLoading ? <PageLoader /> : error ? <ErrorState error={error} onRetry={refetch} /> : !data.items.length ? (
        <EmptyState title="No board members yet" description="Add board members to give them company-level analytics." action={<Button onClick={() => setEditing('new')}>Add board member</Button>} />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {data.items.map((m) => (
            <Card key={m.id} title={<span className="flex items-center gap-3"><Avatar name={m.full_name} userId={m.id} v={m.avatar_v} />{m.full_name}{!m.is_active && <Badge tone="gray">Inactive</Badge>}</span>}
              action={<div className="flex gap-2">
                <Button size="sm" variant="secondary" onClick={() => setEditing(m)} aria-label={`Edit ${m.full_name}`}>Edit</Button>
                <Button size="sm" variant="secondary" loading={toggle.isPending} onClick={() => toggle.mutate(m)} aria-label={`${m.is_active ? 'Deactivate' : 'Activate'} ${m.full_name}`}>{m.is_active ? 'Deactivate' : 'Activate'}</Button>
                <Button size="sm" variant="danger" onClick={() => setDeleting(m)} aria-label={`Delete ${m.full_name}`}>Delete</Button></div>}>
              <p className="text-sm font-medium text-slate-800">{m.designation || 'Board member'} <span className="font-normal text-slate-500">· {m.email}</span></p>
              <p className="mt-1 text-xs text-slate-500">ID {m.employee_code} · Term from {fmtDate(m.term_start)}</p>
              {m.responsibilities && <p className="mt-2 text-sm text-slate-600">{m.responsibilities}</p>}
              <p className="mt-3 flex flex-wrap gap-1.5">{m.permissions.length ? m.permissions.map((p) => <Badge key={p} tone="indigo">{p}</Badge>) : <Badge tone="gray">No analytics access</Badge>}</p>
            </Card>
          ))}
        </div>
      )}
      <MemberModal open={!!editing} onClose={() => setEditing(null)} member={editing === 'new' ? null : editing} />
      <ConfirmDialog open={!!deleting} danger title="Delete board member" confirmLabel="Delete" loading={del.isPending} onClose={() => setDeleting(null)} onConfirm={() => del.mutate()}
        message={`Delete ${deleting?.full_name}? If they already have activity on record, deactivate them instead.`} />
    </>
  )
}
