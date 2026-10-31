import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, Avatar, Button, EmptyState, ErrorState, Field, Modal, PageHeader, PageLoader, Select, Table } from '../../components/ui'
import { api, fieldErrors } from '../../lib/api'
import { useAction, useApi } from '../../lib/hooks'
import { EmployeeFormModal } from '../employees/EmployeesPage'

function ManagerModal({ open, onClose, manager }) {
  const { data: branches } = useApi('/branches', null, { enabled: open })
  const { data: depts } = useApi('/departments', null, { enabled: open })
  const { data: dir } = useApi('/employees/directory', null, { enabled: open })
  const { data: catalog } = useApi('/managers/permissions-catalog', null, { enabled: open })
  const [f, setF] = useState({ branch_id: '', department_id: '', reports_to: '', permissions: [] })
  useEffect(() => {
    if (open && manager) setF({ branch_id: manager.branch_id || '', department_id: manager.department_id || '', reports_to: manager.reports_to || '', permissions: manager.permissions })
  }, [open, manager])
  const save = useAction((permissions) => api.patch(`/managers/${manager.id}`, {
    branch_id: f.branch_id ? Number(f.branch_id) : null, department_id: f.department_id ? Number(f.department_id) : null,
    reports_to: f.reports_to ? Number(f.reports_to) : null, permissions: permissions === undefined ? f.permissions : permissions,
  }), { invalidate: ['/managers', '/branches', '/employees'], success: 'Manager updated', onSuccess: onClose })
  const fe = fieldErrors(save.error)
  const toggle = (k) => setF((s) => ({ ...s, permissions: s.permissions.includes(k) ? s.permissions.filter((x) => x !== k) : [...s.permissions, k] }))
  if (!manager) return null
  return (
    <Modal open={open} onClose={onClose} title={`Configure ${manager.full_name}`}
      footer={<><Button variant="secondary" onClick={() => save.mutate(null)} loading={save.isPending}>Reset permissions to defaults</Button><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={save.isPending} onClick={() => save.mutate()}>Save changes</Button></>}>
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
        {save.error && !Object.keys(fe).length && <Alert>{save.error.message}</Alert>}
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Branch" hint="Limits the manager to that branch's people and data">
            <Select value={f.branch_id} onChange={(e) => setF({ ...f, branch_id: e.target.value })}><option value="">No branch</option>{branches?.items.filter((b) => b.is_active || b.id === manager.branch_id).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</Select>
          </Field>
          <Field label="Department"><Select value={f.department_id} onChange={(e) => setF({ ...f, department_id: e.target.value })}><option value="">None</option>{depts?.items.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</Select></Field>
        </div>
        <Field label="Reports to"><Select value={f.reports_to} onChange={(e) => setF({ ...f, reports_to: e.target.value })}><option value="">Nobody</option>{dir?.items.filter((u) => u.id !== manager.id && u.role !== 'employee').map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}</Select></Field>
        <fieldset>
          <legend className="mb-2 text-sm font-medium text-slate-700">Permissions</legend>
          <ul className="space-y-2">
            {catalog?.items.map((p) => (
              <li key={p.key}><label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-0.5 h-4 w-4 accent-brand-600" checked={f.permissions.includes(p.key)} onChange={() => toggle(p.key)} />
                <span><span className="font-medium">{p.key}</span><span className="block text-xs text-slate-500">{p.description}</span></span></label></li>
            ))}
          </ul>
        </fieldset>
      </form>
    </Modal>
  )
}

function TeamModal({ open, onClose, manager }) {
  const { data: dir } = useApi('/employees/directory', null, { enabled: open })
  const [ids, setIds] = useState([])
  const candidates = useMemo(() => (dir?.items || []).filter((u) => u.role === 'employee' && (!manager?.branch_id || !u.branch_id || u.branch_id === manager.branch_id)), [dir, manager])
  useEffect(() => { if (open && dir && manager) setIds((dir.items || []).filter((u) => u.manager_id === manager.id).map((u) => u.id)) }, [open, dir, manager])
  const save = useAction(() => api.put(`/managers/${manager.id}/team`, { user_ids: ids }), { invalidate: ['/managers', '/employees'], success: 'Team updated', onSuccess: onClose })
  if (!manager) return null
  return (
    <Modal open={open} onClose={onClose} title={`${manager.full_name}'s team`}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={save.isPending} onClick={() => save.mutate()}>Save team ({ids.length})</Button></>}>
      {save.error && <div className="mb-3"><Alert>{save.error.message}</Alert></div>}
      <p className="mb-2 text-xs text-slate-500">Direct reports are employees of the manager's branch. Unticking someone removes their line manager.</p>
      <ul className="max-h-72 divide-y divide-slate-100 overflow-y-auto rounded-lg border border-slate-200">
        {candidates.map((u) => (
          <li key={u.id}><label className="flex cursor-pointer items-center gap-3 px-3 py-2 text-sm">
            <input type="checkbox" className="h-4 w-4 accent-brand-600" checked={ids.includes(u.id)} onChange={() => setIds((s) => (s.includes(u.id) ? s.filter((x) => x !== u.id) : [...s, u.id]))} />
            <Avatar name={u.full_name} size={7} userId={u.id} v={u.avatar_v} /><span className="flex-1 truncate">{u.full_name}</span>
          </label></li>
        ))}
        {!candidates.length && <li className="px-3 py-4 text-center text-sm text-slate-500">No eligible employees</li>}
      </ul>
    </Modal>
  )
}

export default function ManagersPage() {
  const nav = useNavigate()
  const { data, isLoading, error, refetch } = useApi('/managers')
  const { data: branches } = useApi('/branches')
  const { data: depts } = useApi('/departments')
  const [edit, setEdit] = useState(null)
  const [team, setTeam] = useState(null)
  const [adding, setAdding] = useState(false)
  const bName = Object.fromEntries((branches?.items || []).map((b) => [b.id, b.name]))
  const dName = Object.fromEntries((depts?.items || []).map((d) => [d.id, d.name]))
  const byId = Object.fromEntries((data?.items || []).map((m) => [m.id, m]))
  return (
    <>
      <PageHeader title="Managers" description="Branch managers: teams, departments, reporting lines and permissions" actions={<Button onClick={() => setAdding(true)}>New manager</Button>} />
      {isLoading ? <PageLoader /> : error ? <ErrorState error={error} onRetry={refetch} /> : (
        <Table caption="Managers" rows={data.items} empty={<EmptyState title="No managers yet" description="Create a manager, then give them a branch and a team." action={<Button onClick={() => setAdding(true)}>New manager</Button>} />}
          columns={[
            { key: 'name', header: 'Manager', render: (m) => <button type="button" className="flex items-center gap-3 text-left" onClick={() => nav(`/employees/${m.id}`)}><Avatar name={m.full_name} userId={m.id} v={m.avatar_v} /><span><span className="block font-medium text-slate-900">{m.full_name}</span><span className="block text-xs text-slate-500">{m.email}</span></span></button> },
            { key: 'branch', header: 'Branch', render: (m) => bName[m.branch_id] || '—' },
            { key: 'dept', header: 'Department', render: (m) => dName[m.department_id] || '—' },
            { key: 'reports', header: 'Reports to', render: (m) => byId[m.reports_to]?.full_name || (m.reports_to ? 'Founder / HR' : '—') },
            { key: 'team', header: 'Team', render: (m) => `${m.team_size} people` },
            { key: 'perm', header: 'Permissions', render: (m) => `${m.permissions.length} of 4` },
            { key: 'actions', header: '', render: (m) => (
              <div className="flex gap-2"><Button size="sm" variant="secondary" onClick={() => setEdit(m)} aria-label={`Configure ${m.full_name}`}>Configure</Button>
                <Button size="sm" variant="secondary" onClick={() => setTeam(m)} aria-label={`Manage team of ${m.full_name}`}>Team</Button></div>) },
          ]} />
      )}
      <ManagerModal open={!!edit} onClose={() => setEdit(null)} manager={edit} />
      <TeamModal open={!!team} onClose={() => setTeam(null)} manager={team} />
      <EmployeeFormModal open={adding} onClose={() => setAdding(false)} defaultRole="manager" />
    </>
  )
}
