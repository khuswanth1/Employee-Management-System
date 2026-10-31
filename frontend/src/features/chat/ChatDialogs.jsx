import { useState } from 'react'
import { Avatar, Button, Input, Modal, Select, cx } from '../../components/ui'
import { api } from '../../lib/api'
import { ROLE_LABEL } from '../../lib/format'
import { useAction, useApi, useDebounce } from '../../lib/hooks'

export function NewChat({ open, onClose, onCreated }) {
  const [group, setGroup] = useState(false)
  const [q, setQ] = useState('')
  const [name, setName] = useState('')
  const [picked, setPicked] = useState([])
  const dq = useDebounce(q)
  const { data } = useApi('/chat/users', { q: dq || undefined }, { enabled: open })
  const create = useAction((body) => api.post('/chat/conversations', body), { invalidate: ['/chat'], onSuccess: (c) => { onCreated(c.id); onClose() } })
  const toggle = (id) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]))
  const canCreate = group && name.trim() && picked.length > 0
  return (
    <Modal open={open} onClose={onClose} title="New chat"
      footer={group ? <Button disabled={!canCreate} loading={create.isPending} onClick={() => create.mutate({ name: name.trim(), member_ids: picked })}>Create group</Button> : null}>
      <div className="space-y-3">
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input type="checkbox" checked={group} onChange={(e) => { setGroup(e.target.checked); setPicked([]) }} /> Group chat
        </label>
        {group && <Input aria-label="Group name" placeholder="Group name" value={name} maxLength={120} onChange={(e) => setName(e.target.value)} />}
        <Input aria-label="Search people" placeholder="Search people…" value={q} onChange={(e) => setQ(e.target.value)} />
        <ul className="max-h-72 divide-y divide-slate-100 overflow-y-auto rounded-lg border border-slate-200">
          {(data?.items || []).map((u) => (
            <li key={u.id}>
              <button type="button" className={cx('flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-slate-50', picked.includes(u.id) && 'bg-brand-50')}
                onClick={() => (group ? toggle(u.id) : create.mutate({ user_id: u.id }))}>
                <Avatar name={u.full_name} userId={u.id} v={u.avatar_v} />
                <span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium text-slate-900">{u.full_name}</span>
                  <span className="block truncate text-xs text-slate-500">{ROLE_LABEL[u.role]}{u.designation ? ` · ${u.designation}` : ''}</span></span>
                {group && <span aria-hidden>{picked.includes(u.id) ? '✓' : ''}</span>}
              </button>
            </li>
          ))}
          {data && !data.items.length && <li className="px-3 py-4 text-center text-sm text-slate-500">No one found</li>}
        </ul>
      </div>
    </Modal>
  )
}

/** Founder-only: employees allowed to message the founder directly (everyone else must escalate). */
export function DirectLines({ open, onClose }) {
  const { data } = useApi('/chat/exceptions', null, { enabled: open })
  const { data: dir } = useApi('/employees/directory', null, { enabled: open })
  const [pick, setPick] = useState('')
  const inv = { invalidate: ['/chat'] }
  const add = useAction((id) => api.put(`/chat/exceptions/${id}`), { ...inv, success: 'Direct line enabled', onSuccess: () => setPick('') })
  const remove = useAction((id) => api.del(`/chat/exceptions/${id}`), { ...inv, success: 'Direct line removed' })
  const allowed = new Set((data?.items || []).map((u) => u.id))
  const options = (dir?.items || []).filter((u) => u.role === 'employee' && !allowed.has(u.id))
  return (
    <Modal open={open} onClose={onClose} title="Direct lines to the founder">
      <p className="mb-3 text-xs text-slate-500">Employees normally reach the founder through their manager or HR (escalations). Add an exception to let a specific employee message the founder directly.</p>
      <ul className="mb-4 divide-y divide-slate-100 rounded-lg border border-slate-200 text-sm">
        {(data?.items || []).map((u) => (
          <li key={u.id} className="flex items-center gap-3 px-3 py-2"><Avatar name={u.full_name} size={7} userId={u.id} v={u.avatar_v} /><span className="flex-1 truncate">{u.full_name}</span>
            <button type="button" className="text-red-600 hover:underline" aria-label={`Remove direct line for ${u.full_name}`} onClick={() => remove.mutate(u.id)}>Remove</button></li>
        ))}
        {data && !data.items.length && <li className="px-3 py-3 text-center text-slate-500">No exceptions. All employees go through escalations.</li>}
      </ul>
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (pick) add.mutate(pick) }}>
        <Select aria-label="Employee to allow" value={pick} onChange={(e) => setPick(e.target.value)}><option value="">Choose an employee…</option>{options.map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}</Select>
        <Button type="submit" disabled={!pick} loading={add.isPending}>Allow</Button>
      </form>
    </Modal>
  )
}
