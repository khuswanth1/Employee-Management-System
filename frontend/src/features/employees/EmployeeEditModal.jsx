import { useEffect, useState } from 'react'
import { Alert, Button, Field, Input, Modal, Select } from '../../components/ui'
import { api, fieldErrors } from '../../lib/api'
import { ROLE_LABEL } from '../../lib/format'
import { useAction, useApi } from '../../lib/hooks'
import { useAuth } from '../auth/AuthContext'

const toForm = (u) => ({
  full_name: u.full_name || '', designation: u.designation || '', department_id: u.department_id || '', manager_id: u.manager_id || '', role: u.role,
  phone: u.phone || '', employee_code: u.employee_code || '', branch_id: u.branch_id || '', location: u.location || '', hire_date: u.hire_date || '',
})

/** Quick edit of an employee's record from the list. Same rules as the profile page; the server enforces them. */
export default function EmployeeEditModal({ employee, onClose }) {
  const { role } = useAuth()
  const [f, setF] = useState(() => toForm(employee))
  const { data: depts } = useApi('/departments')
  const { data: dir } = useApi('/employees/directory')
  const { data: branches } = useApi('/branches')
  useEffect(() => setF(toForm(employee)), [employee])
  const base = toForm(employee)
  const founder = role === 'founder'
  const lockedRole = !founder || employee.role === 'board_member'
  const lockedBranch = !founder || ['founder', 'board_member'].includes(employee.role)

  const save = useAction(() => {
    const num = (v) => (v ? Number(v) : null)
    const all = {
      full_name: f.full_name, designation: f.designation || null, department_id: num(f.department_id), manager_id: num(f.manager_id), role: f.role,
      phone: f.phone || null, employee_code: f.employee_code || null, branch_id: num(f.branch_id), location: f.location || null, hire_date: f.hire_date || null,
    }
    const body = {}
    Object.keys(all).forEach((k) => { if (String(f[k] ?? '') !== String(base[k] ?? '')) body[k] = all[k] })
    if (body.employee_code === null) delete body.employee_code // the server keeps the current ID when blank
    if (body.hire_date === null) delete body.hire_date
    return api.patch(`/employees/${employee.id}`, body)
  }, { invalidate: ['/employees', '/departments', '/dashboard', '/managers', '/branches', '/teams'], success: 'Employee updated', onSuccess: onClose })

  const fe = fieldErrors(save.error)
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }))
  const dirty = JSON.stringify(f) !== JSON.stringify(base)
  return (
    <Modal open onClose={onClose} wide title={`Edit ${employee.full_name}`}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={save.isPending} disabled={!dirty} onClick={() => save.mutate()}>Save changes</Button></>}>
      <form className="grid gap-4 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); if (dirty) save.mutate() }}>
        {save.error && !Object.keys(fe).length && <div className="sm:col-span-2"><Alert>{save.error.message}</Alert></div>}
        <Field label="Full name" required error={fe.full_name}><Input value={f.full_name} onChange={set('full_name')} required /></Field>
        <Field label="Designation"><Input value={f.designation} onChange={set('designation')} /></Field>
        <Field label="Department"><Select value={f.department_id} onChange={set('department_id')}><option value="">None</option>{depts?.items.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</Select></Field>
        <Field label="Reports to" error={fe.manager_id}><Select value={f.manager_id} onChange={set('manager_id')}><option value="">No manager</option>{dir?.items.filter((x) => x.id !== employee.id).map((x) => <option key={x.id} value={x.id}>{x.full_name}</option>)}</Select></Field>
        <Field label="Role" error={fe.role} hint={lockedRole ? 'Only a founder can change roles' : undefined}>
          <Select value={f.role} onChange={set('role')} disabled={lockedRole}>{(founder && employee.role !== 'board_member' ? ['employee', 'manager', 'hr', 'founder'] : [employee.role]).map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}</Select>
        </Field>
        <Field label="Phone"><Input type="tel" value={f.phone} onChange={set('phone')} /></Field>
        <Field label="Employee ID" error={fe.employee_code}><Input value={f.employee_code} onChange={set('employee_code')} maxLength={20} /></Field>
        <Field label="Branch" error={fe.branch_id} hint={lockedBranch ? 'Only a founder can change branches' : undefined}>
          <Select value={f.branch_id} onChange={set('branch_id')} disabled={lockedBranch}><option value="">No branch</option>{branches?.items.filter((b) => b.is_active || b.id === employee.branch_id).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</Select>
        </Field>
        <Field label="Work location" error={fe.location}><Input value={f.location} onChange={set('location')} maxLength={120} /></Field>
        <Field label="Joining date" error={fe.hire_date}><Input type="date" value={f.hire_date} onChange={set('hire_date')} /></Field>
      </form>
    </Modal>
  )
}
