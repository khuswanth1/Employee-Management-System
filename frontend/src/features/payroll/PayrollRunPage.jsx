import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Alert, Badge, Button, Card, ConfirmDialog, EmptyState, ErrorState, Field, Input, Modal, PageHeader, PageLoader, Select, StatCard, Table, Textarea, useToast } from '../../components/ui'
import { api, download, fieldErrors } from '../../lib/api'
import { fmtDateTime } from '../../lib/format'
import { useAction, useApi } from '../../lib/hooks'
import { useAuth } from '../auth/AuthContext'
import PayslipView from './PayslipView'
import { fmtMoney, monthName, warningText } from './money'
import { RUN_LABEL, RUN_TONE } from './PayrollPage'

function Adjustment({ slip, onClose }) {
  const [f, setF] = useState({ name: '', kind: 'earning', amount: '' })
  const add = useAction(() => api.post(`/payroll/payslips/${slip.id}/adjustments`, { name: f.name.trim(), kind: f.kind, amount: Number(f.amount) }),
    { invalidate: ['/payroll'], success: 'Adjustment added', onSuccess: onClose })
  const fe = fieldErrors(add.error)
  return (
    <Modal open onClose={onClose} title={`One-off adjustment · ${slip.employee}`}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={add.isPending} disabled={f.name.trim().length < 2 || !(Number(f.amount) > 0)} onClick={() => add.mutate()}>Add</Button></>}>
      <div className="space-y-4">
        {add.error && !Object.keys(fe).length && <Alert>{add.error.message}</Alert>}
        <Field label="Description" required error={fe.name}><Input value={f.name} onChange={(e) => setF((s) => ({ ...s, name: e.target.value }))} maxLength={120} placeholder="Spot bonus, advance recovery…" /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Type"><Select value={f.kind} onChange={(e) => setF((s) => ({ ...s, kind: e.target.value }))}><option value="earning">Adds to pay</option><option value="deduction">Taken from pay</option></Select></Field>
          <Field label="Amount" required error={fe.amount}><Input type="number" min="0" step="0.01" value={f.amount} onChange={(e) => setF((s) => ({ ...s, amount: e.target.value }))} /></Field>
        </div>
        <p className="text-xs text-slate-500">Only for this month&apos;s payslip. It survives a recalculation until you remove it from the payslip.</p>
      </div>
    </Modal>
  )
}

function TextDialog({ title, label, cta, onSubmit, pending, onClose, required }) {
  const [v, setV] = useState('')
  return (
    <Modal open onClose={onClose} title={title} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={pending} disabled={required && v.trim().length < 3} onClick={() => onSubmit(v.trim())}>{cta}</Button></>}>
      <Field label={label} required={required}><Textarea value={v} onChange={(e) => setV(e.target.value)} maxLength={300} /></Field>
    </Modal>
  )
}

export default function PayrollRunPage() {
  const { id } = useParams()
  const { user, role } = useAuth()
  const toast = useToast()
  const { data: run, isLoading, error, refetch } = useApi(`/payroll/runs/${id}`)
  const [dlg, setDlg] = useState(null) // { kind, slip? }
  const done = (msg) => ({ invalidate: ['/payroll'], success: msg, onSuccess: () => setDlg(null) })
  const recalc = useAction(() => api.post(`/payroll/runs/${id}/recalculate`), done('Recalculated'))
  const submit = useAction(() => api.post(`/payroll/runs/${id}/submit`), done('Submitted for approval'))
  const approve = useAction(() => api.post(`/payroll/runs/${id}/approve`), done('Payroll approved. Employees were notified.'))
  const cancel = useAction(() => api.post(`/payroll/runs/${id}/cancel`), done('Run cancelled'))
  const back = useAction((note) => api.post(`/payroll/runs/${id}/return`, { note }), done('Sent back to draft'))
  const paid = useAction((reference) => api.post(`/payroll/runs/${id}/mark-paid`, { reference: reference || null }), done('Marked as paid'))
  if (isLoading) return <PageLoader />
  if (error) return <ErrorState error={error} onRetry={refetch} />
  const cur = run.policy?.currency
  const manager = role === 'founder' || (role === 'hr' && !user.branch_id)
  const mine = run.processed_by === user.full_name
  const blocked = run.payslips.filter((s) => s.net < 0).length
  const title = monthName(run.year, run.month)
  return (
    <>
      <PageHeader title={`Payroll · ${title}`} description={<span className="flex items-center gap-2"><Badge tone={RUN_TONE[run.status]}>{RUN_LABEL[run.status]}</Badge>{run.note}</span>}
        actions={<>
          <Link to="/payroll" className="text-sm text-brand-700 hover:underline self-center">All runs</Link>
          <Button variant="secondary" onClick={() => download(`/payroll/runs/${id}/export.csv`, `payroll-${run.year}-${String(run.month).padStart(2, '0')}.csv`).catch((e) => toast(e.message, 'red'))}>Export CSV</Button>
          {manager && run.status === 'draft' && <>
            <Button variant="secondary" loading={recalc.isPending} onClick={() => recalc.mutate()}>Recalculate</Button>
            <Button loading={submit.isPending} disabled={!run.payslips.length} onClick={() => submit.mutate()}>Submit for approval</Button></>}
          {manager && run.status === 'processed' && !mine && <>
            <Button variant="secondary" onClick={() => setDlg({ kind: 'back' })}>Send back</Button>
            <Button loading={approve.isPending} disabled={blocked > 0} onClick={() => setDlg({ kind: 'approve' })}>Approve</Button></>}
          {manager && run.status === 'approved' && <Button onClick={() => setDlg({ kind: 'paid' })}>Mark as paid</Button>}
          {manager && ['draft', 'processed'].includes(run.status) && <Button variant="danger" onClick={() => setDlg({ kind: 'cancel' })}>Cancel run</Button>}
        </>} />
      {run.status === 'processed' && mine && <div className="mb-4"><Alert tone="amber">You submitted this run, so someone else has to approve it.</Alert></div>}
      {blocked > 0 && <div className="mb-4"><Alert>{blocked} payslip(s) have deductions larger than pay and block approval. Change the pay structure or add an adjustment, then recalculate.</Alert></div>}
      {run.skipped.length > 0 && (
        <div className="mb-4"><Alert tone="amber">Not in this run: {run.skipped.map((s) => `${s.name} (${s.reason})`).join('; ')}</Alert></div>
      )}
      <div className="mb-6 grid gap-4 sm:grid-cols-4">
        <StatCard title="Payslips" value={run.totals.payslips} />
        <StatCard title="Gross pay" value={fmtMoney(run.totals.gross, cur)} />
        <StatCard title="Deductions" value={fmtMoney(run.totals.deductions, cur)} />
        <StatCard title="Net pay" value={fmtMoney(run.totals.net, cur)} />
      </div>
      <Table caption="Payslips" rows={run.payslips} empty={<EmptyState title="No payslips" description="Nobody in this run has a pay structure yet." />}
        columns={[
          { key: 'employee', header: 'Employee', render: (s) => <>{s.employee}{s.warnings.length > 0 && <> <Badge tone="red">{s.warnings.map(warningText).join('; ')}</Badge></>}</> },
          { key: 'basic', header: 'Basic', render: (s) => fmtMoney(s.basic, s.currency) },
          { key: 'gross', header: 'Gross', render: (s) => fmtMoney(s.gross, s.currency) },
          { key: 'deductions', header: 'Deductions', render: (s) => fmtMoney(s.deductions, s.currency) },
          { key: 'net', header: 'Net', render: (s) => <strong>{fmtMoney(s.net, s.currency)}</strong> },
          { key: 'a', header: '', render: (s) => (
            <div className="flex gap-1"><Button size="sm" variant="secondary" onClick={() => setDlg({ kind: 'view', slip: s })}>Open</Button>
              {manager && run.status === 'draft' && <Button size="sm" variant="ghost" onClick={() => setDlg({ kind: 'adjust', slip: s })}>Adjust</Button>}</div>) },
        ]} />
      {run.by_department.length > 0 && (
        <Card title="By department" className="mt-6" pad={false}><div className="p-1">
          <Table caption="Payroll by department" rows={run.by_department} rowKey={(d) => d.department}
            columns={[{ key: 'department', header: 'Department' }, { key: 'people', header: 'People' }, { key: 'gross', header: 'Gross', render: (d) => fmtMoney(d.gross, cur) }, { key: 'net', header: 'Net', render: (d) => fmtMoney(d.net, cur) }]} />
        </div></Card>
      )}
      {(run.processed_at || run.approved_at) && (
        <p className="mt-4 text-xs text-slate-500">{run.processed_at && `Submitted by ${run.processed_by} on ${fmtDateTime(run.processed_at)}. `}{run.approved_at && `Approved by ${run.approved_by} on ${fmtDateTime(run.approved_at)}. `}{run.paid_at && `Paid ${fmtDateTime(run.paid_at)}${run.payment_reference ? ` (${run.payment_reference})` : ''}.`}</p>
      )}
      {dlg?.kind === 'view' && <PayslipView id={dlg.slip.id} onClose={() => setDlg(null)} />}
      {dlg?.kind === 'adjust' && <Adjustment slip={dlg.slip} onClose={() => setDlg(null)} />}
      {dlg?.kind === 'back' && <TextDialog title="Send back to draft" label="What needs fixing?" cta="Send back" required pending={back.isPending} onSubmit={(n) => back.mutate(n)} onClose={() => setDlg(null)} />}
      {dlg?.kind === 'paid' && <TextDialog title="Mark as paid" label="Payment reference (optional)" cta="Mark as paid" pending={paid.isPending} onSubmit={(r) => paid.mutate(r)} onClose={() => setDlg(null)} />}
      <ConfirmDialog open={dlg?.kind === 'approve'} title="Approve payroll" confirmLabel="Approve" loading={approve.isPending} onClose={() => setDlg(null)} onConfirm={() => approve.mutate()}
        message={`Approve ${title}? ${run.totals.payslips} payslips totalling ${fmtMoney(run.totals.net, cur)} net become final and visible to employees.`} />
      <ConfirmDialog open={dlg?.kind === 'cancel'} danger title="Cancel payroll run" confirmLabel="Cancel run" loading={cancel.isPending} onClose={() => setDlg(null)} onConfirm={() => cancel.mutate()}
        message="Cancel this run? Its draft payslips are discarded and the month can be calculated again." />
    </>
  )
}
