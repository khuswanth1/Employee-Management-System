import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Alert, Button, Card, EmptyState, ErrorState, PageHeader, PageLoader, StatCard } from '../../components/ui'
import { download } from '../../lib/api'
import { label } from '../../lib/format'
import { useApi } from '../../lib/hooks'
import { useAuth } from '../auth/AuthContext'

function Bars({ data, x, title, color = '#4f46e5' }) {
  return (
    <Card title={title}>
      {data.length ? (
        <div className="h-60" role="img" aria-label={`${title}: ${data.map((r) => `${r[x]} ${r.count}`).join(', ')}`}>
          <ResponsiveContainer><BarChart data={data}><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey={x} tick={{ fontSize: 12 }} /><YAxis allowDecimals={false} /><Tooltip /><Bar dataKey="count" name="People" fill={color} radius={[4, 4, 0, 0]} /></BarChart></ResponsiveContainer>
        </div>
      ) : <p className="text-sm text-slate-500">No data yet</p>}
    </Card>
  )
}

export default function BoardAnalyticsPage() {
  const { user } = useAuth()
  const { data: a, isLoading, error, refetch } = useApi('/board/analytics')
  if (isLoading) return <PageLoader />
  if (error?.status === 403) return <EmptyState title="No analytics access" description="The founder has not given your board account permission to view company analytics. Ask the founder to turn on “analytics.view” for you." />
  if (error) return <ErrorState error={error} onRetry={refetch} />
  const projects = Object.entries(a.projects).map(([k, v]) => `${v} ${label(k).toLowerCase()}`).join(', ') || 'None'
  return (
    <>
      <PageHeader title="Company analytics" description={`Aggregated figures for ${user.company?.name}. No individual employee data is shown.`}
        actions={<Button variant="secondary" onClick={() => download('/board/reports/headcount.csv', 'headcount-summary.csv')}>Download headcount summary</Button>} />
      <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard title="Headcount" value={a.headcount} hint={`${a.new_hires_30d} joined in 30 days`} />
        <StatCard title="Present today" value={`${a.attendance_today.rate}%`} hint={`${a.attendance_today.present} of ${a.attendance_today.headcount}`} />
        <StatCard title="Leave taken (YTD)" value={`${a.leave.approved_days_ytd} days`} hint={`${a.leave.pending_requests} requests pending`} />
        <StatCard title="Task completion" value={`${a.tasks.completion_rate}%`} hint={`${a.tasks.overdue} overdue`} tone={a.tasks.overdue ? 'danger' : 'default'} />
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <Bars data={a.by_branch} x="branch" title="Headcount by branch" />
        <Bars data={a.by_department} x="department" title="Headcount by department" color="#0d9488" />
        <Card title="Projects"><p className="text-sm text-slate-700">{projects}</p></Card>
        <Card title="Financial summary"><Alert tone="amber">{a.financial.reason}</Alert></Card>
      </div>
    </>
  )
}
