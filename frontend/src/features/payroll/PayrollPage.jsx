import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Alert, Badge, Button, Card, EmptyState, ErrorState, Field, Input, Modal, PageHeader, PageLoader, Pagination, Select, Table, Tabs, Textarea } from '../../components/ui'
import { api, fieldErrors } from '../../lib/api'
import { fmtDate } from '../../lib/format'
import { useAction, useApi } from '../../lib/hooks'
import { useAuth } from '../auth/AuthContext'
import { CALC, fmtMoney, MONTHS, monthName } from './money'

export const RUN_TONE = { draft: 'gray', processed: 'amber', approved: 'blue', paid: 'green', cancelled: 'red' }
export const RUN_LABEL = { draft: 'Draft', processed: 'Awaiting approval', approved: 'Approved', paid: 'Paid', cancelled: 'Cancelled' }

// ------------------------------------------------------------------------------- runs

function NewRun({ onClose }) {
  const now = new Date()
  const last = new Date(now.getFullYear(), now.getMonth() - 1, 1)
  const [f, setF] = useState({ year: last.getFullYear(), month: last.getMonth() + 1, note: '' })
  const create = useAction(() => api.post('/payroll/runs', { year: Number(f.year), month: Number(f.month), note: f.note || null }), { invalidate: ['/payroll'], success: 'Payroll calculated', onSuccess: onClose })
  const fe = fieldErrors(create.error)
  return (
    <Modal open onClose={onClose} title="New payroll run" footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={create.isPending} onClick={() => create.mutate()}>Calculate</Button></>}>
      <div className="space-y-4">
        {create.error && !Object.keys(fe).length && <Alert>{create.error.message}</Alert>}
        <p className="text-sm text-slate-600">Calculates a draft payslip for everyone who has a pay structure, from the month&apos;s leave, the company calendar and your payroll settings. Nothing is visible to employees until the run is approved.</p>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Month"><Select value={f.month} onChange={(e) => setF((s) => ({ ...s, month: e.target.value }))}>{MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}</Select></Field>
          <Field label="Year" error={fe.year}><Input type="number" value={f.year} onChange={(e) => setF((s) => ({ ...s, year: e.target.value }))} /></Field>
        </div>
        <Field label="Note"><Input value={f.note} onChange={(e) => setF((s) => ({ ...s, note: e.target.value }))} maxLength={300} /></Field>
      </div>
    </Modal>
  )
}

function Runs() {
  const { data, isLoading, error, refetch } = useApi('/payroll/runs')
  const [adding, setAdding] = useState(false)
  if (isLoading) return <PageLoader />
  if (error) return <ErrorState error={error} onRetry={refetch} />
  return (
    <>
      <div className="mb-3 flex justify-end"><Button onClick={() => setAdding(true)}>New payroll run</Button></div>
      <Table caption="Payroll runs" rows={data.items} empty={<EmptyState title="No payroll runs yet" description="Set up pay structures first, then calculate a month." />}
        columns={[
          { key: 'period', header: 'Month', render: (r) => <Link className="font-medium text-brand-700 hover:underline" to={`/payroll/runs/${r.id}`}>{monthName(r.year, r.month)}</Link> },
          { key: 'status', header: 'Status', render: (r) => <Badge tone={RUN_TONE[r.status]}>{RUN_LABEL[r.status]}</Badge> },
          { key: 'n', header: 'Payslips', render: (r) => r.totals.payslips },
          { key: 'gross', header: 'Gross', render: (r) => fmtMoney(r.totals.gross, r.policy?.currency) },
          { key: 'net', header: 'Net', render: (r) => fmtMoney(r.totals.net, r.policy?.currency) },
          { key: 'by', header: 'Submitted by', render: (r) => r.processed_by || '—' },
          { key: 'ap', header: 'Approved by', render: (r) => r.approved_by || '—' },
        ]} />
      {adding && <NewRun onClose={() => setAdding(false)} />}
    </>
  )
}

// ------------------------------------------------------------------------- components

const blankComp = { code: '', name: '', kind: 'earning', calc: 'fixed', default_value: 0, prorate: true, cap: '', note: '', is_active: true }

function ComponentDialog({ comp, canEdit, onClose }) {
  const [f, setF] = useState(comp ? { ...blankComp, ...comp, cap: comp.cap ?? '', note: comp.note || '' } : blankComp)
  const body = () => ({ ...f, code: f.code.trim(), name: f.name.trim(), default_value: Number(f.default_value || 0), cap: f.cap === '' ? null : Number(f.cap), note: f.note || null })
  const save = useAction(() => (comp ? api.patch(`/payroll/components/${comp.id}`, body()) : api.post('/payroll/components', body())),
    { invalidate: ['/payroll/components'], success: comp ? 'Component updated' : 'Component added', onSuccess: onClose })
  const fe = fieldErrors(save.error)
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }))
  const percent = f.calc !== 'fixed'
  return (
    <Modal open onClose={onClose} wide title={comp ? `Edit ${comp.name}` : 'New pay component'}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button>{canEdit && <Button loading={save.isPending} disabled={f.code.trim().length < 2 || f.name.trim().length < 2} onClick={() => save.mutate()}>Save</Button>}</>}>
      <div className="grid gap-4 sm:grid-cols-2">
        {save.error && !Object.keys(fe).length && <div className="sm:col-span-2"><Alert>{save.error.message}</Alert></div>}
        <div className="sm:col-span-2"><Alert tone="amber">Rates and rules (tax, social security, pension and so on) are not built in. Enter them from your jurisdiction&apos;s current official rules and note the source, and have them verified before relying on payroll.</Alert></div>
        <Field label="Code" required error={fe.code} hint="Letters, digits, - and _"><Input value={f.code} onChange={set('code')} maxLength={24} disabled={!!comp} /></Field>
        <Field label="Name" required error={fe.name}><Input value={f.name} onChange={set('name')} maxLength={80} /></Field>
        <Field label="Type"><Select value={f.kind} onChange={(e) => setF((s) => ({ ...s, kind: e.target.value, calc: e.target.value === 'earning' && s.calc === 'percent_of_gross' ? 'fixed' : s.calc }))} disabled={!!comp}><option value="earning">Earning (adds to pay)</option><option value="deduction">Deduction (taken from pay)</option></Select></Field>
        <Field label="Calculated as"><Select value={f.calc} onChange={set('calc')} disabled={!!comp}><option value="fixed">Fixed amount</option><option value="percent_of_basic">Percentage of basic</option>{f.kind === 'deduction' && <option value="percent_of_gross">Percentage of gross pay</option>}</Select></Field>
        <Field label={percent ? 'Default percentage' : 'Default amount'} error={fe.default_value}><Input type="number" min="0" step="0.01" value={f.default_value} onChange={set('default_value')} /></Field>
        <Field label="Upper limit per month" hint="Blank = none" error={fe.cap}><Input type="number" min="0" step="0.01" value={f.cap} onChange={set('cap')} /></Field>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.prorate} onChange={(e) => setF((s) => ({ ...s, prorate: e.target.checked }))} disabled={f.calc !== 'fixed'} /> Reduce in proportion to unpaid days (fixed amounts)</label>
        {comp && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.is_active} onChange={(e) => setF((s) => ({ ...s, is_active: e.target.checked }))} /> Active</label>}
        <div className="sm:col-span-2"><Field label="Note / source of the rule"><Textarea value={f.note} onChange={set('note')} maxLength={300} /></Field></div>
      </div>
    </Modal>
  )
}

function Components() {
  const { data, isLoading, error, refetch } = useApi('/payroll/components')
  const { user, role } = useAuth()
  const canEdit = role === 'founder' || (role === 'hr' && !user.branch_id)
  const [dlg, setDlg] = useState(null)
  if (isLoading) return <PageLoader />
  if (error) return <ErrorState error={error} onRetry={refetch} />
  return (
    <>
      {canEdit && <div className="mb-3 flex justify-end"><Button onClick={() => setDlg({})}>New component</Button></div>}
      <Table caption="Pay components" rows={data.items} empty={<EmptyState title="No components" description="Add allowances and deductions, then put them in people's pay structures." />}
        columns={[
          { key: 'name', header: 'Component', render: (c) => <>{c.name} <span className="text-xs text-slate-500">{c.code}</span>{!c.is_active && <> <Badge>inactive</Badge></>}</> },
          { key: 'kind', header: 'Type', render: (c) => <Badge tone={c.kind === 'earning' ? 'green' : 'amber'}>{c.kind}</Badge> },
          { key: 'calc', header: 'Calculated as', render: (c) => `${CALC[c.calc]}${c.calc === 'fixed' ? '' : ` (${c.default_value}%)`}` },
          { key: 'cap', header: 'Limit', render: (c) => (c.cap != null ? c.cap : '—') },
          { key: 'a', header: '', render: (c) => <Button size="sm" variant="ghost" onClick={() => setDlg({ comp: c })}>{canEdit ? 'Edit' : 'View'}</Button> },
        ]} />
      {dlg && <ComponentDialog comp={dlg.comp} canEdit={canEdit} onClose={() => setDlg(null)} />}
    </>
  )
}

// --------------------------------------------------------------------- pay structures

function StructureDialog({ person, onClose }) {
  const { data: hist } = useApi(`/payroll/compensation/${person.user_id}`)
  const { data: comps } = useApi('/payroll/components')
  const { data: settings } = useApi('/admin/settings', undefined, { retry: false })
  const cur = hist?.items?.[0]
  const active = (comps?.items || []).filter((c) => c.is_active)
  const [f, setF] = useState(null)
  const form = f || { effective_from: new Date().toISOString().slice(0, 10), basic: cur?.basic ?? '', note: '', lines: Object.fromEntries((cur?.lines || []).map((l) => [l.component_id, l.value])) }
  const currency = cur?.currency || settings?.items?.find((s) => s.key === 'payroll_currency')?.value || 'USD'
  const set = (patch) => setF({ ...form, ...patch })
  const save = useAction(() => api.post(`/payroll/compensation/${person.user_id}`, {
    effective_from: form.effective_from, basic: Number(form.basic), note: form.note || null,
    lines: Object.entries(form.lines).filter(([, v]) => v !== '' && v != null).map(([id, v]) => ({ component_id: Number(id), value: Number(v) })),
  }), { invalidate: ['/payroll/compensation'], success: 'Pay structure saved', onSuccess: onClose })
  const fe = fieldErrors(save.error)
  return (
    <Modal open onClose={onClose} wide title={`Pay structure · ${person.name}`}
      footer={<><Button variant="secondary" onClick={onClose}>Close</Button><Button loading={save.isPending} disabled={!form.basic || Number(form.basic) <= 0 || !form.effective_from} onClick={() => save.mutate()}>Save new version</Button></>}>
      <div className="space-y-4">
        {save.error && !Object.keys(fe).length && <Alert>{save.error.message}</Alert>}
        <p className="text-sm text-slate-600">Saving creates a new version from the date you choose. Earlier versions are kept and payslips already approved never change.</p>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Effective from" required error={fe.effective_from}><Input type="date" value={form.effective_from} onChange={(e) => set({ effective_from: e.target.value })} /></Field>
          <Field label={`Monthly basic (${currency})`} required error={fe.basic}><Input type="number" min="0" step="0.01" value={form.basic} onChange={(e) => set({ basic: e.target.value })} /></Field>
          <Field label="Note"><Input value={form.note} onChange={(e) => set({ note: e.target.value })} maxLength={300} /></Field>
        </div>
        <fieldset className="rounded-lg border border-slate-200 p-3">
          <legend className="px-1 text-sm font-medium">Components (leave blank to not apply)</legend>
          <div className="grid gap-3 sm:grid-cols-2">
            {active.map((c) => (
              <Field key={c.id} label={`${c.name} (${c.kind}${c.calc === 'fixed' ? '' : `, % ${c.calc === 'percent_of_basic' ? 'of basic' : 'of gross'}`})`}>
                <Input type="number" min="0" step="0.01" placeholder={String(c.default_value)} value={form.lines[c.id] ?? ''} onChange={(e) => set({ lines: { ...form.lines, [c.id]: e.target.value } })} />
              </Field>
            ))}
          </div>
          {!active.length && <p className="text-sm text-slate-500">Add components in the Components tab first.</p>}
        </fieldset>
        {hist?.items?.length > 0 && (
          <div><h3 className="mb-1 text-sm font-medium">History</h3>
            <ul className="space-y-1 text-sm text-slate-600">{hist.items.map((h) => <li key={h.id}>From {fmtDate(h.effective_from)}: {fmtMoney(h.basic, h.currency)} basic, {h.lines.length} component(s){h.note ? ` · ${h.note}` : ''}</li>)}</ul></div>
        )}
      </div>
    </Modal>
  )
}

function Structures() {
  const [page, setPage] = useState(1)
  const [q, setQ] = useState('')
  const { data, isLoading, error, refetch } = useApi('/payroll/compensation', { page, page_size: 15, q: q || undefined })
  const [person, setPerson] = useState(null)
  return (
    <>
      <div className="mb-3 w-64"><Field label="Search"><Input value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} placeholder="Name" /></Field></div>
      {isLoading ? <PageLoader /> : error ? <ErrorState error={error} onRetry={refetch} /> : (
        <>
          <Table caption="Pay structures" rows={data.items} rowKey={(p) => p.user_id} empty={<EmptyState title="Nobody found" />}
            columns={[
              { key: 'name', header: 'Employee', render: (p) => <>{p.name} <span className="text-xs text-slate-500">{p.employee_code}</span></> },
              { key: 'role', header: 'Role' },
              { key: 'basic', header: 'Basic / month', render: (p) => (p.basic == null ? <Badge tone="amber">not set</Badge> : fmtMoney(p.basic, p.currency)) },
              { key: 'from', header: 'Since', render: (p) => (p.effective_from ? fmtDate(p.effective_from) : '—') },
              { key: 'a', header: '', render: (p) => <Button size="sm" variant="secondary" onClick={() => setPerson(p)}>{p.basic == null ? 'Set up' : 'Change'}</Button> },
            ]} />
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onChange={setPage} />
        </>
      )}
      {person && <StructureDialog person={person} onClose={() => setPerson(null)} />}
    </>
  )
}

export default function PayrollPage() {
  const [tab, setTab] = useState('runs')
  return (
    <>
      <PageHeader title="Payroll" description="Pay structures, monthly runs and approval. Visible to payroll staff only." />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: 'runs', label: 'Runs' }, { id: 'structures', label: 'Pay structures' }, { id: 'components', label: 'Components' }]} />
      <div className="mt-4">
        {tab === 'runs' && <Runs />}
        {tab === 'structures' && <Structures />}
        {tab === 'components' && <Components />}
      </div>
    </>
  )
}
