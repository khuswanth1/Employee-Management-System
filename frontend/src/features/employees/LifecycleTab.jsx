import { useState } from 'react'
import { Alert, Badge, Button, Card, EmptyState, ErrorState, Field, Input, Modal, PageLoader, Select, Textarea } from '../../components/ui'
import { api, fieldErrors } from '../../lib/api'
import { fmtDate } from '../../lib/format'
import { useAction, useApi } from '../../lib/hooks'

export const EVENT = {
  joined: ['Joined', 'green'], activated: ['Activated', 'green'], probation_set: ['Probation', 'gray'], confirmed: ['Confirmed', 'green'], promoted: ['Promotion', 'blue'],
  role_changed: ['Role changed', 'blue'], department_changed: ['Department', 'gray'], branch_changed: ['Branch', 'gray'], manager_changed: ['Manager', 'gray'],
  suspended: ['Suspended', 'red'], reinstated: ['Reinstated', 'green'], resignation_submitted: ['Resignation', 'amber'], resignation_withdrawn: ['Resignation withdrawn', 'gray'],
  offboarded: ['Left', 'red'], exit_cleared: ['Exit cleared', 'gray'], reactivated: ['Returned', 'green'],
}

/** One line describing what changed, from the stored before/after values. */
export function describe(e) {
  const name = (v) => v?.name || v?.designation || v?.role || '—'
  switch (e.kind) {
    case 'promoted': return `${name(e.from)}${e.from?.job_level ? ` (${e.from.job_level})` : ''} → ${e.to?.designation || '—'}${e.to?.job_level ? ` (${e.to.job_level})` : ''}`
    case 'role_changed': return `${e.from?.role} → ${e.to?.role}`
    case 'department_changed': case 'branch_changed': case 'manager_changed': return `${e.from?.name || 'none'} → ${e.to?.name || 'none'}`
    case 'probation_set': return `ends ${e.to?.end_date ? fmtDate(e.to.end_date) : '—'}${e.from?.end_date ? ` (was ${fmtDate(e.from.end_date)})` : ''}`
    case 'confirmed': return e.to?.confirmation_date ? `confirmed on ${fmtDate(e.to.confirmation_date)}` : ''
    case 'suspended': return e.to?.until ? `until ${fmtDate(e.to.until)}` : 'no end date'
    case 'resignation_submitted': return `last working day ${e.to?.last_working_date ? fmtDate(e.to.last_working_date) : '—'}${e.to?.shorter_than_notice ? ' (shorter than the notice period)' : ''}`
    default: return ''
  }
}

function ActionDialog({ title, cta, fields, submit, onClose, children, danger }) {
  const [f, setF] = useState(Object.fromEntries(fields.map((x) => [x.key, x.initial ?? ''])))
  const run = useAction(() => submit(f), { invalidate: ['/employees', '/lifecycle'], success: `${title}: done`, onSuccess: onClose })
  const fe = fieldErrors(run.error)
  const ok = fields.every((x) => !x.required || String(f[x.key]).trim() !== '')
  return (
    <Modal open onClose={onClose} title={title} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button variant={danger ? 'danger' : 'primary'} loading={run.isPending} disabled={!ok} onClick={() => run.mutate()}>{cta}</Button></>}>
      <div className="space-y-4">
        {run.error && !Object.keys(fe).length && <Alert>{run.error.message}</Alert>}
        {children}
        {fields.map((x) => (
          <Field key={x.key} label={x.label} required={x.required} hint={x.hint} error={fe[x.key]}>
            {x.type === 'select' ? <Select value={f[x.key]} onChange={(e) => setF((s) => ({ ...s, [x.key]: e.target.value }))}>{x.options}</Select>
              : x.type === 'textarea' ? <Textarea value={f[x.key]} onChange={(e) => setF((s) => ({ ...s, [x.key]: e.target.value }))} maxLength={1000} />
                : <Input type={x.type || 'text'} value={f[x.key]} max={x.max} onChange={(e) => setF((s) => ({ ...s, [x.key]: e.target.value }))} />}
          </Field>
        ))}
      </div>
    </Modal>
  )
}

/** History of an employee's employment, with the lifecycle actions for the people who administer it. */
export default function LifecycleTab({ id, user }) {
  const { data, isLoading, error, refetch } = useApi(`/employees/${id}/lifecycle`)
  const { data: depts } = useApi('/departments')
  const { data: dir } = useApi('/employees/directory')
  const [dlg, setDlg] = useState(null)
  if (isLoading) return <PageLoader />
  if (error) return <ErrorState error={error} onRetry={refetch} />
  const base = `/employees/${id}/lifecycle`
  const today = new Date().toISOString().slice(0, 10)
  const st = data.state
  const employed = !['offboarded', 'pending_approval'].includes(user.status)
  const opt = (rows, label) => <><option value="">{label}</option>{(rows?.items || []).map((r) => <option key={r.id} value={r.id}>{r.name || r.full_name}</option>)}</>
  const dialogs = {
    promotion: <ActionDialog title="Promotion" cta="Record" onClose={() => setDlg(null)} submit={(f) => api.post(`${base}/promotion`, { designation: f.designation || null, job_level: f.job_level || null, effective_date: f.effective_date || null, note: f.note || null })}
      fields={[{ key: 'designation', label: 'New title', initial: user.designation || '' }, { key: 'job_level', label: 'Job level' }, { key: 'effective_date', label: 'Effective from', type: 'date', initial: today, max: today }, { key: 'note', label: 'Note', type: 'textarea' }]} />,
    transfer: <ActionDialog title="Transfer" cta="Move" onClose={() => setDlg(null)} submit={(f) => api.post(`${base}/transfer`, { department_id: f.department_id ? Number(f.department_id) : null, manager_id: f.manager_id && f.manager_id !== 'none' ? Number(f.manager_id) : null, clear_manager: f.manager_id === 'none', effective_date: f.effective_date || null, note: f.note || null })}
      fields={[{ key: 'department_id', label: 'New department', type: 'select', options: opt(depts, 'No change') }, { key: 'manager_id', label: 'New reporting manager', type: 'select', options: <><option value="">No change</option><option value="none">No manager</option>{(dir?.items || []).filter((p) => p.id !== Number(id) && ['manager', 'hr', 'founder'].includes(p.role)).map((p) => <option key={p.id} value={p.id}>{p.full_name}</option>)}</> },
        { key: 'effective_date', label: 'Effective from', type: 'date', initial: today, max: today }, { key: 'note', label: 'Note', type: 'textarea' }]}>
      <p className="text-sm text-slate-600">Branch moves are made by a founder from the employee record. Changes apply now; the date is kept in the history.</p></ActionDialog>,
    probation: <ActionDialog title="Probation" cta="Save" onClose={() => setDlg(null)} submit={(f) => api.post(`${base}/probation`, { end_date: f.end_date, note: f.note || null })}
      fields={[{ key: 'end_date', label: 'Probation ends', type: 'date', required: true, initial: st.probation_end_date || '' }, { key: 'note', label: 'Note', type: 'textarea' }]} />,
    confirm: <ActionDialog title="Confirm employment" cta="Confirm" onClose={() => setDlg(null)} submit={(f) => api.post(`${base}/confirmation`, { effective_date: f.effective_date || null, note: f.note || null })}
      fields={[{ key: 'effective_date', label: 'Confirmed on', type: 'date', initial: today, max: today }, { key: 'note', label: 'Note', type: 'textarea' }]} />,
    suspend: <ActionDialog title="Suspend" cta="Suspend" danger onClose={() => setDlg(null)} submit={(f) => api.post(`${base}/suspend`, { reason: f.reason, until: f.until || null })}
      fields={[{ key: 'reason', label: 'Reason', type: 'textarea', required: true, hint: 'Only HR and founders can read this' }, { key: 'until', label: 'Until (optional)', type: 'date' }]}>
      <Alert tone="amber">They are signed out immediately and cannot sign in until reinstated. Their record, work and team stay as they are.</Alert></ActionDialog>,
    reinstate: <ActionDialog title="Reinstate" cta="Reinstate" onClose={() => setDlg(null)} submit={(f) => api.post(`${base}/reinstate`, { note: f.note || null })} fields={[{ key: 'note', label: 'Note', type: 'textarea' }]} />,
    resign: <ActionDialog title="Record resignation" cta="Record" onClose={() => setDlg(null)} submit={(f) => api.post(`${base}/resignation`, { last_working_date: f.last_working_date, reason: f.reason || null })}
      fields={[{ key: 'last_working_date', label: 'Last working day', type: 'date', required: true }, { key: 'reason', label: 'Reason', type: 'textarea' }]} />,
    withdraw: <ActionDialog title="Withdraw resignation" cta="Withdraw" onClose={() => setDlg(null)} submit={(f) => api.post(`${base}/resignation/withdraw`, { note: f.note || null })} fields={[{ key: 'note', label: 'Note', type: 'textarea' }]} />,
    reactivate: <ActionDialog title="Bring back" cta="Reactivate" onClose={() => setDlg(null)} submit={(f) => api.post(`${base}/reactivate`, { hire_date: f.hire_date || null, note: f.note || null })}
      fields={[{ key: 'hire_date', label: 'Joining date this time', type: 'date', initial: today, max: today }, { key: 'note', label: 'Note', type: 'textarea' }]}>
      <p className="text-sm text-slate-600">Their old history stays. They sign in with their existing password (reset it if needed).</p></ActionDialog>,
  }
  return (
    <div className="space-y-6">
      {data.can_manage && (
        <Card title="Actions">
          <div className="flex flex-wrap gap-2">
            {employed && <Button size="sm" variant="secondary" onClick={() => setDlg('promotion')}>Promote</Button>}
            {employed && <Button size="sm" variant="secondary" onClick={() => setDlg('transfer')}>Transfer</Button>}
            {employed && !st.confirmation_date && <Button size="sm" variant="secondary" onClick={() => setDlg('probation')}>{st.probation_end_date ? 'Extend probation' : 'Set probation'}</Button>}
            {employed && !st.confirmation_date && <Button size="sm" variant="secondary" onClick={() => setDlg('confirm')}>Confirm</Button>}
            {['active', 'onboarding'].includes(user.status) && <Button size="sm" variant="secondary" onClick={() => setDlg('suspend')}>Suspend</Button>}
            {user.status === 'suspended' && <Button size="sm" onClick={() => setDlg('reinstate')}>Reinstate</Button>}
            {employed && !st.resigned && <Button size="sm" variant="secondary" onClick={() => setDlg('resign')}>Record resignation</Button>}
            {st.resigned && <Button size="sm" variant="secondary" onClick={() => setDlg('withdraw')}>Withdraw resignation</Button>}
            {user.status === 'offboarded' && <Button size="sm" onClick={() => setDlg('reactivate')}>Bring back</Button>}
          </div>
          {data.exit_clearance && <p className="mt-3 text-sm text-slate-600">Exit clearance: {data.exit_clearance.done} of {data.exit_clearance.total} items done{data.exit_clearance.cleared ? ' · cleared' : ''}.</p>}
        </Card>
      )}
      <div className="flex flex-wrap gap-4 text-sm text-slate-600">
        <span>Probation: {st.confirmation_date ? <Badge tone="green">confirmed {fmtDate(st.confirmation_date)}</Badge> : st.probation_end_date ? `ends ${fmtDate(st.probation_end_date)}` : '—'}</span>
        {st.last_working_date && <span>Last working day: <strong>{fmtDate(st.last_working_date)}</strong></span>}
      </div>
      <Card title="Employment history" pad={false}>
        {data.items.length ? (
          <ol className="divide-y divide-slate-100" aria-label="Employment history">
            {data.items.map((e) => (
              <li key={e.id} className="flex flex-wrap items-start gap-3 px-5 py-3">
                <span className="w-28 shrink-0 text-sm text-slate-500">{fmtDate(e.effective_date)}</span>
                <div className="min-w-0 flex-1"><p className="text-sm"><Badge tone={EVENT[e.kind]?.[1] || 'gray'}>{EVENT[e.kind]?.[0] || e.kind}</Badge> <span className="ml-1">{describe(e)}</span></p>
                  {e.note && <p className="mt-0.5 text-sm text-slate-600">{e.note}</p>}{e.by && <p className="text-xs text-slate-400">by {e.by}</p>}</div>
              </li>
            ))}
          </ol>
        ) : <EmptyState title="No history yet" />}
      </Card>
      {dlg && dialogs[dlg]}
    </div>
  )
}
