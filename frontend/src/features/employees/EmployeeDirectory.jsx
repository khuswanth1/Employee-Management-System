import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Avatar, EmptyState, ErrorState, PageHeader, PageLoader, SearchInput, Table } from '../../components/ui'
import { ROLE_LABEL } from '../../lib/format'
import { useApi } from '../../lib/hooks'

// Read-only directory for people who do not manage employee records: everyone they work with, click a row for the card.
export default function EmployeeDirectory() {
  const nav = useNavigate()
  const [q, setQ] = useState('')
  const { data, isLoading, error, refetch } = useApi('/employees/directory')
  const { data: depts } = useApi('/departments')
  const dept = Object.fromEntries((depts?.items || []).map((d) => [d.id, d.name]))
  const rows = (data?.items || []).filter((u) => `${u.full_name} ${u.designation || ''}`.toLowerCase().includes(q.trim().toLowerCase()))
  return (
    <>
      <PageHeader title="People" description="Everyone you work with. Select a person to see their profile card." />
      <div className="mb-4 max-w-sm"><SearchInput value={q} onChange={setQ} placeholder="Search by name or title" /></div>
      {isLoading ? <PageLoader /> : error ? <ErrorState error={error} onRetry={refetch} /> : (
        <Table caption="People" rows={rows} onRowClick={(u) => nav(`/employees/${u.id}`)} empty={<EmptyState title="Nobody matches" />}
          columns={[
            { key: 'full_name', header: 'Name', render: (u) => <span className="flex items-center gap-2"><Avatar name={u.full_name} size={8} userId={u.id} v={u.avatar_v} /><span className="font-medium text-slate-900">{u.full_name}</span></span> },
            { key: 'designation', header: 'Title' },
            { key: 'role', header: 'Role', render: (u) => ROLE_LABEL[u.role] || u.role },
            { key: 'department_id', header: 'Department', render: (u) => dept[u.department_id] || '—' },
          ]} />
      )}
    </>
  )
}
