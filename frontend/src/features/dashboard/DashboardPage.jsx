import { Link } from 'react-router-dom'
import { Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Card, EmptyState, ErrorState, PageHeader, PageLoader, ProgressBar, StatCard, StatusBadge } from '../../components/ui'
import { useApi } from '../../lib/hooks'
import { fmtDate, label } from '../../lib/format'
import { useAuth } from '../auth/AuthContext'

const COLORS = ['#4f46e5', '#0ea5e9', '#f59e0b', '#10b981', '#ef4444', '#8b5cf6']
const STATUS_ORDER = ['todo', 'in_progress', 'review', 'changes_requested', 'done']

function TaskStatusChart({ data, title = 'Tasks by status' }) {
  const rows = STATUS_ORDER.map((k) => ({ name: label(k), value: data?.[k] || 0 }))
  const total = rows.reduce((a, r) => a + r.value, 0)
  return (
    <Card title={title}>
      {total === 0 ? <p className="py-8 text-center text-sm text-slate-500">No tasks yet</p> : (
        <div className="h-56" role="img" aria-label={`Task status chart: ${rows.map((r) => `${r.name} ${r.value}`).join(', ')}`}>
          <ResponsiveContainer>
            <PieChart>
              <Pie data={rows} dataKey="value" nameKey="name" innerRadius={50} outerRadius={80} paddingAngle={2}>
                {rows.map((_, i) => <Cell key={i} fill={COLORS[i]} />)}
              </Pie>
              <Tooltip /><Legend />
            </PieChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  )
}

function WorkloadChart({ data }) {
  return (
    <Card title="Employee workload (open tasks)">
      {!data?.length ? <p className="py-8 text-center text-sm text-slate-500">No open assignments</p> : (
        <div className="h-64" role="img" aria-label="Open and overdue tasks per employee">
          <ResponsiveContainer>
            <BarChart data={data} layout="vertical" margin={{ left: 20 }}>
              <CartesianGrid strokeDasharray="3 3" horizontal={false} />
              <XAxis type="number" allowDecimals={false} /><YAxis type="category" dataKey="user_name" width={110} tick={{ fontSize: 12 }} />
              <Tooltip /><Legend />
              <Bar dataKey="open_tasks" name="Open" fill="#4f46e5" radius={[0, 4, 4, 0]} />
              <Bar dataKey="overdue_tasks" name="Overdue" fill="#ef4444" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  )
}

function AttendanceCard({ data, title = 'Attendance today' }) {
  if (!data) return null
  const rows = [{ name: 'Present', value: data.present }, { name: 'On leave', value: data.on_leave }, { name: 'Absent', value: data.absent }]
  return (
    <Card title={title}>
      <div className="grid grid-cols-3 gap-3 text-center">
        {rows.map((r, i) => (
          <div key={r.name}><p className="text-2xl font-semibold tabular-nums" style={{ color: ['#10b981', '#0ea5e9', '#ef4444'][i] }}>{r.value}</p><p className="text-xs text-slate-500">{r.name}</p></div>
        ))}
      </div>
      <div className="mt-4"><ProgressBar value={data.total ? Math.round((data.present / data.total) * 100) : 0} /></div>
    </Card>
  )
}

function ProjectList({ projects, linked = true }) {
  return (
    <Card title="Projects" action={linked && <Link className="text-sm font-medium text-brand-700 hover:underline" to="/projects">View all</Link>} pad={false}>
      {!projects?.length ? <div className="p-5"><EmptyState title="No projects yet" /></div> : (
        <ul className="divide-y divide-slate-100">
          {projects.map((p) => (
            <li key={p.id} className="px-5 py-3">
              <div className="mb-1.5 flex items-center justify-between gap-2">
                {linked ? <Link to={`/projects/${p.id}`} className="truncate text-sm font-medium text-slate-900 hover:text-brand-700">{p.name}</Link> : <span className="truncate text-sm font-medium text-slate-900">{p.name}</span>}
                <StatusBadge value={p.status} />
              </div>
              <ProgressBar value={p.progress} />
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function MyWork({ d }) {
  return (
    <>
      <Card title="My upcoming tasks" action={<Link className="text-sm font-medium text-brand-700 hover:underline" to="/my-tasks">All tasks</Link>} pad={false}>
        {!d.my_upcoming_tasks?.length ? <div className="p-5 text-center text-sm text-slate-500">Nothing assigned to you</div> : (
          <ul className="divide-y divide-slate-100">
            {d.my_upcoming_tasks.map((t) => (
              <li key={t.id} className="flex items-center justify-between gap-3 px-5 py-3 text-sm">
                <div className="min-w-0"><p className="truncate font-medium text-slate-900">{t.title}</p><p className="text-xs text-slate-500">Due {fmtDate(t.due_date)}</p></div>
                <div className="flex shrink-0 gap-1.5"><StatusBadge value={t.priority} /><StatusBadge value={t.status} /></div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  )
}

export default function DashboardPage() {
  const { user, role } = useAuth()
  const { data: d, isLoading, error, refetch } = useApi('/dashboard')
  if (isLoading) return <PageLoader />
  if (error) return <ErrorState error={error} onRetry={refetch} />

  return (
    <>
      <PageHeader title={`Welcome back, ${user.full_name.split(' ')[0]}`} description={`${label(role)} overview for ${user.company?.name}`} />
      {role !== 'founder' && !d.submitted_update_today && (
        <div className="mb-6 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <span>You haven't submitted today's work update yet.</span>
          <Link to="/updates" className="font-medium underline">Submit now</Link>
        </div>
      )}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {(role === 'founder' || role === 'hr') && <StatCard title="Headcount" value={d.headcount} hint={`${d.onboarding} onboarding`} />}
        {role === 'founder' && <StatCard title="Overdue tasks" value={d.overdue_tasks} tone="danger" hint="Company-wide" />}
        {role === 'manager' && <StatCard title="Awaiting my review" value={d.awaiting_review} hint="Tasks in review" />}
        {role === 'manager' && <StatCard title="Overdue (my projects)" value={d.overdue_tasks} tone="danger" />}
        {(role === 'manager' || role === 'hr' || role === 'founder') && <StatCard title="Leave approvals" value={d.pending_leave_approvals} hint="Pending" />}
        {role === 'manager' && <StatCard title="Updates to review" value={d.updates_to_review} />}
        {role === 'founder' && <StatCard title="Open blockers (7d)" value={d.blockers_open} tone="danger" hint={`${d.updates_this_week} updates this week`} />}
        {role !== 'founder' && <StatCard title="My open tasks" value={(d.my_tasks.todo || 0) + (d.my_tasks.in_progress || 0) + (d.my_tasks.review || 0) + (d.my_tasks.changes_requested || 0)} />}
        {role !== 'founder' && <StatCard title="My overdue tasks" value={d.my_overdue_tasks} tone="danger" />}
        {role !== 'founder' && <StatCard title="Pending leave requests" value={d.pending_leave_requests} hint="Mine" />}
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        {role === 'founder' && <>
          <TaskStatusChart data={d.company_task_status} title="Company tasks by status" />
          <ProjectList projects={d.projects} linked={false} />
          <WorkloadChart data={d.workload} />
          <AttendanceCard data={d.attendance_today} />
          <Card title="Projects by status">
            <div className="flex flex-wrap gap-2">{Object.keys(d.project_status).length ? Object.entries(d.project_status).map(([k, v]) => <div key={k} className="rounded-lg bg-slate-50 px-4 py-2 text-center"><p className="text-xl font-semibold">{v}</p><p className="text-xs text-slate-500">{label(k)}</p></div>) : <p className="text-sm text-slate-500">No projects</p>}</div>
          </Card>
        </>}
        {role === 'hr' && <>
          <Card title="Headcount by department">
            {!d.by_department.length ? <p className="text-sm text-slate-500">No data</p> : (
              <div className="h-64" role="img" aria-label="Headcount by department"><ResponsiveContainer><BarChart data={d.by_department}><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="department" tick={{ fontSize: 12 }} /><YAxis allowDecimals={false} /><Tooltip /><Bar dataKey="count" name="Employees" fill="#4f46e5" radius={[4, 4, 0, 0]} /></BarChart></ResponsiveContainer></div>
            )}
          </Card>
          <AttendanceCard data={d.attendance_today} />
          <Card title="Upcoming holidays">
            {d.upcoming_holidays.length ? <ul className="divide-y divide-slate-100 text-sm">{d.upcoming_holidays.map((h) => <li key={h.date} className="flex justify-between py-2"><span>{h.name}</span><span className="text-slate-500">{fmtDate(h.date)}</span></li>)}</ul> : <p className="text-sm text-slate-500">None scheduled</p>}
          </Card>
        </>}
        {role === 'manager' && <>
          <ProjectList projects={d.projects} />
          <TaskStatusChart data={d.team_task_status} title="My projects: tasks by status" />
          <WorkloadChart data={d.workload} />
          <AttendanceCard data={d.team_attendance} title="My team today" />
        </>}
        {role === 'employee' && <TaskStatusChart data={d.my_tasks} title="My tasks by status" />}
        {role !== 'founder' && <MyWork d={d} />}
      </div>
    </>
  )
}
