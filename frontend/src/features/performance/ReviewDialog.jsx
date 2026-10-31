import { useEffect, useState } from 'react'
import { Alert, Badge, Button, ErrorState, Field, Modal, PageLoader, Textarea } from '../../components/ui'
import { api } from '../../lib/api'
import { useAction, useApi } from '../../lib/hooks'
import { RatingSelect, ratingLabel, REVIEW_LABEL, REVIEW_TONE } from './shared'

const Read = ({ title, children }) => <div><h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h4><div className="mt-1 whitespace-pre-wrap text-sm">{children || '—'}</div></div>

/**
 * One appraisal. `side` 'self' = the person's own form, 'manager' = the reviewer's form; anything the viewer may not write is shown read-only.
 * The server decides what is visible (a draft self review and an unshared manager review never reach the wrong person).
 */
export default function ReviewDialog({ id, onClose }) {
  const { data: r, isLoading, error, refetch } = useApi(`/performance/reviews/${id}`)
  const { data: me } = useApi('/auth/me')
  const [f, setF] = useState(null)
  const owner = r && me && r.user_id === me.id
  const side = r ? (owner && r.status === 'pending_self' && r.cycle_status === 'active' ? 'self' : r.can_review ? 'manager' : null) : null
  useEffect(() => {
    if (!r || f) return
    if (side === 'self') setF({ rating: r.self_rating, comments: r.self_comments || '', competencies: r.self_competencies, goals: r.self_goals })
    else if (side === 'manager') setF({ rating: r.manager_rating, comments: r.manager_comments || '', strengths: r.strengths || '', development_areas: r.development_areas || '', competencies: r.manager_competencies, goals: r.manager_goals })
  }, [r, side, f])
  const base = `/performance/reviews/${id}`
  const payload = () => (side === 'self'
    ? { rating: f.rating, comments: f.comments, competencies: f.competencies, goals: f.goals }
    : { rating: f.rating, comments: f.comments, strengths: f.strengths, development_areas: f.development_areas, competencies: f.competencies, goals: f.goals })
  const save = useAction(() => api.put(`${base}/${side}`, payload()), { invalidate: ['/performance'], success: 'Draft saved' })
  const submit = useAction(async () => { await api.put(`${base}/${side}`, payload()); return api.post(`${base}/${side}/submit`) }, { invalidate: ['/performance'], success: 'Submitted', onSuccess: onClose })
  const [response, setResponse] = useState('')
  const ack = useAction(() => api.post(`${base}/acknowledge`, { response }), { invalidate: ['/performance'], success: 'Review acknowledged', onSuccess: onClose })
  if (isLoading) return <Modal open onClose={onClose} title="Review"><PageLoader /></Modal>
  if (error) return <Modal open onClose={onClose} title="Review"><ErrorState error={error} onRetry={refetch} /></Modal>
  const set = (patch) => setF((s) => ({ ...s, ...patch }))
  const setComp = (name, v) => set({ competencies: { ...f.competencies, [name]: v } })
  const setGoal = (gid, v) => set({ goals: { ...f.goals, [gid]: v } })
  const editing = side && f
  const err = (submit.error || save.error || ack.error)?.message
  return (
    <Modal open onClose={onClose} wide title={`${r.employee} · ${r.cycle}`}
      footer={<><Button variant="secondary" onClick={onClose}>Close</Button>
        {editing && <><Button variant="secondary" loading={save.isPending} onClick={() => save.mutate()}>Save draft</Button><Button loading={submit.isPending} onClick={() => submit.mutate()}>{side === 'self' ? 'Submit self review' : 'Submit review'}</Button></>}
        {owner && r.status === 'completed' && <Button loading={ack.isPending} onClick={() => ack.mutate()}>Acknowledge</Button>}</>}>
      <div className="space-y-5">
        <div className="flex flex-wrap items-center gap-2"><Badge tone={REVIEW_TONE[r.status]}>{REVIEW_LABEL[r.status]}</Badge>{r.reviewer && <span className="text-sm text-slate-500">Reviewer: {r.reviewer}</span>}</div>
        {err && <Alert>{err}</Alert>}
        {owner && r.hidden_until_shared && r.status === 'pending_manager' && <Alert tone="amber">Your manager&apos;s assessment stays private until they submit it.</Alert>}
        {side === 'manager' && <Alert tone="amber">The person cannot see your rating or comments until you submit.</Alert>}

        <section aria-label="Self review" className="space-y-3 rounded-lg border border-slate-200 p-4">
          <h3 className="font-semibold">Self review</h3>
          {side === 'self' && f ? (<>
            <Field label="Overall rating" required><RatingSelect scale={r.scale} value={f.rating} onChange={(v) => set({ rating: v })} label="Overall self rating" /></Field>
            {r.competencies.map((c) => <Field key={c} label={c}><RatingSelect scale={r.scale} value={f.competencies[c]} onChange={(v) => setComp(c, v)} label={`Self rating for ${c}`} /></Field>)}
            {r.goals.map((g) => <Field key={g.id} label={`Goal: ${g.title}`}><RatingSelect scale={r.scale} value={f.goals[g.id]} onChange={(v) => setGoal(g.id, v)} label={`Self rating for goal ${g.title}`} /></Field>)}
            <Field label="How did the cycle go?" required><Textarea value={f.comments} onChange={(e) => set({ comments: e.target.value })} maxLength={6000} /></Field></>
          ) : r.self_submitted_at || owner ? (<>
            <Read title="Overall rating">{ratingLabel(r.scale, r.self_rating)}</Read>
            {Object.entries(r.self_competencies).map(([k, v]) => <Read key={k} title={k}>{ratingLabel(r.scale, v)}</Read>)}
            <Read title="Comments">{r.self_comments}</Read></>
          ) : <p className="text-sm text-slate-500">Not submitted yet.</p>}
        </section>

        {(r.status === 'pending_manager' || r.status === 'completed' || r.status === 'acknowledged') && (
          <section aria-label="Manager review" className="space-y-3 rounded-lg border border-slate-200 p-4">
            <h3 className="font-semibold">Manager review</h3>
            {side === 'manager' && f ? (<>
              <Field label="Overall rating" required><RatingSelect scale={r.scale} value={f.rating} onChange={(v) => set({ rating: v })} label="Overall manager rating" /></Field>
              {r.competencies.map((c) => <Field key={c} label={c}><RatingSelect scale={r.scale} value={f.competencies[c]} onChange={(v) => setComp(c, v)} label={`Manager rating for ${c}`} /></Field>)}
              {r.goals.map((g) => <Field key={g.id} label={`Goal: ${g.title} (${g.weight}%, ${g.progress}% done)`}><RatingSelect scale={r.scale} value={f.goals[g.id]} onChange={(v) => setGoal(g.id, v)} label={`Manager rating for goal ${g.title}`} /></Field>)}
              <Field label="Assessment" required hint="At least 10 characters"><Textarea value={f.comments} onChange={(e) => set({ comments: e.target.value })} maxLength={6000} /></Field>
              <Field label="Strengths"><Textarea value={f.strengths} onChange={(e) => set({ strengths: e.target.value })} maxLength={4000} /></Field>
              <Field label="Development areas"><Textarea value={f.development_areas} onChange={(e) => set({ development_areas: e.target.value })} maxLength={4000} /></Field></>
            ) : r.manager_rating != null || r.manager_comments ? (<>
              <Read title="Overall rating">{ratingLabel(r.scale, r.manager_rating)}</Read>
              {r.goal_score != null && <Read title="Goal score (weighted)">{r.goal_score}</Read>}
              {Object.entries(r.manager_competencies).map(([k, v]) => <Read key={k} title={k}>{ratingLabel(r.scale, v)}</Read>)}
              <Read title="Assessment">{r.manager_comments}</Read><Read title="Strengths">{r.strengths}</Read><Read title="Development areas">{r.development_areas}</Read></>
            ) : <p className="text-sm text-slate-500">Not shared yet.</p>}
          </section>
        )}
        {owner && r.status === 'completed' && <Field label="Your response (optional)"><Textarea value={response} onChange={(e) => setResponse(e.target.value)} maxLength={4000} /></Field>}
        {r.employee_response && <Read title="Employee response">{r.employee_response}</Read>}
      </div>
    </Modal>
  )
}
