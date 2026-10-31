import { useState } from 'react'
import { Badge, Button, Card, EmptyState, ErrorState, Field, Input, PageHeader, PageLoader, Pagination, Table } from '../../components/ui'
import { download } from '../../lib/api'
import { fmtDate, fmtTimeIn } from '../../lib/format'
import { useApi } from '../../lib/hooks'
import { useToast } from '../../components/ui'
import { hm, statusInfo } from './labels'

const iso = (d) => d.toISOString().slice(0, 10)

export default function AttendanceReportPage() {
  const toast = useToast()
  const [range, setRange] = useState({ start: iso(new Date(Date.now() - 29 * 864e5)), end: iso(new Date()) })
  const [page, setPage] = useState(1)
  const { data: summary, isLoading, error, refetch } = useApi('/attendance/summary', range)
  const { data: rows } = useApi('/attendance', { ...range, page, page_size: 15 })
  return (
    <>
      <PageHeader title="Attendance report" description="Hours, presence and overtime for your scope"
        actions={<Button variant="secondary" onClick={() => download('/reports/attendance.csv', 'attendance.csv', range).catch((e) => toast(e.message, 'red'))}>Export CSV</Button>} />
      <div className="mb-4 flex flex-wrap gap-3">
        <Field label="From"><Input type="date" value={range.start} max={range.end} onChange={(e) => { setRange({ ...range, start: e.target.value }); setPage(1) }} /></Field>
        <Field label="To"><Input type="date" value={range.end} min={range.start} onChange={(e) => { setRange({ ...range, end: e.target.value }); setPage(1) }} /></Field>
      </div>
      {isLoading ? <PageLoader /> : error ? <ErrorState error={error} onRetry={refetch} /> : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <Card title="Summary by employee" pad={false} className="flex min-w-0 flex-col">
            <div className="p-1"><Table caption="Attendance summary" rows={summary.items} rowKey={(r) => r.user_id} empty={<EmptyState title="No attendance in this period" />}
              columns={[{ key: 'user_name', header: 'Employee' }, { key: 'days_present', header: 'Days' }, { key: 'worked_hours', header: 'Hours' }, { key: 'overtime_hours', header: 'Overtime (h)' },
                { key: 'late_days', header: 'Late days', render: (r) => (r.late_days ? `${r.late_days} (${hm(r.late_minutes)})` : '0') }, { key: 'early_departures', header: 'Left early' },
                { key: 'half_days', header: 'Half days' }, { key: 'weekend_days', header: 'Weekend' }, { key: 'holiday_days', header: 'Holiday' }, { key: 'wfh_days', header: 'Home' },
                { key: 'auto_closed', header: 'No check-out' }]} /></div>
          </Card>
          <Card title="Daily records" pad={false} className="flex min-w-0 flex-col">
            <div className="p-1"><Table caption="Attendance records" rows={rows?.items} empty={<EmptyState title="No records" />}
              columns={[{ key: 'user_name', header: 'Employee' }, { key: 'work_date', header: 'Date', render: (a) => fmtDate(a.work_date) }, { key: 'in', header: 'In', render: (a) => fmtTimeIn(a.check_in, a.timezone) },
                { key: 'out', header: 'Out', render: (a) => fmtTimeIn(a.check_out, a.timezone) }, { key: 'worked_hours', header: 'Worked (h)' }, { key: 'overtime_hours', header: 'Overtime (h)' },
                { key: 'late', header: 'Late', render: (a) => (a.late_minutes ? hm(a.late_minutes) : '—') },
                { key: 'status', header: 'Status', render: (a) => (a.status ? <Badge tone={statusInfo(a.status)[1]}>{statusInfo(a.status)[0]}</Badge> : '—') }]} /></div>
            {rows && <div className="mt-auto px-5 pb-4"><Pagination page={rows.page} pageSize={rows.page_size} total={rows.total} onChange={setPage} /></div>}
          </Card>
        </div>
      )}
    </>
  )
}
