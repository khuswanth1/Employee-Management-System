import { useEffect, useState } from 'react'
import { Alert, Avatar, Badge, Button, Card, ConfirmDialog, EmptyState, ErrorState, Field, FormSection, Input, Modal, PageHeader, Select, TableSkeleton } from '../../components/ui'
import { api, fieldErrors } from '../../lib/api'
import { ROLE_LABEL } from '../../lib/format'
import { useAction, useApi } from '../../lib/hooks'
import { useAuth } from '../auth/AuthContext'

const DAYS = [['mon', 'Mon'], ['tue', 'Tue'], ['wed', 'Wed'], ['thu', 'Thu'], ['fri', 'Fri'], ['sat', 'Sat'], ['sun', 'Sun']]
const blank = { name: '', code: '', address: '', city: '', state: '', country: '', postal_code: '', contact_email: '', contact_phone: '', timezone: '', working_days: [], manager_id: '', hr_representative_id: '' }
const toForm = (b) => Object.fromEntries(Object.keys(blank).map((k) => [k, b[k] ?? blank[k]]))
const TIMEZONES = (() => { try { return Intl.supportedValuesOf('timeZone') } catch { return [] } })()

function BranchModal({ open, onClose, branch }) {
  const isNew = !branch
  const [f, setF] = useState(blank)
  const { data: detail } = useApi(`/branches/${branch?.id}`, null, { enabled: open && !isNew })
  useEffect(() => { if (open) setF(branch ? toForm(branch) : blank) }, [open, branch])
  const people = detail?.members || []
  const save = useAction(() => {
    const t = (v) => (v.trim() ? v.trim() : null)
    const body = { name: f.name.trim(), code: f.code.trim(), address: t(f.address), city: t(f.city), state: t(f.state), country: t(f.country), postal_code: t(f.postal_code),
      contact_email: t(f.contact_email), contact_phone: t(f.contact_phone), timezone: t(f.timezone), working_days: f.working_days.length ? f.working_days : null }
    if (!isNew) { body.manager_id = f.manager_id ? Number(f.manager_id) : null; body.hr_representative_id = f.hr_representative_id ? Number(f.hr_representative_id) : null }
    return isNew ? api.post('/branches', body) : api.patch(`/branches/${branch.id}`, body)
  }, { invalidate: ['/branches'], success: isNew ? 'Branch created' : 'Branch updated', onSuccess: onClose })
  const fe = fieldErrors(save.error)
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }))
  const toggleDay = (d) => setF((s) => ({ ...s, working_days: s.working_days.includes(d) ? s.working_days.filter((x) => x !== d) : [...s.working_days, d] }))
  return (
    <Modal open={open} onClose={onClose} wide title={isNew ? 'New branch' : `Edit ${branch.name}`}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={save.isPending} onClick={() => save.mutate()}>{isNew ? 'Create branch' : 'Save changes'}</Button></>}>
      <form className="space-y-5" onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
        <datalist id="tz-list">{TIMEZONES.map((z) => <option key={z} value={z} />)}</datalist>
        {save.error && !Object.keys(fe).length && <Alert>{save.error.message}</Alert>}
        <FormSection title="General information">
          <Field label="Branch name" required error={fe.name}><Input value={f.name} onChange={set('name')} required minLength={2} maxLength={120} /></Field>
          <Field label="Branch code" required error={fe.code} hint="Short unique code, e.g. NYC"><Input value={f.code} onChange={set('code')} required minLength={2} maxLength={20} /></Field>
        </FormSection>
        <FormSection title="Address">
          <div className="sm:col-span-2"><Field label="Street address" error={fe.address}><Input value={f.address} onChange={set('address')} maxLength={300} /></Field></div>
          <Field label="City / location" error={fe.city}><Input value={f.city} onChange={set('city')} maxLength={100} /></Field>
          <Field label="State / region" error={fe.state}><Input value={f.state} onChange={set('state')} maxLength={100} /></Field>
          <Field label="Country" error={fe.country}><Input value={f.country} onChange={set('country')} maxLength={100} /></Field>
          <Field label="Postal code" error={fe.postal_code}><Input value={f.postal_code} onChange={set('postal_code')} maxLength={20} /></Field>
        </FormSection>
        <FormSection title="Contact">
          <Field label="Contact email" error={fe.contact_email}><Input type="email" value={f.contact_email} onChange={set('contact_email')} maxLength={255} /></Field>
          <Field label="Contact number" error={fe.contact_phone}><Input type="tel" value={f.contact_phone} onChange={set('contact_phone')} /></Field>
        </FormSection>
        <FormSection title="Schedule" description="Overrides the company defaults for people in this branch.">
          <Field label="Timezone" error={fe.timezone} hint="IANA name, e.g. Asia/Kolkata"><Input list="tz-list" value={f.timezone} onChange={set('timezone')} maxLength={64} /></Field>
          <fieldset><legend className="mb-1 block text-sm font-medium text-slate-700">Working days</legend>
            <div className="flex flex-wrap gap-2">{DAYS.map(([k, l]) => (
              <label key={k} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm"><input type="checkbox" className="accent-brand-600" checked={f.working_days.includes(k)} onChange={() => toggleDay(k)} />{l}</label>))}</div>
            {fe.working_days && <p role="alert" className="mt-1 text-xs text-red-600">{fe.working_days}</p>}
          </fieldset>
        </FormSection>
        {!isNew && (
          <FormSection title="Leadership" description="Choose from people already assigned to this branch.">
            <Field label="Branch manager" error={fe.manager_id}><Select value={f.manager_id} onChange={set('manager_id')}><option value="">None</option>{people.filter((u) => ['manager', 'hr'].includes(u.role)).map((u) => <option key={u.id} value={u.id}>{u.full_name} ({ROLE_LABEL[u.role]})</option>)}</Select></Field>
            <Field label="HR representative" error={fe.hr_representative_id}><Select value={f.hr_representative_id} onChange={set('hr_representative_id')}><option value="">None</option>{people.filter((u) => u.role === 'hr').map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}</Select></Field>
          </FormSection>
        )}
      </form>
    </Modal>
  )
}

function Members({ branch, canEdit }) {
  const { data: detail, isLoading } = useApi(`/branches/${branch.id}`)
  const { data: dir } = useApi('/employees/directory', null, { enabled: canEdit })
  const [pick, setPick] = useState('')
  const inv = { invalidate: ['/branches', '/employees'] }
  const assign = useAction((id) => api.post(`/branches/${branch.id}/members`, { user_ids: [Number(id)] }), { ...inv, success: 'Assigned to branch', onSuccess: () => setPick('') })
  const remove = useAction((id) => api.del(`/branches/${branch.id}/members/${id}`), { ...inv, success: 'Removed from branch' })
  const members = detail?.members || []
  const inBranch = new Set(members.map((m) => m.id))
  const candidates = (dir?.items || []).filter((u) => !inBranch.has(u.id) && ['employee', 'manager', 'hr'].includes(u.role))
  return (
    <div className="mt-3 border-t border-slate-100 pt-3">
      {isLoading ? <p className="text-sm text-slate-500">Loading…</p> : !members.length ? <p className="text-sm text-slate-500">Nobody is assigned to this branch yet.</p> : (
        <ul className="divide-y divide-slate-100 text-sm">
          {members.map((m) => (
            <li key={m.id} className="flex items-center gap-3 py-2">
              <Avatar name={m.full_name} size={7} userId={m.id} v={m.avatar_v} />
              <span className="min-w-0 flex-1"><span className="block truncate font-medium text-slate-900">{m.full_name}</span><span className="block truncate text-xs text-slate-500">{ROLE_LABEL[m.role]}{m.designation ? ` · ${m.designation}` : ''}</span></span>
              {canEdit && <button type="button" className="text-red-600 hover:underline" aria-label={`Remove ${m.full_name} from ${branch.name}`} onClick={() => remove.mutate(m.id)}>Remove</button>}
            </li>
          ))}
        </ul>
      )}
      {canEdit && branch.is_active && (
        <form className="mt-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); if (pick) assign.mutate(pick) }}>
          <Select aria-label={`Assign someone to ${branch.name}`} value={pick} onChange={(e) => setPick(e.target.value)}>
            <option value="">Assign employee, manager or HR…</option>
            {candidates.map((u) => <option key={u.id} value={u.id}>{u.full_name} ({ROLE_LABEL[u.role]}{u.branch_id ? ', moves branch' : ''})</option>)}
          </Select>
          <Button type="submit" disabled={!pick} loading={assign.isPending}>Assign</Button>
        </form>
      )}
    </div>
  )
}

export default function BranchesPage() {
  const { role } = useAuth()
  const canEdit = role === 'founder'
  const { data, isLoading, error, refetch } = useApi('/branches')
  const [editing, setEditing] = useState(null) // branch | 'new' | null
  const [deleting, setDeleting] = useState(null)
  const [open, setOpen] = useState(null)
  const toggle = useAction((b) => api.patch(`/branches/${b.id}`, { is_active: !b.is_active }), { invalidate: ['/branches'], success: 'Branch updated' })
  const del = useAction(() => api.del(`/branches/${deleting.id}`), { invalidate: ['/branches'], success: 'Branch deleted', onSuccess: () => setDeleting(null) })

  return (
    <>
      <PageHeader title="Branches & locations" description={canEdit ? 'Create branches and assign employees, HR and managers to them' : 'Company branches and who works in them'}
        actions={canEdit && <Button onClick={() => setEditing('new')}>New branch</Button>} />
      {isLoading ? <TableSkeleton rows={3} cols={3} /> : error ? <ErrorState error={error} onRetry={refetch} /> : !data.items.length ? (
        <EmptyState title="No branches yet" description={canEdit ? 'Create your first branch to organise people by location.' : 'The founder has not created any branches.'} action={canEdit && <Button onClick={() => setEditing('new')}>New branch</Button>} />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2 [&>*]:min-w-0">
          {data.items.map((b) => (
            <Card key={b.id} title={<span className="flex items-center gap-2">{b.name} <Badge tone="indigo">{b.code}</Badge>{!b.is_active && <Badge tone="gray">Inactive</Badge>}</span>}
              action={canEdit && <div className="flex gap-2">
                <Button size="sm" variant="secondary" onClick={() => setEditing(b)} aria-label={`Edit ${b.name}`}>Edit</Button>
                <Button size="sm" variant="secondary" loading={toggle.isPending} onClick={() => toggle.mutate(b)} aria-label={`${b.is_active ? 'Deactivate' : 'Activate'} ${b.name}`}>{b.is_active ? 'Deactivate' : 'Activate'}</Button>
                <Button size="sm" variant="danger" onClick={() => setDeleting(b)} aria-label={`Delete ${b.name}`}>Delete</Button></div>}>
              <p className="text-sm text-slate-600">{[b.address, b.city, b.state, b.country, b.postal_code].filter(Boolean).join(', ') || 'No address'}</p>
              {(b.manager_name || b.hr_representative_name) && <p className="mt-1 text-xs text-slate-600">{b.manager_name && <>Manager: <span className="font-medium">{b.manager_name}</span></>}{b.manager_name && b.hr_representative_name && ' · '}{b.hr_representative_name && <>HR: <span className="font-medium">{b.hr_representative_name}</span></>}</p>}
              {(b.timezone || b.working_days) && <p className="mt-1 text-xs text-slate-500">{[b.timezone, b.working_days && b.working_days.map((d) => d[0].toUpperCase() + d.slice(1)).join(' ')].filter(Boolean).join(' · ')}</p>}
              {b.counts && <p className="mt-2 text-xs text-slate-500">{b.counts.employee} employees · {b.counts.manager} managers · {b.counts.hr} HR</p>}
              <button type="button" className="mt-3 text-sm font-medium text-brand-700 hover:underline" aria-expanded={open === b.id} onClick={() => setOpen(open === b.id ? null : b.id)}>
                {open === b.id ? 'Hide people' : 'Show people'}
              </button>
              {open === b.id && <Members branch={b} canEdit={canEdit} />}
            </Card>
          ))}
        </div>
      )}
      <BranchModal open={!!editing} onClose={() => setEditing(null)} branch={editing === 'new' ? null : editing} />
      <ConfirmDialog open={!!deleting} danger title="Delete branch" confirmLabel="Delete branch" loading={del.isPending} onClose={() => setDeleting(null)} onConfirm={() => del.mutate()}
        message={`Delete "${deleting?.name}"? A branch with people assigned cannot be deleted; deactivate it instead.`} />
    </>
  )
}
