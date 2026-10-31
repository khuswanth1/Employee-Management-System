import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Alert, Avatar, Badge, Button, Card, ConfirmDialog, EmptyState, ErrorState, Field, Input, Modal, PageHeader, PageLoader, Select, StatusBadge, Tabs } from '../../components/ui'
import { api, fieldErrors } from '../../lib/api'
import { toAvatarFile } from '../../lib/avatar'
import { fmtDate, label, ROLE_LABEL } from '../../lib/format'
import { useAction, useApi } from '../../lib/hooks'
import { useAuth } from '../auth/AuthContext'
import LifecycleTab from './LifecycleTab'
import { DocumentsTab, EmploymentTab, PersonalTab } from './ProfileTabs'

function ResetPassword({ id, onClose }) {
  const [pw, setPw] = useState('')
  const reset = useAction(() => api.post(`/employees/${id}/reset-password`, { new_password: pw }), { success: 'Password reset', onSuccess: onClose })
  const fe = fieldErrors(reset.error)
  return (
    <Modal open onClose={onClose} title="Reset password" footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={reset.isPending} onClick={() => reset.mutate()}>Reset</Button></>}>
      <Field label="New temporary password" required error={fe.new_password} hint="4 to 12 characters"><Input type="password" minLength={4} maxLength={12} autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} /></Field>
    </Modal>
  )
}

function usePhoto(id, invalidate) {
  const up = useAction(async (file) => api.upload(`/employees/${id}/avatar`, await toAvatarFile(file)), { invalidate, success: 'Photo updated' })
  const del = useAction(() => api.del(`/employees/${id}/avatar`), { invalidate, success: 'Photo removed' })
  return { up, del }
}

/** Photo with preview-before-upload, replace and remove (HR in their branch / founders). */
function PhotoEditor({ u, canEdit, photo }) {
  const input = useRef(null)
  const [preview, setPreview] = useState(null) // { file, url }
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview.url) }, [preview])
  const pick = (e) => { const file = e.target.files?.[0]; e.target.value = ''; if (file) setPreview({ file, url: URL.createObjectURL(file) }) }
  return (
    <div className="flex items-center gap-3">
      {preview ? <img src={preview.url} alt="Selected photo preview" className="h-16 w-16 rounded-full object-cover ring-2 ring-brand-500" /> : <Avatar name={u.full_name} size={16} userId={u.id} v={u.avatar_v} />}
      {canEdit && (
        <div className="space-y-1.5">
          {preview ? (
            <div className="flex gap-2">
              <Button size="sm" loading={photo.up.isPending} onClick={() => photo.up.mutate(preview.file, { onSuccess: () => setPreview(null) })}>Save photo</Button>
              <Button size="sm" variant="secondary" onClick={() => setPreview(null)}>Cancel</Button>
            </div>
          ) : (
            <div className="flex gap-2">
              <Button size="sm" variant="secondary" onClick={() => input.current?.click()}>{u.avatar_v ? 'Change photo' : 'Upload photo'}</Button>
              {u.avatar_v && <Button size="sm" variant="ghost" loading={photo.del.isPending} onClick={() => photo.del.mutate()}>Remove</Button>}
            </div>
          )}
          <input ref={input} type="file" accept="image/jpeg,image/png,image/webp" className="sr-only" aria-label="Employee photo" onChange={pick} />
        </div>
      )}
    </div>
  )
}

const toForm = (u) => ({ branch_id: u.branch_id || '', location: u.location || '', employee_code: u.employee_code || '',  full_name: u.full_name, designation: u.designation || '', phone: u.phone || '', department_id: u.department_id || '', manager_id: u.manager_id || '', role: u.role, hire_date: u.hire_date || '' })

export default function EmployeeDetailPage() {
  const { id } = useParams()
  const { user: me, role } = useAuth()
  const [dialog, setDialog] = useState(null)
  const [tab, setTab] = useState('overview')
  const { data: u, isLoading, error, refetch } = useApi(`/employees/${id}`)
  const canAdmin = role === 'founder' || role === 'hr' || (role === 'manager' && (u?.manager_id === me?.id || ['employee', 'hr'].includes(u?.role)))
  const { data: depts } = useApi('/departments')
  const { data: dir } = useApi('/employees/directory')
  const { data: checklist } = useApi(`/employees/${id}/checklist`)
  const { data: profile } = useApi(`/employees/${id}/profile`)
  const { data: branches } = useApi('/branches')
  const [f, setF] = useState(null)
  useEffect(() => { if (u) setF(toForm(u)) }, [u])

  const inv = ['/employees', '/departments', '/dashboard']
  const save = useAction(() => api.patch(`/employees/${id}`, { ...f, department_id: f.department_id ? Number(f.department_id) : null, ...(role === 'founder' ? { branch_id: f.branch_id ? Number(f.branch_id) : null } : { branch_id: undefined }), location: f.location || null, employee_code: f.employee_code || undefined, manager_id: f.manager_id ? Number(f.manager_id) : null, hire_date: f.hire_date || null, designation: f.designation || null, phone: f.phone || null }), { invalidate: inv, success: 'Profile saved' })
  const nav = useNavigate()
  const photo = usePhoto(id, inv)
  const dirty = !!f && !!u && JSON.stringify(f) !== JSON.stringify(toForm(u))
  const activate = useAction(() => api.patch(`/employees/${id}`, { status: 'active' }), { invalidate: [...inv, `/employees/${id}`], success: 'Employee activated', onSuccess: () => setDialog(null) })
  const resetMfa = useAction(() => api.post(`/employees/${id}/mfa/reset`), { success: 'Two-step verification reset', onSuccess: () => setDialog(null) })
  const approve = useAction(() => api.post(`/employees/${id}/approve`), { invalidate: [...inv, `/employees/${id}`], success: 'Joining approved. The account is now active.', onSuccess: () => setDialog(null) })
  const reject = useAction(() => api.post(`/employees/${id}/reject`), { invalidate: inv, success: 'Pending joining deleted', onSuccess: () => nav('/employees') })
  const delEmp = useAction(async () => {
    if (u?.status === 'pending_approval') {
      return api.post(`/employees/${id}/reject`)
    }
    try {
      return await api.del(`/employees/${id}`)
    } catch (err) {
      if (err.status === 409 || err.message?.toLowerCase().includes('offboard')) {
        return await api.post(`/employees/${id}/offboard`)
      }
      throw err
    }
  }, {
    invalidate: inv,
    success: 'Employee removed successfully',
    onSuccess: () => nav('/employees'),
  })
  const tick = useAction(({ item, done }) => api.patch(`/checklist/${item.id}`, { done }), { invalidate: [`/employees/${id}`, '/employees'] })

  if (isLoading || !f) return <PageLoader />
  if (error) return <ErrorState error={error} onRetry={refetch} />
  const fe = fieldErrors(save.error)
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }))
  const locked = !canAdmin || (['founder', 'board_member'].includes(u.role) && role !== 'founder')
  const tabs = [
    { id: 'overview', label: 'Overview' }, { id: 'employment', label: 'Employment' },
    ...(profile?.can_view_restricted ? [{ id: 'personal', label: 'Personal' }] : []),
    ...(canAdmin || me.id === u.id ? [{ id: 'documents', label: 'Documents' }] : []),
    { id: 'history', label: 'History' },
    { id: 'team', label: 'Team & projects' },
  ]

  return (
    <>
      <PageHeader title={u.full_name} description={`${ROLE_LABEL[u.role]} · ${u.email}`}
        actions={<>
          <StatusBadge value={u.status} />
          {u.status === 'pending_approval' && (canAdmin ? !locked : role === 'manager') && <>
            <Button loading={approve.isPending} onClick={() => setDialog('approve')}>Approve</Button>
            <Button variant="danger" onClick={() => setDialog('reject')}>Delete</Button>
          </>}
          {canAdmin && u.status === 'onboarding' && !locked && <Button onClick={() => setDialog('activate')}>Activate</Button>}
          {canAdmin && u.status !== 'offboarded' && u.status !== 'pending_approval' && u.id !== me.id && !locked && <>
            <Button variant="secondary" onClick={() => setDialog('reset')}>Reset password</Button>
            <Button variant="secondary" onClick={() => setDialog('mfa')}>Reset two-step</Button>
            <Button variant="danger" onClick={() => setDialog('delete')}>Delete</Button>
          </>}
        </>} />
      <Tabs value={tab} onChange={setTab} tabs={tabs} />
      {tab === 'employment' && profile && <EmploymentTab id={id} profile={profile} hireDate={u.hire_date} canEditAll={profile.can_edit_employment && !locked} canEditOwn={me.id === u.id} />}
      {tab === 'history' && <LifecycleTab id={id} user={u} />}
      {tab === 'personal' && profile?.can_view_restricted && <PersonalTab id={id} profile={profile} canEdit={me.id === u.id || (canAdmin && !locked)} />}
      {tab === 'documents' && <DocumentsTab id={id} canUpload={canAdmin || me.id === u.id} canAdmin={canAdmin && !locked} isSelf={me.id === u.id} />}
      {tab === 'overview' && <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Profile" className="lg:col-span-2">
          <div className="mb-5 flex flex-wrap items-center gap-4"><PhotoEditor u={u} canEdit={canAdmin && !locked} photo={photo} /><div><p className="font-semibold">{u.full_name} <span className="font-mono text-xs font-normal text-slate-500">{u.employee_code}</span></p><p className="text-sm text-slate-500">Joined {fmtDate(u.hire_date)}</p></div></div>
          {save.error && !Object.keys(fe).length && <div className="mb-4"><Alert>{save.error.message}</Alert></div>}
          <form className="grid gap-4 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
            <Field label="Full name" error={fe.full_name}><Input value={f.full_name} onChange={set('full_name')} disabled={locked} /></Field>
            <Field label="Designation"><Input value={f.designation} onChange={set('designation')} disabled={locked} /></Field>
            <Field label="Department"><Select value={f.department_id} onChange={set('department_id')} disabled={locked}><option value="">None</option>{depts?.items.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</Select></Field>
            <Field label="Reports to"><Select value={f.manager_id} onChange={set('manager_id')} disabled={locked}><option value="">No manager</option>{dir?.items.filter((x) => x.id !== u.id).map((x) => <option key={x.id} value={x.id}>{x.full_name}</option>)}</Select></Field>
            <Field label="Role"><Select value={f.role} onChange={set('role')} disabled={locked}>{(role === 'founder' ? ['employee', 'manager', 'hr', 'founder'] : [u.role]).map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}</Select></Field>
            <Field label="Phone"><Input value={f.phone} onChange={set('phone')} disabled={locked} /></Field>
            <Field label="Employee ID" error={fe.employee_code}><Input value={f.employee_code} onChange={set('employee_code')} disabled={locked} maxLength={20} /></Field>
            <Field label="Branch" error={fe.branch_id} hint={role === 'founder' ? undefined : 'Only a founder can change branches'}><Select value={f.branch_id} onChange={set('branch_id')} disabled={locked || role !== 'founder' || ['founder', 'board_member'].includes(u.role)}><option value="">No branch</option>{branches?.items.filter((b) => b.is_active || b.id === u.branch_id).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</Select></Field>
            <Field label="Work location" error={fe.location}><Input value={f.location} onChange={set('location')} disabled={locked} maxLength={120} /></Field>
            <Field label="Hire date"><Input type="date" value={f.hire_date} onChange={set('hire_date')} disabled={locked} /></Field>
            {!locked && <div className="flex items-end gap-2"><Button type="submit" loading={save.isPending} disabled={!dirty}>Save changes</Button><Button type="button" variant="secondary" disabled={!dirty || save.isPending} onClick={() => setF(toForm(u))}>Cancel</Button></div>}
          </form>
        </Card>
        <div className="space-y-6">
          <Card title="Onboarding & offboarding checklist" pad={false}>
            {!checklist?.items.length ? <div className="p-5 text-sm text-slate-500">No checklist items</div> : (
              <ul className="divide-y divide-slate-100">{checklist.items.map((c) => (
                <li key={c.id} className="flex items-center gap-3 px-5 py-2.5 text-sm">
                  <input type="checkbox" className="h-4 w-4 accent-brand-600" checked={c.done} disabled={!canAdmin} aria-label={c.title} onChange={(e) => tick.mutate({ item: c, done: e.target.checked })} />
                  <span className={c.done ? 'text-slate-500 line-through' : ''}>{c.title}</span><span className="ml-auto text-xs text-slate-500">{c.kind}</span>
                </li>))}</ul>
            )}
          </Card>
        </div>
      </div>}

      {tab === 'team' && (u.team ? (
          <Card title="Team & Allocated Projects" className="lg:col-span-3">
            <div className="flex flex-wrap items-center justify-between gap-3 pb-4 border-b border-slate-100">
              <div className="flex items-center gap-3">
                <div className="rounded-lg bg-brand-50 border border-brand-200/60 px-3 py-2 text-brand-700 font-bold text-base">
                  {u.team.name}
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <Link to={`/teams/${u.team.id}`} className="font-semibold text-slate-900 hover:text-brand-700 hover:underline">
                      {u.team.name}
                    </Link>
                    {!u.team.is_active && <Badge>Inactive</Badge>}
                  </div>
                  <p className="text-xs text-slate-500">{u.team.description || 'Active team'}</p>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-4 text-xs text-slate-600">
                {u.team.manager && (
                  <div className="flex items-center gap-1.5">
                    <span className="text-slate-500">Manager:</span>
                    <Avatar name={u.team.manager.full_name} userId={u.team.manager.id} v={u.team.manager.avatar_v} size={5} />
                    <span className="font-medium text-slate-800">{u.team.manager.full_name}</span>
                  </div>
                )}
                {u.team.leader && (
                  <div className="flex items-center gap-1.5">
                    <span className="text-slate-500">Leader:</span>
                    <Avatar name={u.team.leader.full_name} userId={u.team.leader.id} v={u.team.leader.avatar_v} size={5} />
                    <span className="font-medium text-slate-800">{u.team.leader.full_name}</span>
                  </div>
                )}
                <Link to={`/teams/${u.team.id}`} className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 font-medium text-brand-700 hover:bg-slate-50">
                  Open Team Details &rarr;
                </Link>
              </div>
            </div>

            {/* Allocated Projects */}
            {u.projects && u.projects.length > 0 ? (
              <div className="mt-4 grid gap-4 md:grid-cols-2">
                {u.projects.map((p) => (
                  <div key={p.id} className="rounded-xl border border-slate-200 bg-slate-50/70 p-4">
                    <div className="flex items-center justify-between gap-2 mb-2">
                      <Link to={`/projects/${p.id}`} className="font-semibold text-slate-900 hover:text-brand-700">
                        {p.name}
                      </Link>
                      <StatusBadge value={p.status} />
                    </div>

                    {/* Employee Assigned Tasks */}
                    <div className="mt-3">
                      <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">
                        <span>Assigned Tasks</span>
                        <span className="rounded-full bg-slate-200/80 px-2 py-0.5 text-[10px] font-medium text-slate-700">{p.tasks.length} task{p.tasks.length !== 1 ? 's' : ''}</span>
                      </div>
                      {p.tasks.length > 0 ? (
                        <div className="space-y-1.5">
                          {p.tasks.map((tk) => (
                            <div key={tk.id} className="flex items-center justify-between gap-2 rounded-lg bg-white p-2.5 border border-slate-200/70 shadow-2xs text-xs">
                              <div className="flex items-center gap-2 min-w-0">
                                <span className={`h-2 w-2 rounded-full shrink-0 ${tk.status === 'done' ? 'bg-emerald-500' : tk.is_blocked ? 'bg-amber-500' : 'bg-blue-500'}`} />
                                <span className="font-medium text-slate-800 truncate">{tk.title}</span>
                              </div>
                              <div className="flex items-center gap-1.5 shrink-0">
                                {tk.is_blocked && <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-800">Blocked</span>}
                                {tk.priority === 'high' && <span className="rounded bg-rose-50 px-1.5 py-0.5 text-[10px] font-medium text-rose-700">High</span>}
                                {tk.progress > 0 && tk.status !== 'done' && <span className="text-[10px] text-slate-500">{tk.progress}%</span>}
                                <StatusBadge value={tk.status} />
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="text-xs text-slate-500 italic">No tasks currently assigned to this employee in this project.</p>
                      )}
                    </div>

                    {/* Teammates on this project */}
                    {p.teammates && p.teammates.length > 0 && (
                      <div className="mt-4 pt-3 border-t border-slate-200">
                        <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">
                          Teammates working on this project ({p.teammates.length})
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {p.teammates.map((tm) => (
                            <div key={tm.id} className="flex items-center gap-1.5 rounded-full bg-white px-2.5 py-1 border border-slate-200 text-xs shadow-2xs">
                              <Avatar name={tm.full_name} userId={tm.id} v={tm.avatar_v} size={5} />
                              <span className="font-medium text-slate-700">{tm.full_name}</span>
                              <span className="text-[10px] text-slate-500">· {tm.designation || label(tm.role)}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <p className="mt-4 text-xs text-slate-500 italic">No projects allocated to this team yet.</p>
            )}
          </Card>
      ) : <EmptyState title="Not on a team" description="This person is not a member of an active team yet." />)}
      <ConfirmDialog open={dialog === 'approve'} title="Approve and confirm employee" confirmLabel="Approve" loading={approve.isPending} onClose={() => setDialog(null)} onConfirm={() => approve.mutate()}
        message={`Approve and confirm ${u.full_name}? The account will become active and they will be able to sign in.`} />
      <ConfirmDialog open={dialog === 'reject'} danger title="Delete pending joining" confirmLabel="Delete" loading={reject.isPending} onClose={() => setDialog(null)} onConfirm={() => reject.mutate()}
        message={`Delete ${u.full_name}? This pending account is removed permanently. It has not been approved yet, so no work history is lost.`} />
      {dialog === 'reset' && <ResetPassword id={id} onClose={() => setDialog(null)} />}
      <ConfirmDialog open={dialog === 'mfa'} title="Reset two-step verification" confirmLabel="Reset" loading={resetMfa.isPending} onClose={() => setDialog(null)} onConfirm={() => resetMfa.mutate()}
        message={`Switch off two-step verification for ${u.full_name}? They are signed out everywhere and can set it up again after signing in with their password.`} />
      <ConfirmDialog open={dialog === 'activate'} title="Activate employee" confirmLabel="Activate" loading={activate.isPending} onClose={() => setDialog(null)} onConfirm={() => activate.mutate()}
        message={`Mark ${u.full_name} as active now? Any onboarding checklist items still open stay on their profile.`} />
    </>
  )
}
