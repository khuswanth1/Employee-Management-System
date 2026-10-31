import { useState } from 'react'
import { Alert, Button, Card, EmptyState, ErrorState, Field, Input, Modal, PageHeader, PageLoader, StatCard, StatusBadge, Table } from '../../components/ui'
import { api, fieldErrors } from '../../lib/api'
import { fmtDate } from '../../lib/format'
import { useAction, useApi } from '../../lib/hooks'
import SecurityCard from '../auth/SecurityCard'

function CreateModal({ onClose }) {
  const blank = { name: '', slug: '', founder_name: '', founder_email: '', founder_password: '', max_users: 500 }
  const [f, setF] = useState(blank)
  const create = useAction(() => api.post('/platform/companies', { ...f, max_users: Number(f.max_users) }), { invalidate: ['/platform'], success: 'Company provisioned', onSuccess: onClose })
  const fe = fieldErrors(create.error)
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }))
  return (
    <Modal open onClose={onClose} wide title="Provision a company" footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={create.isPending} onClick={() => create.mutate()}>Create company & database</Button></>}>
      <form className="grid gap-4 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); create.mutate() }}>
        {create.error && !Object.keys(fe).length && <div className="sm:col-span-2"><Alert>{create.error.message}</Alert></div>}
        <Field label="Company name" required error={fe.name}><Input value={f.name} onChange={set('name')} /></Field>
        <Field label="Company URL name" required error={fe.slug} hint="Lowercase letters, digits and hyphens. Employees type this to sign in."><Input value={f.slug} onChange={(e) => setF({ ...f, slug: e.target.value.toLowerCase() })} /></Field>
        <Field label="Founder name" required error={fe.founder_name}><Input value={f.founder_name} onChange={set('founder_name')} /></Field>
        <Field label="Founder email" required error={fe.founder_email}><Input type="email" value={f.founder_email} onChange={set('founder_email')} autoComplete="off" /></Field>
        <Field label="Founder temporary password" required error={fe.founder_password} hint="10+ characters with upper/lower case and a digit"><Input type="password" value={f.founder_password} onChange={set('founder_password')} autoComplete="new-password" /></Field>
        <Field label="Max users" error={fe.max_users}><Input type="number" min="1" value={f.max_users} onChange={set('max_users')} /></Field>
      </form>
    </Modal>
  )
}

function Usage({ company, onClose }) {
  const { data } = useApi(`/platform/companies/${company.id}/usage`)
  const backup = useAction(() => api.post(`/platform/companies/${company.id}/backup`), { success: (b) => `Backup created: ${b.file}` })
  return (
    <Modal open onClose={onClose} title={`${company.name} — usage`} footer={<><Button variant="secondary" loading={backup.isPending} onClick={() => backup.mutate()}>Create backup</Button><Button onClick={onClose}>Close</Button></>}>
      {!data ? <PageLoader /> : (
        <div className="grid grid-cols-2 gap-3">
          <StatCard title="Users" value={`${data.active_users}/${data.max_users}`} /><StatCard title="Online now" value={data.online_users} />
          <StatCard title="Projects" value={data.projects} /><StatCard title="Tasks" value={data.tasks} />
          <StatCard title="Audit events" value={data.audit_events} />{data.db_size_bytes !== undefined && <StatCard title="Database size" value={`${(data.db_size_bytes / 1024).toFixed(0)} KB`} />}
        </div>
      )}
    </Modal>
  )
}

function DeleteModal({ company, onClose }) {
  const [typed, setTyped] = useState('')
  const del = useAction(() => api.del(`/platform/companies/${company.id}`), { invalidate: ['/platform'], success: 'Company deleted', onSuccess: onClose })
  return (
    <Modal open onClose={onClose} title={`Delete ${company.name}`} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button variant="danger" disabled={typed !== company.slug} loading={del.isPending} onClick={() => del.mutate()}>Delete company permanently</Button></>}>
      <div className="space-y-3">
        {del.error && <Alert>{del.error.message}</Alert>}
        <p className="text-sm text-slate-700">This permanently deletes the company, its database and every user, project and record in it. It cannot be undone. Create a backup first if you may need the data.</p>
        <Field label={`Type "${company.slug}" to confirm`}><Input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" /></Field>
      </div>
    </Modal>
  )
}

export default function CompaniesPage() {
  const [creating, setCreating] = useState(false)
  const [usage, setUsage] = useState(null)
  const [deleting, setDeleting] = useState(null)
  const { data, isLoading, error, refetch } = useApi('/platform/companies')
  const { data: stats } = useApi('/platform/stats')
  const setStatus = useAction(({ c, status }) => api.patch(`/platform/companies/${c.id}`, { status }), { invalidate: ['/platform'], success: 'Company updated' })
  const migrate = useAction(() => api.post('/platform/migrate'), { success: (r) => `Migrated ${r.migrated.length} tenant(s)${r.failed.length ? `, ${r.failed.length} failed` : ''}` })
  return (
    <>
      <PageHeader title="Companies" description="Provision and manage tenant workspaces. Each company has its own isolated database."
        actions={<><Button variant="secondary" loading={migrate.isPending} onClick={() => migrate.mutate()}>Run migrations</Button><Button onClick={() => setCreating(true)}>New company</Button></>} />
      <div className="mb-6 grid grid-cols-3 gap-4"><StatCard title="Companies" value={stats?.companies} /><StatCard title="Active" value={stats?.active} /><StatCard title="Suspended" value={stats?.suspended} /></div>
      {isLoading ? <PageLoader /> : error ? <ErrorState error={error} onRetry={refetch} /> : (
        <Table caption="Companies" rows={data.items} empty={<EmptyState title="No companies yet" action={<Button onClick={() => setCreating(true)}>New company</Button>} />}
          columns={[
            { key: 'name', header: 'Company', render: (c) => <div><p className="font-medium text-slate-900">{c.name}</p><p className="text-xs text-slate-500">{c.slug}</p></div> },
            { key: 'status', header: 'Status', render: (c) => <StatusBadge value={c.status} /> },
            { key: 'max_users', header: 'User limit' }, { key: 'created_at', header: 'Created', render: (c) => fmtDate(c.created_at) },
            { key: 'act', header: '', render: (c) => <div className="flex gap-3 text-sm"><button className="text-brand-700 hover:underline" onClick={() => setUsage(c)}>Usage</button>
              {c.status === 'active' ? <button className="text-red-600 hover:underline" onClick={() => window.confirm(`Suspend ${c.name}? All its users are locked out immediately.`) && setStatus.mutate({ c, status: 'suspended' })}>Suspend</button>
                : <button className="text-emerald-700 hover:underline" onClick={() => setStatus.mutate({ c, status: 'active' })}>Reactivate</button>}
              <button className="text-red-700 hover:underline" onClick={() => setDeleting(c)}>Delete</button></div> },
          ]} />
      )}
      {creating && <CreateModal onClose={() => setCreating(false)} />}
      {deleting && <DeleteModal company={deleting} onClose={() => setDeleting(null)} />}
      {usage && <Usage company={usage} onClose={() => setUsage(null)} />}
      <div className="mt-8 max-w-xl"><SecurityCard platform /></div>
    </>
  )
}
