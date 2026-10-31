import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Field, Input, Modal, Select, Textarea } from '../../components/ui'
import MultiSelect from '../../components/MultiSelect'
import { api, fieldErrors } from '../../lib/api'
import { label } from '../../lib/format'
import { useAction, useApi } from '../../lib/hooks'
import { useAuth } from '../auth/AuthContext'

const blank = { name: '', description: '', department_id: '', branch_id: '', manager_id: '', leader_id: '', member_ids: [], project_ids: [] }

/** Create a team (team == null) or edit its basic details. Members, leader and projects of an existing team are managed on its page. */
export default function TeamModal({ open, onClose, team, onSaved }) {
  const { user, role } = useAuth()
  const isNew = !team
  const [f, setF] = useState(blank)
  const branchLocked = role === 'manager' && user.branch_id != null
  const { data: depts } = useApi('/departments', null, { enabled: open })
  const { data: branches } = useApi('/branches', null, { enabled: open && role === 'founder' })
  const { data: dir } = useApi('/employees/directory', null, { enabled: open && role === 'founder' && isNew })
  const { data: pool } = useApi('/teams/available', { branch_id: branchLocked ? user.branch_id : f.branch_id || undefined }, { enabled: open && isNew })
  const { data: projects } = useApi('/projects', { page_size: 100 }, { enabled: open && isNew })

  useEffect(() => {
    if (!open) return
    setF(team ? { ...blank, name: team.name, description: team.description || '', department_id: team.department_id || '' } : blank)
  }, [open, team])

  const people = pool?.items || []
  const chosen = useMemo(() => people.filter((p) => f.member_ids.includes(p.id) && ['employee', 'manager'].includes(p.role)), [people, f.member_ids])
  const ownable = (projects?.items || []).filter((p) => p.can_edit)
  const managers = (dir?.items || []).filter((u) => u.role === 'manager' && (!f.branch_id || !u.branch_id || String(u.branch_id) === String(f.branch_id)))

  const save = useAction(
    () => {
      const base = { name: f.name, description: f.description || null, department_id: f.department_id ? Number(f.department_id) : null }
      if (!isNew) return api.patch(`/teams/${team.id}`, base)
      return api.post('/teams', {
        ...base,
        branch_id: f.branch_id ? Number(f.branch_id) : null,
        manager_id: f.manager_id ? Number(f.manager_id) : null,
        leader_id: f.leader_id ? Number(f.leader_id) : null,
        member_ids: f.member_ids,
        project_ids: f.project_ids,
      })
    },
    { invalidate: ['/teams', '/projects'], success: isNew ? 'Team created' : 'Team updated', onSuccess: (t) => { onClose(); onSaved?.(t) } },
  )
  const fe = fieldErrors(save.error)
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }))

  return (
    <Modal
      open={open}
      onClose={onClose}
      wide
      title={isNew ? 'New team' : 'Edit team'}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={save.isPending} onClick={() => save.mutate()}>{isNew ? 'Create team' : 'Save changes'}</Button></>}
    >
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
        {save.error && !Object.keys(fe).length && <Alert>{save.error.message}</Alert>}
        <Field label="Team name" required error={fe.name}>
          <Input value={f.name} onChange={set('name')} required placeholder="e.g. Platform Engineering" />
        </Field>
        <Field label="Description" error={fe.description}>
          <Textarea value={f.description} onChange={set('description')} placeholder="What does this team own?" />
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Department">
            <Select value={f.department_id} onChange={set('department_id')}>
              <option value="">None</option>
              {depts?.items.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </Select>
          </Field>
          {isNew && role === 'founder' && (
            <Field label="Branch" hint="Team members must belong to this branch">
              <Select value={f.branch_id} onChange={(e) => setF((s) => ({ ...s, branch_id: e.target.value, member_ids: [], leader_id: '' }))}>
                <option value="">Company-wide</option>
                {branches?.items.filter((b) => b.is_active).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
              </Select>
            </Field>
          )}
        </div>
        {isNew && role === 'founder' && (
          <Field label="Managing manager" hint="The manager who owns this team and its project allocation">
            <Select value={f.manager_id} onChange={set('manager_id')}>
              <option value="">Founder-managed</option>
              {managers.map((m) => <option key={m.id} value={m.id}>{m.full_name}</option>)}
            </Select>
          </Field>
        )}
        {isNew && (
          <>
            <Field label="Team members" hint="Only people who are not in another team are listed.">
              <MultiSelect
                options={people.map((p) => ({ value: p.id, label: p.full_name, hint: p.designation || label(p.role) }))}
                value={f.member_ids}
                onChange={(ids) => setF((s) => ({ ...s, member_ids: ids, leader_id: ids.includes(Number(s.leader_id)) ? s.leader_id : '' }))}
              />
            </Field>
            <Field label="Team leader" hint="Pick from the selected members (employees or managers)">
              <Select value={f.leader_id} onChange={set('leader_id')} disabled={!chosen.length}>
                <option value="">No leader yet</option>
                {chosen.map((p) => <option key={p.id} value={p.id}>{p.full_name}</option>)}
              </Select>
            </Field>
            <Field label="Allocate projects" hint="Projects you own. Everyone on the team gets access to them.">
              <MultiSelect options={ownable.map((p) => ({ value: p.id, label: p.name }))} value={f.project_ids} onChange={(ids) => setF((s) => ({ ...s, project_ids: ids }))} placeholder="Search projects…" />
            </Field>
          </>
        )}
      </form>
    </Modal>
  )
}
