// Pure helpers for the personal task manager (kept out of the components so they can be unit tested).

/** 90 -> "1h 30m", 45 -> "45m", 120 -> "2h", 0/null -> "—" */
export function fmtMinutes(total) {
  const m = Number(total) || 0
  if (m <= 0) return '—'
  const h = Math.floor(m / 60), r = m % 60
  return [h ? `${h}h` : '', r ? `${r}m` : ''].filter(Boolean).join(' ')
}

/** Hours + minutes fields -> total minutes, or null when both are empty. */
export function toMinutes(hours, minutes) {
  if (hours === '' && minutes === '') return null
  return (Number(hours) || 0) * 60 + (Number(minutes) || 0)
}

export const splitMinutes = (total) => (total ? { h: String(Math.floor(total / 60)), m: String(total % 60) } : { h: '', m: '' })

const minutesOf = (t) => t.duration_minutes || 0

/** Re-derive the per-task totals after the tree changed locally (same arithmetic as the server). */
function recompute(items) {
  return items.map((t, i) => {
    const subs = (t.subtasks || []).map((s, j) => ({ ...s, position: j, parent_id: t.id }))
    return {
      ...t, position: i, subtasks: subs,
      subtask_count: subs.length, subtasks_done: subs.filter((s) => s.status === 'completed').length,
      total_minutes: minutesOf(t) + subs.reduce((a, s) => a + minutesOf(s), 0),
      remaining_minutes: (t.status === 'completed' ? 0 : minutesOf(t)) + subs.filter((s) => s.status !== 'completed').reduce((a, s) => a + minutesOf(s), 0),
    }
  })
}

/**
 * Move task `id` to position `index` under `parentId` (null = top level) — the optimistic mirror of POST /todos/{id}/move.
 * Returns the new item list, or the same list when the move is not allowed (the server then explains why).
 */
export function applyMove(items, id, parentId, index) {
  let moved = null
  const without = items.map((t) => {
    if (t.id === id) { moved = t; return null }
    const hit = (t.subtasks || []).find((s) => s.id === id)
    if (hit) { moved = hit; return { ...t, subtasks: t.subtasks.filter((s) => s.id !== id) } }
    return t
  }).filter(Boolean)
  if (!moved) return items
  if (parentId === null) {
    const at = Math.max(0, Math.min(index, without.length))
    return recompute([...without.slice(0, at), { ...moved, parent_id: null, subtasks: moved.subtasks || [] }, ...without.slice(at)])
  }
  if (moved.id === parentId || (moved.subtasks || []).length) return items // a task with subtasks cannot become a subtask
  const target = without.find((t) => t.id === parentId)
  if (!target) return items
  const subs = target.subtasks || []
  const at = Math.max(0, Math.min(index, subs.length))
  const next = [...subs.slice(0, at), { ...moved, parent_id: parentId }, ...subs.slice(at)]
  return recompute(without.map((t) => (t.id === parentId ? { ...t, subtasks: next } : t)))
}

/** Index to send to the server when dropping `dragId` before/after `targetId` inside `list` (the list as shown). */
export function dropIndex(list, dragId, targetId, after) {
  const rest = list.filter((t) => t.id !== dragId)
  const at = rest.findIndex((t) => t.id === targetId)
  return at < 0 ? rest.length : at + (after ? 1 : 0)
}
