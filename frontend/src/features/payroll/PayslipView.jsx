import { Alert, Button, ErrorState, Modal, PageLoader, Table } from '../../components/ui'
import { useApi } from '../../lib/hooks'
import { fmtMoney, monthName, warningText } from './money'

/** One payslip, laid out so that the browser's print dialog produces a clean page (Print -> Save as PDF). */
export default function PayslipView({ id, onClose }) {
  const { data: s, isLoading, error, refetch } = useApi(`/payroll/payslips/${id}`)
  const earnings = s?.lines.filter((l) => l.kind === 'earning') || []
  const deductions = s?.lines.filter((l) => l.kind === 'deduction') || []
  const money = (v) => fmtMoney(v, s?.currency)
  const cols = [{ key: 'name', header: 'Item', render: (l) => <>{l.name}{l.adjustment && <span className="ml-1 text-xs text-slate-500">(one-off)</span>}</> },
    { key: 'basis', header: 'Basis', render: (l) => <span className="text-xs text-slate-500">{l.basis || ''}</span> }, { key: 'amount', header: 'Amount', render: (l) => money(l.amount) }]
  return (
    <Modal open onClose={onClose} wide title={s ? `Payslip · ${monthName(s.period.year, s.period.month)}` : 'Payslip'}
      footer={<><Button variant="secondary" onClick={onClose}>Close</Button><Button onClick={() => window.print()} disabled={!s}>Print / save as PDF</Button></>}>
      {isLoading ? <PageLoader /> : error ? <ErrorState error={error} onRetry={refetch} /> : (
        <div className="space-y-4 text-sm" id="payslip-print">
          <div className="flex flex-wrap justify-between gap-2">
            <div><p className="text-lg font-semibold">{s.employee}</p><p className="text-slate-500">{[s.employee_code, s.designation].filter(Boolean).join(' · ')}</p></div>
            <div className="text-right text-slate-500"><p>{s.period.start} – {s.period.end}</p>
              <p>{s.facts.payable_days} of {s.facts.scheduled_days} working days paid{Number(s.facts.paid_leave_days) ? ` · ${s.facts.paid_leave_days} paid leave` : ''}{Number(s.facts.unpaid_leave_days) ? ` · ${s.facts.unpaid_leave_days} unpaid leave` : ''}{Number(s.facts.absent_days) ? ` · ${s.facts.absent_days} absent` : ''}</p></div>
          </div>
          {s.warnings.length > 0 && <Alert>{s.warnings.map(warningText).join('; ')}</Alert>}
          {s.run_status === 'draft' || s.run_status === 'processed' ? <Alert tone="amber">Draft: not yet approved, so this is not visible to the employee.</Alert> : null}
          <Table caption="Earnings" columns={cols} rows={earnings} rowKey={(l) => l.id} />
          <Table caption="Deductions" columns={cols} rows={deductions} rowKey={(l) => l.id} empty={<p className="p-3 text-slate-500">No deductions.</p>} />
          <dl className="grid grid-cols-3 gap-3 rounded-lg bg-slate-50 p-3 text-center">
            <div><dt className="text-xs text-slate-500">Gross pay</dt><dd className="font-semibold tabular-nums">{money(s.gross)}</dd></div>
            <div><dt className="text-xs text-slate-500">Deductions</dt><dd className="font-semibold tabular-nums">{money(s.deductions)}</dd></div>
            <div><dt className="text-xs text-slate-500">Net pay</dt><dd className="text-lg font-bold tabular-nums">{money(s.net)}</dd></div>
          </dl>
        </div>
      )}
    </Modal>
  )
}
