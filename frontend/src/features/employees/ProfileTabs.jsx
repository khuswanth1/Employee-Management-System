import { useEffect, useRef, useState } from 'react'
import { Alert, Badge, Button, Card, EmptyState, Field, FormSection, Input, PageLoader, Select, Textarea } from '../../components/ui'
import TagInput from '../../components/TagInput'
import { api, download, fieldErrors } from '../../lib/api'
import { fmtDate, label } from '../../lib/format'
import { useAction, useApi } from '../../lib/hooks'

export const EMPLOYMENT_TYPES = ['full_time', 'part_time', 'contract', 'intern', 'consultant']
export const GENDERS = ['female', 'male', 'non_binary', 'prefer_not_to_say']
export const DOC_TYPES = ['resume', 'offer_letter', 'employment_agreement', 'identity', 'qualification', 'certification', 'other']

const blank = (v) => (v === '' || v === undefined ? null : v)

/** Fields of one profile section. Only changed values are sent, so an untouched section never overwrites newer data. */
function useProfileForm(id, p, fields, listFields = []) {
  const toForm = (src) => Object.fromEntries(fields.map((k) => [k, listFields.includes(k) ? (src?.[k] || []) : (src?.[k] ?? '')]))
  const [f, setF] = useState(() => toForm(p))
  useEffect(() => setF(toForm(p)), [p]) // eslint-disable-line react-hooks/exhaustive-deps
  const base = toForm(p)
  const changed = fields.filter((k) => JSON.stringify(f[k]) !== JSON.stringify(base[k]))
  const save = useAction(() => {
    const body = {}
    changed.forEach((k) => { body[k] = listFields.includes(k) ? f[k] : blank(k === 'notice_period_days' && f[k] !== '' ? Number(f[k]) : f[k]) })
    return api.patch(`/employees/${id}/profile`, body)
  }, { invalidate: [`/employees/${id}/profile`, `/employees/${id}`], success: 'Saved' })
  // A fast double click lands before React re-renders the disabled button, so guard with a ref: one save at a time.
  const busy = useRef(false)
  const submit = () => {
    if (busy.current) return
    busy.current = true
    save.mutate(undefined, { onSettled: () => { busy.current = false } })
  }
  return { f, submit, set: (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value })), setKey: (k, v) => setF((s) => ({ ...s, [k]: v })),
    dirty: changed.length > 0, reset: () => setF(base), save, fe: fieldErrors(save.error) }
}

function SaveBar({ form, disabled }) {
  if (disabled) return null
  return (
    <div className="flex items-center gap-2 pt-1">
      <Button type="submit" loading={form.save.isPending} disabled={!form.dirty}>Save changes</Button>
      <Button type="button" variant="secondary" disabled={!form.dirty || form.save.isPending} onClick={form.reset}>Discard</Button>
      {form.dirty && <span className="text-xs text-slate-500">Unsaved changes</span>}
    </div>
  )
}

const FormError = ({ form }) => (form.save.error && !Object.keys(form.fe).length ? <Alert>{form.save.error.message}</Alert> : null)

const EMPLOYMENT = ['employment_type', 'employment_category', 'job_level', 'probation_end_date', 'confirmation_date', 'notice_period_days', 'last_working_date', 'tags']
const IDENTITY = ['middle_name', 'display_name', 'skills', 'certifications']

export function EmploymentTab({ id, profile, hireDate, canEditAll, canEditOwn }) {
  const employment = useProfileForm(id, profile, EMPLOYMENT, ['tags'])
  const identity = useProfileForm(id, profile, IDENTITY, ['skills', 'certifications'])
  const locked = !canEditAll
  const lockedIdentity = !(canEditAll || canEditOwn)
  return (
    <div className="space-y-6">
      <Card title="Employment details">
        <form className="space-y-5" onSubmit={(e) => { e.preventDefault(); employment.submit() }}>
          <FormError form={employment} />
          <FormSection title="Contract" description="How this person is engaged.">
            <Field label="Employment type" error={employment.fe.employment_type}>
              <Select value={employment.f.employment_type} onChange={employment.set('employment_type')} disabled={locked}><option value="">Not set</option>{EMPLOYMENT_TYPES.map((t) => <option key={t} value={t}>{label(t)}</option>)}</Select>
            </Field>
            <Field label="Employment category" error={employment.fe.employment_category} hint="For example Permanent, Fixed term or Probationary"><Input maxLength={60} value={employment.f.employment_category} onChange={employment.set('employment_category')} disabled={locked} /></Field>
            <Field label="Job level" error={employment.fe.job_level} hint="For example L3 or Senior"><Input maxLength={40} value={employment.f.job_level} onChange={employment.set('job_level')} disabled={locked} /></Field>
            <Field label="Notice period (days)" error={employment.fe.notice_period_days} hint="0 to 365"><Input type="number" inputMode="numeric" min={0} max={365} value={employment.f.notice_period_days} onChange={employment.set('notice_period_days')} disabled={locked} /></Field>
          </FormSection>
          <FormSection title="Key dates" description={`Joined ${fmtDate(hireDate)}. Dates cannot be earlier than the joining date.`}>
            <Field label="Probation end date" error={employment.fe.probation_end_date}><Input type="date" min={hireDate || undefined} value={employment.f.probation_end_date} onChange={employment.set('probation_end_date')} disabled={locked} /></Field>
            <Field label="Confirmation date" error={employment.fe.confirmation_date}><Input type="date" min={employment.f.probation_end_date || hireDate || undefined} value={employment.f.confirmation_date} onChange={employment.set('confirmation_date')} disabled={locked} /></Field>
            <Field label="Last working date" error={employment.fe.last_working_date} hint="Only when the person is leaving"><Input type="date" min={hireDate || undefined} value={employment.f.last_working_date} onChange={employment.set('last_working_date')} disabled={locked} /></Field>
          </FormSection>
          <FormSection title="Tags" cols={1}>
            <Field label="Employee tags" hint="Internal labels such as remote or mentor. Press Enter to add."><TagInput label="Tags" max={30} value={employment.f.tags} onChange={(v) => employment.setKey('tags', v)} disabled={locked} /></Field>
          </FormSection>
          <SaveBar form={employment} disabled={locked} />
        </form>
      </Card>
      <Card title="Skills and identity">
        <form className="space-y-5" onSubmit={(e) => { e.preventDefault(); identity.submit() }}>
          <FormError form={identity} />
          <FormSection title="Names">
            <Field label="Middle name" error={identity.fe.middle_name}><Input maxLength={100} value={identity.f.middle_name} onChange={identity.set('middle_name')} disabled={lockedIdentity} /></Field>
            <Field label="Display name" error={identity.fe.display_name} hint="Shown instead of the legal name where space is short"><Input maxLength={100} value={identity.f.display_name} onChange={identity.set('display_name')} disabled={lockedIdentity} /></Field>
          </FormSection>
          <FormSection title="Capabilities" cols={1}>
            <Field label="Skills" error={identity.fe.skills}><TagInput label="Skills" value={identity.f.skills} onChange={(v) => identity.setKey('skills', v)} disabled={lockedIdentity} /></Field>
            <Field label="Professional certifications" error={identity.fe.certifications}><TagInput label="Certifications" value={identity.f.certifications} onChange={(v) => identity.setKey('certifications', v)} disabled={lockedIdentity} /></Field>
          </FormSection>
          <SaveBar form={identity} disabled={lockedIdentity} />
        </form>
      </Card>
    </div>
  )
}

const PERSONAL = ['personal_email', 'date_of_birth', 'gender', 'address', 'emergency_contact_name', 'emergency_contact_relationship', 'emergency_contact_phone', 'emergency_contact_address']

/** Restricted data. The server only sends these fields to the person and to HR/founders; this tab is never rendered otherwise. */
export function PersonalTab({ id, profile, canEdit }) {
  const form = useProfileForm(id, profile, PERSONAL)
  const lock = !canEdit
  const maxDob = new Date(Date.now() - 14 * 365.25 * 864e5).toISOString().slice(0, 10)
  return (
    <Card title="Personal and emergency contact">
      <form className="space-y-5" onSubmit={(e) => { e.preventDefault(); form.submit() }}>
        <Alert tone="amber">Restricted: visible only to this person, HR and founders. Changes are audit-logged by field name, never by value.</Alert>
        <FormError form={form} />
        <FormSection title="Personal">
          <Field label="Personal email" error={form.fe.personal_email}><Input type="email" autoComplete="off" value={form.f.personal_email} onChange={form.set('personal_email')} disabled={lock} /></Field>
          <Field label="Date of birth" error={form.fe.date_of_birth}><Input type="date" max={maxDob} value={form.f.date_of_birth} onChange={form.set('date_of_birth')} disabled={lock} /></Field>
          <Field label="Gender" error={form.fe.gender} hint="Optional"><Select value={form.f.gender} onChange={form.set('gender')} disabled={lock}><option value="">Not provided</option>{GENDERS.map((g) => <option key={g} value={g}>{label(g)}</option>)}</Select></Field>
          <div className="sm:col-span-2"><Field label="Home address" error={form.fe.address}><Textarea rows={2} maxLength={300} value={form.f.address} onChange={form.set('address')} disabled={lock} /></Field></div>
        </FormSection>
        <FormSection title="Emergency contact">
          <Field label="Name" error={form.fe.emergency_contact_name}><Input maxLength={120} value={form.f.emergency_contact_name} onChange={form.set('emergency_contact_name')} disabled={lock} /></Field>
          <Field label="Relationship" error={form.fe.emergency_contact_relationship}><Input maxLength={60} value={form.f.emergency_contact_relationship} onChange={form.set('emergency_contact_relationship')} disabled={lock} /></Field>
          <Field label="Phone" error={form.fe.emergency_contact_phone} hint="Digits, spaces and + ( ) - only"><Input type="tel" value={form.f.emergency_contact_phone} onChange={form.set('emergency_contact_phone')} disabled={lock} /></Field>
          <Field label="Address (optional)" error={form.fe.emergency_contact_address}><Input maxLength={300} value={form.f.emergency_contact_address} onChange={form.set('emergency_contact_address')} disabled={lock} /></Field>
        </FormSection>
        <SaveBar form={form} disabled={lock} />
      </form>
    </Card>
  )
}

const VERIFY_TONE = { pending: 'amber', verified: 'green', rejected: 'red' }

export function DocumentsTab({ id, canUpload, canAdmin, isSelf }) {
  const { data: docs, isLoading } = useApi(`/employees/${id}/documents`)
  const [docType, setDocType] = useState('resume')
  const [expiry, setExpiry] = useState('')
  const [file, setFile] = useState(null)
  const inv = [`/employees/${id}/documents`]
  const upload = useAction(() => api.upload(`/employees/${id}/documents`, file, { doc_type: docType, ...(expiry ? { expiry_date: expiry } : {}) }),
    { invalidate: inv, success: 'Document uploaded', onSuccess: () => { setFile(null); setExpiry('') } })
  const verify = useAction(({ d, status }) => api.patch(`/documents/${d.id}/verification`, { status }), { invalidate: inv, success: 'Verification updated' })
  const remove = useAction((d) => api.del(`/documents/${d.id}`), { invalidate: inv, success: 'Document removed' })
  if (isLoading) return <PageLoader />
  return (
    <div className="space-y-6">
      {canUpload && (
        <Card title="Add a document">
          <form className="grid gap-4 sm:grid-cols-4" onSubmit={(e) => { e.preventDefault(); if (file) upload.mutate() }}>
            <Field label="Type" required><Select value={docType} onChange={(e) => setDocType(e.target.value)}>{DOC_TYPES.map((t) => <option key={t} value={t}>{label(t)}</option>)}</Select></Field>
            <Field label="Expiry date" hint="Only for documents that expire"><Input type="date" value={expiry} min={new Date().toISOString().slice(0, 10)} onChange={(e) => setExpiry(e.target.value)} /></Field>
            <Field label="File" required hint="PDF, image or Office file, up to 10 MB">
              <Input type="file" onChange={(e) => setFile(e.target.files?.[0] || null)} />
            </Field>
            <div className="flex items-end"><Button type="submit" loading={upload.isPending} disabled={!file}>Upload</Button></div>
          </form>
        </Card>
      )}
      <Card title="Documents" pad={false}>
        {!docs?.items.length ? <div className="p-5"><EmptyState title="No documents" description="Uploaded documents appear here with their verification status." /></div> : (
          <ul className="divide-y divide-slate-100">
            {docs.items.map((d) => (
              <li key={d.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 text-sm">
                <div className="min-w-0">
                  <p className="truncate font-medium text-slate-900">{d.name}</p>
                  <p className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                    <span>{label(d.doc_type)}</span><span>Uploaded {fmtDate(d.created_at)}</span>
                    {d.expiry_date && <span>Expires {fmtDate(d.expiry_date)}</span>}
                    {d.is_expired ? <Badge tone="red">Expired</Badge> : d.expires_soon ? <Badge tone="amber">Expires soon</Badge> : null}
                  </p>
                </div>
                <div className="flex shrink-0 flex-wrap items-center gap-3">
                  <Badge tone={VERIFY_TONE[d.verification_status]}>{label(d.verification_status)}</Badge>
                  {canAdmin && !isSelf && <Select aria-label={`Verification for ${d.name}`} className="w-32 py-1 text-xs" value={d.verification_status} onChange={(e) => verify.mutate({ d, status: e.target.value })}>
                    {['pending', 'verified', 'rejected'].map((s) => <option key={s} value={s}>{label(s)}</option>)}</Select>}
                  <button className="text-brand-700 hover:underline" onClick={() => download(`/documents/${d.id}/download`, d.name)}>Download</button>
                  {canAdmin && <button className="text-red-600 hover:underline" onClick={() => window.confirm(`Remove "${d.name}"?`) && remove.mutate(d)}>Remove</button>}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}
