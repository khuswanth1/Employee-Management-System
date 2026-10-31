import { useState } from 'react'
import { Alert, Badge, Button, Card, EmptyState, Field, Input, Modal, ProgressBar, Textarea } from '../../components/ui'
import { api, fieldErrors } from '../../lib/api'
import { fmtDate } from '../../lib/format'
import { useAction, useApi } from '../../lib/hooks'

function GoalDialog({ cycleId, userId, onClose }) {
  const [f, setF] = useState({ title: '', description: '', kind: 'goal', weight: 0, unit: '', target_value: '', due_date: '' })
  const body = () => ({ cycle_id: cycleId, user_id: userId || null, title: f.title.trim(), description: f.description || null, kind: f.kind, weight: Number(f.weight || 0),
    unit: f.unit || null, target_value: f.kind === 'kpi' ? Number(f.target_value) : null, due_date: f.due_date || null })
  const save = useAction(() => api.post('/performance/goals', body()), { invalidate: ['/performance'], success: 'Goal added', onSuccess: onClose })
  const fe = fieldErrors(save.error)
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }))
  const ready = f.title.trim().length >= 3 && (f.kind === 'goal' || Number(f.target_value) > 0)
  return (
    <Modal open onClose={onClose} title="Add a goal" footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={save.isPending} disabled={!ready} onClick={() => save.mutate()}>Add</Button></>}>
      <div className="space-y-4">
        {save.error && !Object.keys(fe).length && <Alert>{save.error.message}</Alert>}
        <Field label="Title" required error={fe.title}><Input value={f.title} onChange={set('title')} maxLength={200} /></Field>
        <Field label="Details"><Textarea value={f.description} onChange={set('description')} maxLength={4000} /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Type"><select className="block w-full rounded-lg border border-slate-500 bg-white px-3 py-2 text-sm" value={f.kind} onChange={set('kind')}><option value="goal">Objective (progress 0–100%)</option><option value="kpi">Measurable KPI</option></select></Field>
          <Field label="Weight (% of all goals)" error={fe.weight}><Input type="number" min="0" max="100" value={f.weight} onChange={set('weight')} /></Field>
          {f.kind === 'kpi' && <>
            <Field label="Target" required error={fe.target_value}><Input type="number" min="0" step="any" value={f.target_value} onChange={set('target_value')} /></Field>
            <Field label="Unit"><Input value={f.unit} onChange={set('unit')} maxLength={30} placeholder="tickets, %, …" /></Field></>}
          <Field label="Due"><Input type="date" value={f.due_date} onChange={set('due_date')} /></Field>
        </div>
        {!userId && <p className="text-xs text-slate-500">Your manager agrees the goal before it counts towards your review.</p>}
      </div>
    </Modal>
  )
}

function CheckIn({ goal, onClose }) {
  const [v, setV] = useState(goal.kind === 'kpi' ? goal.current_value ?? '' : goal.progress)
  const [comment, setComment] = useState('')
  const save = useAction(() => api.post(`/performance/goals/${goal.id}/updates`, goal.kind === 'kpi' ? { current_value: Number(v), comment: comment || null } : { progress: Number(v), comment: comment || null }),
    { invalidate: ['/performance'], success: 'Progress saved', onSuccess: onClose })
  const { data: hist } = useApi(`/performance/goals/${goal.id}/updates`)
  return (
    <Modal open onClose={onClose} title={`Progress · ${goal.title}`} footer={<><Button variant="secondary" onClick={onClose}>Close</Button><Button loading={save.isPending} disabled={v === ''} onClick={() => save.mutate()}>Save</Button></>}>
      <div className="space-y-4">
        {save.error && <Alert>{save.error.message}</Alert>}
        <Field label={goal.kind === 'kpi' ? `Current value${goal.unit ? ` (${goal.unit})` : ''}, target ${goal.target_value}` : 'Progress (0–100)'}>
          <Input type="number" min="0" max={goal.kind === 'kpi' ? undefined : 100} step="any" value={v} onChange={(e) => setV(e.target.value)} />
        </Field>
        <Field label="Comment"><Textarea value={comment} onChange={(e) => setComment(e.target.value)} maxLength={2000} /></Field>
        {hist?.items?.length > 0 && <ul className="max-h-40 space-y-1 overflow-auto text-sm text-slate-600">{hist.items.map((h) => <li key={h.id}>{fmtDate(h.created_at)} · {h.author}: {h.progress}%{h.comment ? ` · ${h.comment}` : ''}</li>)}</ul>}
      </div>
    </Modal>
  )
}

/** Goals and KPIs of one person in one cycle. `manage`: the viewer is the person's manager / HR (can agree and cancel). */
export default function GoalsCard({ cycle, userId, manage = false, title = 'Goals and KPIs' }) {
  const { data, isLoading } = useApi('/performance/goals', { cycle_id: cycle.id, user_id: userId })
  const [dlg, setDlg] = useState(null)
  const agree = useAction((id) => api.post(`/performance/goals/${id}/agree`), { invalidate: ['/performance'], success: 'Goal agreed' })
  const cancel = useAction((id) => api.del(`/performance/goals/${id}`), { invalidate: ['/performance'], success: 'Goal removed' })
  const open = cycle.status !== 'closed'
  const items = (data?.items || []).filter((g) => g.status !== 'cancelled')
  return (
    <Card title={title} action={open ? <Button size="sm" variant="secondary" onClick={() => setDlg({ add: true })}>Add goal</Button> : null}>
      {isLoading ? null : !items.length ? <EmptyState title="No goals yet" description={open ? 'Add what you will deliver this cycle.' : undefined} /> : (
        <ul className="divide-y divide-slate-100">
          {items.map((g) => (
            <li key={g.id} className="py-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="font-medium">{g.title} <span className="text-xs text-slate-500">· {g.weight}%{g.due_date ? ` · due ${fmtDate(g.due_date)}` : ''}</span> {g.status === 'proposed' && <Badge tone="amber">waiting to be agreed</Badge>}</p>
                <div className="flex gap-1">
                  {manage && g.status === 'proposed' && open && <Button size="sm" onClick={() => agree.mutate(g.id)}>Agree</Button>}
                  {g.status === 'agreed' && cycle.status === 'active' && <Button size="sm" variant="secondary" onClick={() => setDlg({ goal: g })}>Update progress</Button>}
                  {open && (manage || g.status === 'proposed') && <Button size="sm" variant="ghost" onClick={() => window.confirm('Remove this goal?') && cancel.mutate(g.id)}>Remove</Button>}
                </div>
              </div>
              {g.description && <p className="mt-1 text-sm text-slate-600">{g.description}</p>}
              <div className="mt-2 flex items-center gap-3"><div className="w-48"><ProgressBar value={g.progress} label={`Progress of ${g.title}`} /></div>
                <span className="text-xs text-slate-500">{g.kind === 'kpi' ? `${g.current_value ?? 0} of ${g.target_value}${g.unit ? ` ${g.unit}` : ''}` : `${g.progress}%`}</span></div>
            </li>
          ))}
        </ul>
      )}
      {data && <p className="mt-3 text-xs text-slate-500">Weights used: {data.total_weight}% of 100%.</p>}
      {dlg?.add && <GoalDialog cycleId={cycle.id} userId={userId} onClose={() => setDlg(null)} />}
      {dlg?.goal && <CheckIn goal={dlg.goal} onClose={() => setDlg(null)} />}
    </Card>
  )
}
