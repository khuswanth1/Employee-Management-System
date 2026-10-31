import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Alert, Avatar, Button, ConfirmDialog, EmptyState, ErrorState, Field, Input, Modal, PageHeader, Pagination, SearchInput, Select, StatusBadge, Table, TableSkeleton } from '../../components/ui'
import { api, fieldErrors } from '../../lib/api'
import { toAvatarFile } from '../../lib/avatar'
import { ROLE_LABEL } from '../../lib/format'
import { useAction, useApi, useDebounce } from '../../lib/hooks'
import { usePersistentState } from '../../lib/usePersistentState'
import { useAuth } from '../auth/AuthContext'
import EmployeeDirectory from './EmployeeDirectory'
import EmployeeEditModal from './EmployeeEditModal'

export function EmployeeFormModal({ open, onClose, defaultRole = 'employee' }) {
  const { role } = useAuth()
  const nav = useNavigate()
  const { data: depts } = useApi('/departments')
  const { data: dir } = useApi('/employees/directory')
  const { data: branches } = useApi('/branches', null, { enabled: open })
  const blank = { full_name: '', email: '', password: '', role: defaultRole, department_id: '', manager_id: '', designation: '', phone: '', employee_code: '', branch_id: '', location: '', hire_date: '' }
  const [f, setF] = useState(blank)
  const [photo, setPhoto] = useState(null) // { file, url }
  const [photoError, setPhotoError] = useState(null)
  const fileRef = useRef(null)
  useEffect(() => { if (open) setF((s) => ({ ...s, role: defaultRole })) }, [open, defaultRole]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => { if (photo) URL.revokeObjectURL(photo.url) }, [photo])
  const pickPhoto = (e) => {
    const file = e.target.files?.[0]; e.target.value = ''
    if (!file) return
    setPhotoError(null)
    if (!/^image\/(jpeg|png|webp)$/.test(file.type)) { setPhotoError('Please choose a JPEG, PNG or WebP image'); return }
    setPhoto({ file, url: URL.createObjectURL(file) })
  }
  const create = useAction(async () => {
    const u = await api.post('/employees', { ...f, department_id: f.department_id ? Number(f.department_id) : null, manager_id: f.manager_id ? Number(f.manager_id) : null, designation: f.designation || null, phone: f.phone || null, employee_code: f.employee_code || null, location: f.location || null, hire_date: f.hire_date || null, ...(role === 'founder' && f.branch_id ? { branch_id: Number(f.branch_id) } : { branch_id: undefined }) })
    if (photo) {  // the account exists now; a failed photo upload must not hide that
      try { await api.upload(`/employees/${u.id}/avatar`, await toAvatarFile(photo.file)) } catch { u.photoFailed = true }
    }
    return u
  }, {
    invalidate: ['/employees', '/departments', '/dashboard', '/managers', '/branches'],
    success: (u) => (u.photoFailed ? 'Employee created, but the photo could not be uploaded. Add it from their profile.' : 'Employee created'),
    onSuccess: (u) => { onClose(); setF(blank); setPhoto(null); nav(`/employees/${u.id}`) },
  })
  const fe = fieldErrors(create.error)
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }))
  return (
    <Modal open={open} onClose={onClose} wide title="Add employee" footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={create.isPending} onClick={() => create.mutate()}>Create employee</Button></>}>
      <form className="grid gap-4 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); create.mutate() }}>
        {create.error && !Object.keys(fe).length && <div className="sm:col-span-2"><Alert>{create.error.message}</Alert></div>}
        <div className="flex items-center gap-4 sm:col-span-2">
          {photo ? <img src={photo.url} alt="Selected photo preview" className="h-16 w-16 rounded-full object-cover ring-2 ring-brand-500" /> : <span aria-hidden className="flex h-16 w-16 items-center justify-center rounded-full bg-slate-100 text-xs text-slate-500">Photo</span>}
          <div className="space-y-1">
            <div className="flex gap-2">
              <Button type="button" size="sm" variant="secondary" onClick={() => fileRef.current?.click()}>{photo ? 'Change photo' : 'Upload photo'}</Button>
              {photo && <Button type="button" size="sm" variant="ghost" onClick={() => setPhoto(null)}>Remove</Button>}
            </div>
            <p className="text-xs text-slate-500">Optional. JPEG, PNG or WebP; cropped to a square.</p>
            {photoError && <p role="alert" className="text-xs text-red-600">{photoError}</p>}
            <input ref={fileRef} type="file" accept="image/jpeg,image/png,image/webp" className="sr-only" aria-label="Employee photo" onChange={pickPhoto} />
          </div>
        </div>
        <Field label="Full name" required error={fe.full_name}><Input value={f.full_name} onChange={set('full_name')} required /></Field>
        <Field label="Work email" required error={fe.email}><Input type="email" value={f.email} onChange={set('email')} required autoComplete="off" /></Field>
        <Field label="Temporary password" required error={fe.password} hint="4 to 12 characters. The employee can change it after signing in."><Input type="password" minLength={4} maxLength={12} value={f.password} onChange={set('password')} autoComplete="new-password" required /></Field>
        <Field label="Role" error={fe.role}>
          <Select value={f.role} onChange={set('role')}>{(role === 'founder' ? ['employee', 'manager', 'hr', 'founder'] : role === 'manager' ? ['employee', 'hr'] : ['employee']).map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}</Select>
        </Field>
        <Field label="Department"><Select value={f.department_id} onChange={set('department_id')}><option value="">None</option>{depts?.items.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</Select></Field>
        {role !== 'manager' && <Field label="Reports to"><Select value={f.manager_id} onChange={set('manager_id')}><option value="">No manager</option>{dir?.items.map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}</Select></Field>}
        <Field label="Designation"><Input value={f.designation} onChange={set('designation')} /></Field>
        <Field label="Phone"><Input value={f.phone} onChange={set('phone')} type="tel" /></Field>
        <Field label="Employee ID" error={fe.employee_code} hint="Leave blank to generate (EMP-0001)"><Input value={f.employee_code} onChange={set('employee_code')} maxLength={20} /></Field>
        <Field label="Joining date" error={fe.hire_date}><Input type="date" value={f.hire_date} onChange={set('hire_date')} /></Field>
        {role === 'founder' && <Field label="Branch" error={fe.branch_id}><Select value={f.branch_id} onChange={set('branch_id')}><option value="">No branch</option>{branches?.items.filter((b) => b.is_active).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</Select></Field>}
        <Field label="Work location" error={fe.location} hint="Defaults to the branch city"><Input value={f.location} onChange={set('location')} maxLength={120} /></Field>
      </form>
    </Modal>
  )
}

function StaffEmployeesPage() {
  const nav = useNavigate()
  const [q, setQ] = usePersistentState('employees.q', '')
  const [params] = useSearchParams()
  const [saved, setF] = usePersistentState('employees.filters', { department_id: '', role: '', status: '', branch_id: '' })
  const f = params.get('department_id') ? { ...saved, department_id: params.get('department_id') } : saved
  const [page, setPage] = useState(1)
  const [sort, setSort] = usePersistentState('employees.sort', { key: 'full_name', order: 'asc' })
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState(null)
  const [confirmApprove, setConfirmApprove] = useState(null)
  const [confirmDelete, setConfirmDelete] = useState(null)
  const { user: me, role: myRole } = useAuth()
  const dq = useDebounce(q)
  const { data: depts } = useApi('/departments')
  const { data: branches } = useApi('/branches')
  const bName = Object.fromEntries((branches?.items || []).map((b) => [b.id, b.name]))
  const { data, isLoading, error, refetch } = useApi('/employees', { q: dq, ...f, sort: sort.key, order: sort.order, page, page_size: 15 })
  const deptName = Object.fromEntries((depts?.items || []).map((d) => [d.id, d.name]))
  const onSort = (key) => { setSort((s) => ({ key, order: s.key === key && s.order === 'asc' ? 'desc' : 'asc' })); setPage(1) }
  const flt = (k) => (e) => { setF({ ...f, [k]: e.target.value }); setPage(1) }

  const canManage = (u) => {
    if (u.id === me?.id) return false
    if (myRole === 'founder') return true
    if (myRole === 'hr') return !['founder', 'board_member'].includes(u.role)
    if (myRole === 'manager') return u.manager_id === me?.id || ['employee', 'hr'].includes(u.role)
    return false
  }

  const approveAction = useAction((emp) => api.post(`/employees/${emp.id}/approve`), {
    invalidate: ['/employees', '/departments', '/dashboard'],
    success: 'Employee approved. Account is now active.',
    onSuccess: () => setConfirmApprove(null),
  })
  const deleteAction = useAction(async (emp) => {
    if (emp.status === 'pending_approval') {
      return api.post(`/employees/${emp.id}/reject`)
    }
    try {
      return await api.del(`/employees/${emp.id}`)
    } catch (err) {
      if (err.status === 409 || err.message?.toLowerCase().includes('offboard')) {
        return await api.post(`/employees/${emp.id}/offboard`)
      }
      throw err
    }
  }, {
    invalidate: ['/employees', '/departments', '/dashboard', '/teams', '/projects'],
    success: (r, emp) => (emp?.status === 'pending_approval' ? 'Pending joining deleted' : 'Employee removed successfully'),
    onSuccess: () => setConfirmDelete(null),
  })

  return (
    <>
      <PageHeader
        title="Employees"
        description={myRole === 'manager' ? 'Your direct reports. New employees you add report to you.' : 'Profiles, reporting lines and lifecycle'}
        actions={['founder', 'hr', 'manager'].includes(myRole) ? <Button onClick={() => setAdding(true)}>+ Add employee</Button> : null}
      />
      <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-12">
        <div className="sm:col-span-3">
          <SearchInput value={q} onChange={(v) => { setQ(v); setPage(1) }} placeholder="Search name or email" />
        </div>
        <div className="sm:col-span-2">
          <Select aria-label="Department" value={f.department_id} onChange={flt('department_id')}>
            <option value="">All departments</option>
            {depts?.items.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </Select>
        </div>
        {branches?.items.length > 0 && (
          <div className="sm:col-span-2">
            <Select aria-label="Branch" value={f.branch_id} onChange={flt('branch_id')}>
              <option value="">All branches</option>
              {branches.items.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
            </Select>
          </div>
        )}
        <div className="sm:col-span-2">
          <Select aria-label="Role" value={f.role} onChange={flt('role')}>
            <option value="">All roles</option>
            {['hr', 'manager', 'employee'].map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
          </Select>
        </div>
        <div className="sm:col-span-2">
          <Select aria-label="Status" value={f.status} onChange={flt('status')}>
            <option value="">All statuses</option>
            {['pending_approval', 'onboarding', 'active', 'offboarded'].map((s) => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}
          </Select>
        </div>
        {(q || f.department_id || f.role || f.status || f.branch_id) && (
          <div className="flex items-center sm:col-span-3">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => { setQ(''); setF({ department_id: '', role: '', status: '', branch_id: '' }); setPage(1) }}>
              Clear filters
            </Button>
          </div>
        )}
      </div>
      {isLoading ? <TableSkeleton cols={6} /> : error ? <ErrorState error={error} onRetry={refetch} /> : (
        <>
          <Table caption="Employees" sort={sort} onSort={onSort} rows={data.items} onRowClick={(u) => nav(`/employees/${u.id}`)} empty={<EmptyState title="No employees match" description="Try different filters or add a new employee." />}
            columns={[
              { key: 'name', header: 'Employee', sortKey: 'full_name', render: (u) => <div className="flex items-center gap-3"><Avatar name={u.full_name} userId={u.id} v={u.avatar_v} /><div><p className="font-medium text-slate-900">{u.full_name}</p><p className="text-xs text-slate-500">{u.email}</p></div></div> },
              { key: 'designation', header: 'Designation', render: (u) => u.designation || '—' },
              { key: 'code', header: 'ID', sortKey: 'employee_code', render: (u) => <span className="font-mono text-xs">{u.employee_code || '—'}</span> },
              { key: 'dept', header: 'Department', render: (u) => deptName[u.department_id] || '—' },
              { key: 'branch', header: 'Branch', render: (u) => bName[u.branch_id] || '—' },
              { key: 'role', header: 'Role', sortKey: 'role', render: (u) => ROLE_LABEL[u.role] },
              { key: 'status', header: 'Status', sortKey: 'status', render: (u) => <StatusBadge value={u.status} /> },
              { key: 'actions', header: 'Actions', className: 'text-right whitespace-nowrap', render: (u) => {
                if (!canManage(u)) return null
                if (u.status === 'pending_approval') {
                  return (
                    <div className="flex items-center justify-end gap-2" onClick={(e) => e.stopPropagation()}>
                      <Button size="sm" onClick={() => setConfirmApprove(u)}>Approve</Button>
                      <Button size="sm" variant="danger" onClick={() => setConfirmDelete(u)}>Delete</Button>
                    </div>
                  )
                }
                return (
                  <div className="flex items-center justify-end gap-2" onClick={(e) => e.stopPropagation()}>
                    <Button size="sm" variant="secondary" onClick={() => setEditing(u)}>
                      Edit
                    </Button>
                    {u.status !== 'offboarded' && (
                      <Button size="sm" variant="danger" onClick={() => setConfirmDelete(u)}>
                        Delete
                      </Button>
                    )}
                  </div>
                )
              }},
            ]} />
          <Pagination page={data.page} pageSize={data.page_size} total={data.total} onChange={setPage} />
        </>
      )}
      {editing && <EmployeeEditModal employee={editing} onClose={() => setEditing(null)} />}
      <EmployeeFormModal open={adding} onClose={() => setAdding(false)} />
      {confirmApprove && (
        <ConfirmDialog
          open
          title="Approve and confirm employee"
          confirmLabel="Approve"
          loading={approveAction.isPending}
          onClose={() => setConfirmApprove(null)}
          onConfirm={() => approveAction.mutate(confirmApprove)}
          message={`Approve and confirm ${confirmApprove.full_name}? The account will become active and they will be able to sign in.`}
        />
      )}
      {confirmDelete && (
        <ConfirmDialog
          open
          danger
          title={confirmDelete.status === 'pending_approval' ? 'Delete pending joining' : 'Delete or offboard employee'}
          confirmLabel="Delete"
          loading={deleteAction.isPending}
          onClose={() => setConfirmDelete(null)}
          onConfirm={() => deleteAction.mutate(confirmDelete)}
          message={
            confirmDelete.status === 'pending_approval'
              ? `Delete pending joining for ${confirmDelete.full_name}? This pending account is removed permanently.`
              : `Delete ${confirmDelete.full_name}? If they have active work history, they will be safely offboarded and deactivated. If they have no work history, their account will be permanently deleted.`
          }
        />
      )}
    </>
  )
}

// People who administer records get the management page; everyone else gets the read-only directory.
export default function EmployeesPage() {
  const { user, role } = useAuth()
  const manages = role === 'founder' || role === 'hr' || (role === 'manager' && (!user.permissions || user.permissions.includes('employees.manage')))
  return manages ? <StaffEmployeesPage /> : <EmployeeDirectory />
}
