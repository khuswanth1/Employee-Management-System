import { useEffect, useState } from 'react'
import { Alert, Button, Field, FormSection, Input, Modal, Select, Textarea } from '../../components/ui'
import MultiSelect from '../../components/MultiSelect'
import TagInput from '../../components/TagInput'
import { api, fieldErrors } from '../../lib/api'
import { label } from '../../lib/format'
import { useAction, useApi } from '../../lib/hooks'
import { useAuth } from '../auth/AuthContext'

const blank = { name: '', code: '', description: '', category: '', client_name: '', status: 'planning', risk_level: 'low', visibility: 'restricted', start_date: '', due_date: '', estimated_hours: '', tags: [], member_ids: [] }
const blankTeam = { mode: 'none', name: '', leader_id: '', member_ids: [], team_id: '' }

/** Create (project == null) or edit a project. */
export default function ProjectModal({ open, onClose, project, onCreated, onDeleted }) {
  const isNew = !project
  const { role, user } = useAuth()
  const [f, setF] = useState(blank)
  const [tm, setTm] = useState(blankTeam)
  const canTeam = isNew && (role === 'founder' || role === 'manager')
  const { data: pool } = useApi('/teams/available', { branch_id: role === 'manager' && user.branch_id != null ? user.branch_id : undefined }, { enabled: open && canTeam && tm.mode === 'new' })
  const { data: myTeams } = useApi('/teams', { active: true, page_size: 100 }, { enabled: open && canTeam && tm.mode === 'existing' })
  const { data: dir } = useApi('/employees/directory', null, { enabled: open })
  const { data: detail } = useApi(project ? `/projects/${project.id}` : null, null, { enabled: open && !isNew })

  useEffect(() => {
    if (!open) return
    setTm(blankTeam)
    const src = detail || project
    setF(
      src
        ? {
            name: src.name,
            code: src.code || '',
            description: src.description || '',
            category: src.category || '',
            client_name: src.client_name || '',
            status: src.status,
            risk_level: src.risk_level || 'low',
            visibility: src.visibility || 'restricted',
            start_date: src.start_date || '',
            due_date: src.due_date || '',
            estimated_hours: src.estimated_hours ?? '',
            tags: src.tags || [],
            member_ids: detail?.member_ids || src.member_ids || []
          }
        : blank
    )
  }, [open, project, detail])

  const save = useAction(
    async () => {
      const dates = { start_date: f.start_date || null, due_date: f.due_date || null }
      const details = {
        code: f.code.trim() || null, category: f.category.trim() || null, client_name: f.client_name.trim() || null, risk_level: f.risk_level,
        visibility: f.visibility, estimated_hours: f.estimated_hours === '' ? null : Number(f.estimated_hours), tags: f.tags,
      }
      if (isNew) {
        return api.post('/projects', {
          name: f.name,
          description: f.description || null,
          status: f.status,
          ...dates,
          ...details,
          member_ids: f.member_ids,
          ...(tm.mode === 'new' && {
            team: { name: tm.name || null, leader_id: tm.leader_id ? Number(tm.leader_id) : null, member_ids: tm.member_ids }
          }),
          ...(tm.mode === 'existing' && tm.team_id && { team_id: Number(tm.team_id) })
        })
      }
      const saved = await api.patch(`/projects/${project.id}`, {
        name: f.name,
        description: f.description || null,
        status: f.status,
        ...dates,
        ...details,
        ...(f.code.trim() ? {} : { code: undefined })
      })
      const before = [...(detail?.member_ids || project?.member_ids || [])].sort().join()
      if ((detail || project) && [...f.member_ids].sort().join() !== before) {
        await api.put(`/projects/${project.id}/members`, { member_ids: f.member_ids })
      }
      return saved
    },
    {
      invalidate: ['/projects', '/dashboard', '/teams'],
      success: isNew ? 'Project created' : 'Project updated',
      onSuccess: (p) => {
        onClose()
        if (isNew) onCreated?.(p)
      }
    }
  )

  const del = useAction(() => api.del(`/projects/${project.id}`), {
    invalidate: ['/projects', '/dashboard', '/tasks'],
    success: 'Project deleted',
    onSuccess: () => {
      onClose()
      onDeleted?.()
    }
  })

  const fe = fieldErrors(save.error)
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }))
  const ownerId = detail?.owner_id || project?.owner_id
  const employees = (dir?.items || []).filter((u) => u.role === 'employee')
  const employeeIds = new Set(employees.map((u) => u.id))

  return (
    <Modal
      open={open}
      onClose={onClose}
      wide
      title={isNew ? 'New project' : `Edit ${project.name}`}
      footer={
        <div className="flex w-full items-center justify-between">
          {!isNew ? (
            <Button
              type="button"
              variant="danger"
              size="sm"
              loading={del.isPending}
              onClick={() => {
                if (window.confirm(`Delete "${project.name}" and all its tasks, milestones and attachments?`)) {
                  del.mutate()
                }
              }}
            >
              Delete project
            </Button>
          ) : (
            <div />
          )}
          <div className="flex gap-2">
            <Button variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button loading={save.isPending} onClick={() => save.mutate()}>
              {isNew ? 'Create project' : 'Save changes'}
            </Button>
          </div>
        </div>
      }
    >
      <form className="space-y-5" onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
        {save.error && !Object.keys(fe).length && <Alert>{save.error.message}</Alert>}
        <FormSection title="General information">
          <Field label="Project name" required error={fe.name}>
            <Input value={f.name} onChange={set('name')} required maxLength={200} placeholder="e.g. Website Redesign" />
          </Field>
          <Field label="Project code" error={fe.code} hint="Leave blank to generate one (PRJ-0001). Letters, digits, - and _">
            <Input value={f.code} onChange={set('code')} maxLength={20} />
          </Field>
          <div className="sm:col-span-2">
            <Field label="Description" error={fe.description}>
              <Textarea value={f.description} onChange={set('description')} placeholder="What is the goal of this project?" />
            </Field>
          </div>
          <Field label="Category" error={fe.category} hint="For example Product, Internal, Client work"><Input value={f.category} onChange={set('category')} maxLength={60} /></Field>
          <Field label="Client or business unit" error={fe.client_name}><Input value={f.client_name} onChange={set('client_name')} maxLength={120} /></Field>
        </FormSection>
        <FormSection title="Status and risk">
          <Field label="Status">
            <Select value={f.status} onChange={set('status')}>
              {['planning', 'active', 'on_hold', 'completed'].map((s) => (<option key={s} value={s}>{label(s)}</option>))}
            </Select>
          </Field>
          <Field label="Risk level" error={fe.risk_level}>
            <Select value={f.risk_level} onChange={set('risk_level')}>
              {['low', 'medium', 'high', 'critical'].map((s) => (<option key={s} value={s}>{label(s)}</option>))}
            </Select>
          </Field>
          <Field label="Visibility" error={fe.visibility} hint={f.visibility === 'company' ? 'Everyone in the owner\'s branch can read it. Only the project people can change it.' : 'Only the owner, members, team leaders and management can see it.'}>
            <Select value={f.visibility} onChange={set('visibility')}>
              <option value="restricted">Restricted (project people only)</option>
              <option value="company">Visible to everyone (read-only)</option>
            </Select>
          </Field>
        </FormSection>
        <FormSection title="Dates and effort">
          <Field label="Start date" error={fe.start_date}>
            <Input type="date" value={f.start_date} onChange={set('start_date')} />
          </Field>
          <Field label="Planned deadline" error={fe.due_date}>
            <Input type="date" min={f.start_date || undefined} value={f.due_date} onChange={set('due_date')} />
          </Field>
          <Field label="Estimated effort (hours)" error={fe.estimated_hours}>
            <Input type="number" min={0} max={10000} step="0.5" inputMode="decimal" value={f.estimated_hours} onChange={set('estimated_hours')} />
          </Field>
          <Field label="Tags" error={fe.tags} hint="Press Enter to add">
            <TagInput label="Tags" max={20} value={f.tags} onChange={(v) => setF((s) => ({ ...s, tags: v }))} />
          </Field>
        </FormSection>
        {canTeam && (
          <fieldset className="space-y-3 rounded-lg border border-slate-200 p-3">
            <legend className="px-1 text-sm font-medium text-slate-700">Project team</legend>
            <div className="flex flex-wrap gap-4 text-sm">
              {[['none', 'No team yet'], ['new', 'Create a team'], ['existing', 'Use an existing team']].map(([v, l]) => (
                <label key={v} className="flex items-center gap-1.5">
                  <input type="radio" name="team-mode" className="accent-brand-600" checked={tm.mode === v} onChange={() => setTm({ ...blankTeam, mode: v })} />{l}
                </label>
              ))}
            </div>
            {tm.mode === 'new' && (
              <>
                <Field label="Team name" hint={`Defaults to "${f.name || 'Project'} Team"`}>
                  <Input value={tm.name} maxLength={120} onChange={(e) => setTm({ ...tm, name: e.target.value })} />
                </Field>
                <Field label="Team members" hint="Only people who are not already in an active team are listed.">
                  <MultiSelect
                    options={(pool?.items || []).map((p) => ({ value: p.id, label: p.full_name, hint: p.designation || label(p.role) }))}
                    value={tm.member_ids}
                    onChange={(ids) => setTm({ ...tm, member_ids: ids, leader_id: ids.includes(Number(tm.leader_id)) ? tm.leader_id : '' })}
                  />
                </Field>
                <Field label="Team leader" hint="Chosen from the selected members. The leader distributes tasks, follows daily updates and progress.">
                  <Select value={tm.leader_id} disabled={!tm.member_ids.length} onChange={(e) => setTm({ ...tm, leader_id: e.target.value })}>
                    <option value="">No leader yet</option>
                    {(pool?.items || []).filter((p) => tm.member_ids.includes(p.id) && p.role !== 'hr').map((p) => <option key={p.id} value={p.id}>{p.full_name}</option>)}
                  </Select>
                </Field>
              </>
            )}
            {tm.mode === 'existing' && (
              <Field label="Team" hint="Teams you manage. Its leader and members get access to the project.">
                <Select value={tm.team_id} onChange={(e) => setTm({ ...tm, team_id: e.target.value })}>
                  <option value="">Choose a team…</option>
                  {(myTeams?.items || []).filter((t) => t.can_manage).map((t) => <option key={t.id} value={t.id}>{t.name}{t.leader ? ` — led by ${t.leader.full_name}` : ''}</option>)}
                </Select>
              </Field>
            )}
          </fieldset>
        )}
        <Field label={canTeam ? "Additional project members" : "Team members"} hint="Search and pick as many as you need. The owner always stays on the project.">
          <MultiSelect
            options={employees.map((u) => ({ value: u.id, label: u.full_name, hint: u.designation || label(u.role) }))}
            value={f.member_ids.filter((id) => employeeIds.has(id))}
            onChange={(ids) =>
              setF((s) => ({
                ...s,
                // founders, managers and HR are not listed but stay on the project (the owner always does)
                member_ids: [...new Set([...ids, ...s.member_ids.filter((id) => !employeeIds.has(id)), ...(ownerId ? [ownerId] : [])])]
              }))
            }
          />
        </Field>
      </form>
    </Modal>
  )
}
