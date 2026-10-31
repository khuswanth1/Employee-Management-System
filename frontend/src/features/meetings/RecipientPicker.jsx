import { useMemo, useState } from 'react'
import { Avatar, SearchInput } from '../../components/ui'
import { useApi } from '../../lib/hooks'

// Who a meeting or call can reach: people the caller may contact, their own teams and their chat groups.
export const emptyPick = () => ({ people: [], teams: [], groups: [] })
export const pickBody = (p) => ({ invitee_ids: p.people, team_ids: p.teams, group_ids: p.groups })
export const pickCount = (p) => p.people.length + p.teams.length + p.groups.length

function Check({ id, checked, onChange, children }) {
  return (
    <li>
      <label htmlFor={id} className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-slate-50">
        <input id={id} type="checkbox" className="h-4 w-4 rounded border-slate-300" checked={checked} onChange={onChange} />
        {children}
      </label>
    </li>
  )
}

export default function RecipientPicker({ value, onChange, enabled = true, exclude = [], people = true, groups = true }) {
  const [q, setQ] = useState('')
  const { data: users } = useApi('/chat/users', null, { enabled })
  const { data: teams } = useApi('/teams/mine', null, { enabled })
  const { data: convs } = useApi('/chat/conversations', null, { enabled: enabled && groups })
  const toggle = (key, id) => onChange({ ...value, [key]: value[key].includes(id) ? value[key].filter((x) => x !== id) : [...value[key], id] })
  const list = useMemo(() => (users?.items || []).filter((u) => !exclude.includes(u.id) && u.full_name.toLowerCase().includes(q.trim().toLowerCase())), [users, exclude, q])
  const groupList = (convs?.items || []).filter((c) => c.kind === 'group')
  const teamList = teams?.items || []
  return (
    <div className="space-y-4">
      {people && (
        <fieldset>
          <legend className="mb-1 text-sm font-medium text-slate-700">People</legend>
          <SearchInput value={q} onChange={setQ} placeholder="Search people" />
          <ul className="mt-2 max-h-44 overflow-y-auto rounded-lg border border-slate-200 p-1" aria-label="People">
            {list.length === 0 ? <li className="px-2 py-3 text-sm text-slate-500">{users ? 'Nobody matches.' : 'Loading…'}</li> : list.map((u) => (
              <Check key={u.id} id={`pick-user-${u.id}`} checked={value.people.includes(u.id)} onChange={() => toggle('people', u.id)}>
                <Avatar name={u.full_name} size={6} userId={u.id} v={u.avatar_v} />
                <span className="min-w-0"><span className="block truncate">{u.full_name}</span>{u.designation && <span className="block truncate text-xs text-slate-500">{u.designation}</span>}</span>
              </Check>
            ))}
          </ul>
        </fieldset>
      )}
      {teamList.length > 0 && (
        <fieldset>
          <legend className="mb-1 text-sm font-medium text-slate-700">Teams</legend>
          <ul className="rounded-lg border border-slate-200 p-1">
            {teamList.map((t) => <Check key={t.id} id={`pick-team-${t.id}`} checked={value.teams.includes(t.id)} onChange={() => toggle('teams', t.id)}><span className="truncate">{t.name}</span></Check>)}
          </ul>
        </fieldset>
      )}
      {groups && groupList.length > 0 && (
        <fieldset>
          <legend className="mb-1 text-sm font-medium text-slate-700">Chat groups</legend>
          <ul className="rounded-lg border border-slate-200 p-1">
            {groupList.map((g) => <Check key={g.id} id={`pick-group-${g.id}`} checked={value.groups.includes(g.id)} onChange={() => toggle('groups', g.id)}><span className="truncate">{g.title}</span><span className="text-xs text-slate-500">{g.members.length} people</span></Check>)}
          </ul>
        </fieldset>
      )}
      <p className="text-xs text-slate-500" aria-live="polite">{pickCount(value) ? `${value.people.length} people, ${value.teams.length} teams, ${value.groups.length} groups selected` : 'Only you can join until you invite someone.'}</p>
    </div>
  )
}
