import { useState } from 'react'
import { Button, EmptyState, ErrorState, PageHeader, PageLoader, StatusBadge, Table } from '../../components/ui'
import { useApi } from '../../lib/hooks'
import PayslipView from './PayslipView'
import { fmtMoney, monthName } from './money'

export default function MyPayslipsPage() {
  const { data, isLoading, error, refetch } = useApi('/payroll/my-payslips')
  const [open, setOpen] = useState(null)
  if (isLoading) return <PageLoader />
  if (error) return <ErrorState error={error} onRetry={refetch} />
  return (
    <>
      <PageHeader title="My payslips" description="Issued payslips appear here once payroll for the month is approved." />
      <Table caption="My payslips" rows={data.items} empty={<EmptyState title="No payslips yet" description="Your first payslip will show up after the next payroll is approved." />}
        columns={[
          { key: 'period', header: 'Month', render: (p) => monthName(p.year, p.month) },
          { key: 'gross', header: 'Gross', render: (p) => fmtMoney(p.gross, p.currency) },
          { key: 'deductions', header: 'Deductions', render: (p) => fmtMoney(p.deductions, p.currency) },
          { key: 'net', header: 'Net pay', render: (p) => <strong>{fmtMoney(p.net, p.currency)}</strong> },
          { key: 'status', header: '', render: (p) => <StatusBadge value={p.status === 'paid' ? 'completed' : 'approved'} /> },
          { key: 'a', header: '', render: (p) => <Button size="sm" variant="secondary" onClick={() => setOpen(p.id)}>View</Button> },
        ]} />
      {open && <PayslipView id={open} onClose={() => setOpen(null)} />}
    </>
  )
}
