import { Link, useParams } from 'react-router-dom'
import { Avatar, Button, Card, ErrorState, PageLoader } from '../../components/ui'
import { fmtDate, ROLE_LABEL } from '../../lib/format'
import { useApi } from '../../lib/hooks'
import EmployeeDetailPage from './EmployeeDetailPage'

function Fact({ label, children }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="mt-0.5 text-sm text-slate-900">{children || '—'}</dd>
    </div>
  )
}

// What colleagues may see of each other. Personal details, documents, history and pay are only on the full record.
export function ColleagueCardView({ c }) {
  return (
    <div className="mx-auto max-w-2xl">
      <Card>
        <div className="flex items-center gap-4">
          <Avatar name={c.full_name} size={16} userId={c.id} v={c.avatar_v} />
          <div className="min-w-0">
            <h1 className="truncate text-xl font-semibold text-slate-900">{c.full_name}</h1>
            <p className="text-sm text-slate-500">{[c.designation, ROLE_LABEL[c.role]].filter(Boolean).join(' · ')}</p>
          </div>
        </div>
        <dl className="mt-6 grid gap-4 sm:grid-cols-2" aria-label={`About ${c.full_name}`}>
          <Fact label="Department">{c.department}</Fact>
          <Fact label="Branch">{c.branch}</Fact>
          <Fact label="Team">{c.team}</Fact>
          <Fact label="Work location">{c.location}</Fact>
          <Fact label="Reports to">{c.manager ? <Link className="text-brand-700 hover:underline" to={`/employees/${c.manager.id}`}>{c.manager.name}</Link> : null}</Fact>
          <Fact label="Direct reports">{c.direct_reports ? String(c.direct_reports) : null}</Fact>
          <Fact label="Joined">{c.joined ? fmtDate(c.joined) : null}</Fact>
          {c.email && <Fact label="Email"><a className="text-brand-700 hover:underline" href={`mailto:${c.email}`}>{c.email}</a></Fact>}
        </dl>
        <p className="mt-6 text-xs text-slate-500">Personal details, documents, history and pay are visible only to the person, their manager and HR.</p>
        <div className="mt-4 flex flex-wrap gap-2">
          <Link to="/org-chart"><Button variant="secondary">Org chart</Button></Link>
          <Link to="/chat"><Button variant="secondary">Message in chat</Button></Link>
        </div>
      </Card>
    </div>
  )
}

// /employees/:id: the full record for people who may open it, otherwise the colleague card.
export default function EmployeeRoute() {
  const { id } = useParams()
  const { data, isLoading, error, refetch } = useApi(`/employees/${id}/card`)
  if (isLoading) return <PageLoader />
  if (error) return <ErrorState error={error} onRetry={refetch} />
  return data.can_open ? <EmployeeDetailPage /> : <ColleagueCardView c={data} />
}
