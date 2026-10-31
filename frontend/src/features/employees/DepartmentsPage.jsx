import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Alert, Avatar, Button, Card, ConfirmDialog, EmptyState, ErrorState, Field, FormSection, Input, Modal, PageHeader, PageLoader, Select, StatusBadge, Table, TableSkeleton, Tabs, Textarea } from '../../components/ui'
import { api, fieldErrors } from '../../lib/api'
import { fmtDate } from '../../lib/format'
import { useAction, useApi } from '../../lib/hooks'
import { useAuth } from '../auth/AuthContext'

const blankDept = { name: '', code: '', description: '', head_id: '', parent_id: '', cost_center: '', status: 'active' }
const toDeptForm = (d) => ({ name: d.name || '', code: d.code || '', description: d.description || '', head_id: d.head_id || '', parent_id: d.parent_id || '', cost_center: d.cost_center || '', status: d.status || 'active' })

function DeptModal({ dept, depts, onClose }) {
  const isNew = !dept?.id
  const base = isNew ? blankDept : toDeptForm(dept)
  const [f, setF] = useState(base)
  const { data: dir } = useApi('/employees/directory')
  const save = useAction(() => {
    const num = (v) => (v ? Number(v) : null)
    const body = { name: f.name.trim(), code: f.code.trim() || null, description: f.description.trim() || null, head_id: num(f.head_id), parent_id: num(f.parent_id), cost_center: f.cost_center.trim() || null, status: f.status }
    if (!isNew) Object.keys(body).forEach((k) => { if (String(f[k] ?? '') === String(base[k] ?? '')) delete body[k] })
    return isNew ? api.post('/departments', body) : api.patch(`/departments/${dept.id}`, body)
  }, { invalidate: ['/departments'], success: 'Department saved', onSuccess: onClose })
  const fe = fieldErrors(save.error)
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }))
  const dirty = JSON.stringify(f) !== JSON.stringify(base)
  const parents = (depts || []).filter((d) => d.id !== dept?.id)
  return (
    <Modal open onClose={onClose} wide title={isNew ? 'New department' : `Edit ${dept.name}`}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={save.isPending} disabled={!dirty || !f.name.trim()} onClick={() => save.mutate()}>{isNew ? 'Create department' : 'Save changes'}</Button></>}>
      <form className="space-y-5" onSubmit={(e) => { e.preventDefault(); if (dirty && f.name.trim()) save.mutate() }}>
        {save.error && !Object.keys(fe).length && <Alert>{save.error.message}</Alert>}
        <FormSection title="General information">
          <Field label="Department name" required error={fe.name}><Input value={f.name} onChange={set('name')} minLength={2} maxLength={120} required /></Field>
          <Field label="Department code" error={fe.code} hint="Short unique code such as ENG. Letters, digits, - and _"><Input value={f.code} onChange={set('code')} maxLength={20} /></Field>
          <div className="sm:col-span-2"><Field label="Description" error={fe.description}><Textarea rows={2} maxLength={1000} value={f.description} onChange={set('description')} /></Field></div>
        </FormSection>
        <FormSection title="Organisational assignment">
          <Field label="Department head" error={fe.head_id}><Select value={f.head_id} onChange={set('head_id')}><option value="">No head</option>{dir?.items.map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}</Select></Field>
          <Field label="Parent department" error={fe.parent_id} hint="Leave empty for a top-level department"><Select value={f.parent_id} onChange={set('parent_id')}><option value="">None</option>{parents.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</Select></Field>
          <Field label="Cost centre" error={fe.cost_center}><Input value={f.cost_center} onChange={set('cost_center')} maxLength={40} /></Field>
          <Field label="Status" error={fe.status} hint="Inactive departments cannot receive new people"><Select value={f.status} onChange={set('status')}><option value="active">Active</option><option value="inactive">Inactive</option></Select></Field>
        </FormSection>
        {!isNew && <p className="text-xs text-slate-500">Created {fmtDate(dept.created_at)} · {dept.employee_count} active employee{dept.employee_count === 1 ? '' : 's'} (calculated)</p>}
      </form>
    </Modal>
  )
}

function OrgNode({ node, byManager, depth = 0 }) {
  const kids = byManager[node.id] || []
  return (
    <li>
      <div className="flex items-center gap-2 py-1.5" style={{ paddingLeft: depth * 24 }}>
        {depth > 0 && <span className="text-slate-300" aria-hidden>└</span>}
        <Avatar name={node.full_name} size={7} />
        <span className="text-sm"><span className="font-medium">{node.full_name}</span> <span className="text-slate-500">· {node.designation || node.role}</span></span>
      </div>
      {kids.length > 0 && <ul>{kids.map((k) => <OrgNode key={k.id} node={k} byManager={byManager} depth={depth + 1} />)}</ul>}
    </li>
  )
}

function OrgChart() {
  const { data } = useApi('/employees/directory')
  const { byManager, roots } = useMemo(() => {
    const items = data?.items || []
    const ids = new Set(items.map((i) => i.id))
    const by = {}
    items.forEach((i) => { if (i.manager_id && ids.has(i.manager_id)) (by[i.manager_id] ||= []).push(i) })
    return { byManager: by, roots: items.filter((i) => !i.manager_id || !ids.has(i.manager_id)) }
  }, [data])
  if (!data) return <PageLoader />
  return <Card title="Reporting hierarchy"><ul>{roots.map((r) => <OrgNode key={r.id} node={r} byManager={byManager} />)}</ul></Card>
}

export default function DepartmentsPage() {
  const { role } = useAuth()
  const canEdit = role === 'hr' || role === 'founder'
  const [tab, setTab] = useState('depts')
  const [edit, setEdit] = useState(null)
  const [removing, setRemoving] = useState(null)
  const { data, isLoading, error, refetch } = useApi('/departments')
  const del = useAction((d) => api.del(`/departments/${d.id}`), { invalidate: ['/departments'], success: 'Department deleted', onSuccess: () => setRemoving(null) })
  return (
    <>
      <PageHeader title="Organization" description="Departments and reporting hierarchy" actions={canEdit && <Button onClick={() => setEdit({})}>New department</Button>} />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: 'depts', label: 'Departments' }, { id: 'org', label: 'Org chart' }]} />
      {tab === 'org' ? <OrgChart /> : isLoading ? <TableSkeleton cols={6} /> : error ? <ErrorState error={error} onRetry={refetch} /> : (
        <Table caption="Departments" rows={data.items} empty={<EmptyState title="No departments" description="Create departments to organise employees." action={canEdit && <Button onClick={() => setEdit({})}>New department</Button>} />}
          columns={[
            { key: 'name', header: 'Department', render: (d) => <div><p className="font-medium text-slate-900">{d.name}</p>{d.parent_name && <p className="text-xs text-slate-500">Under {d.parent_name}</p>}</div> },
            { key: 'code', header: 'Code', render: (d) => d.code ? <span className="font-mono text-xs">{d.code}</span> : '—' },
            { key: 'head', header: 'Head', render: (d) => d.head_name || '—' },
            { key: 'employee_count', header: 'Employees', render: (d) => canEdit ? <Link className="text-brand-700 hover:underline" to={`/employees?department_id=${d.id}`}>{d.employee_count}</Link> : d.employee_count },
            { key: 'status', header: 'Status', render: (d) => <StatusBadge value={d.status} /> },
            ...(canEdit ? [{ key: 'act', header: '', render: (d) => <div className="flex gap-3"><button className="text-brand-700 hover:underline" onClick={() => setEdit(d)}>Edit</button><button className="text-red-600 hover:underline" onClick={() => setRemoving(d)}>Delete</button></div> }] : []),
          ]} />
      )}
      {edit && <DeptModal dept={edit} depts={data?.items} onClose={() => setEdit(null)} />}
      <ConfirmDialog open={!!removing} danger title="Delete department" confirmLabel="Delete" loading={del.isPending} onClose={() => setRemoving(null)} onConfirm={() => del.mutate(removing)}
        message={`Delete ${removing?.name}? A department with employees or sub-departments cannot be deleted; mark it inactive instead.`} />
    </>
  )
}
