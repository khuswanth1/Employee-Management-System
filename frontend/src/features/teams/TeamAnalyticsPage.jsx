import { Link } from 'react-router-dom'
import { Badge, EmptyState, ErrorState, PageHeader, PageLoader, ProgressBar, StatCard, Table } from '../../components/ui'
import { useApi } from '../../lib/hooks'

export default function TeamAnalyticsPage() {
  const { data, isLoading, error, refetch } = useApi('/teams/analytics')
  if (isLoading) return <PageLoader />
  if (error) return <ErrorState error={error} onRetry={refetch} />
  const t = data.totals
  return (
    <>
      <PageHeader title="Team productivity" description="Delivery, workload and risk across the teams you can see" />
      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-5">
        <StatCard title="Active teams" value={data.teams} />
        <StatCard title="People in teams" value={t.members} />
        <StatCard title="Open tasks" value={t.open_tasks} />
        <StatCard title="Overdue" value={t.overdue_tasks} tone="danger" />
        <StatCard title="Done (30 days)" value={t.done_last_30d} />
      </div>
      <Table
        caption="Team productivity"
        rows={data.items}
        rowKey={(r) => r.team_id}
        empty={<EmptyState title="No active teams" description="Teams you manage or oversee will appear here." />}
        columns={[
          { key: 'name', header: 'Team', render: (r) => <Link className="font-medium text-brand-700 hover:underline" to={`/teams/${r.team_id}`}>{r.name}</Link> },
          { key: 'leader', header: 'Leader', render: (r) => r.leader?.full_name || <span className="text-amber-700">None</span> },
          { key: 'members', header: 'Members', render: (r) => r.members },
          { key: 'load', header: 'Open / member', render: (r) => r.tasks_per_member },
          { key: 'completion', header: 'Completion', className: 'w-40', render: (r) => <ProgressBar value={r.completion_rate} /> },
          { key: 'ontime', header: 'On time', render: (r) => (r.on_time_rate == null ? '—' : `${r.on_time_rate}%`) },
          { key: 'risk', header: 'Risk', render: (r) => (
            <span className="flex gap-1">
              {r.overdue_tasks > 0 && <Badge tone="red">{r.overdue_tasks} overdue</Badge>}
              {r.blocked_tasks > 0 && <Badge tone="amber">{r.blocked_tasks} blocked</Badge>}
              {!r.overdue_tasks && !r.blocked_tasks && <Badge tone="green">Clear</Badge>}
            </span>
          ) },
          { key: 'upd', header: 'Updates today', render: (r) => `${r.updates_today}/${r.members}` },
        ]}
      />
    </>
  )
}
