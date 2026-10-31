import { Select } from '../../components/ui'

export const REVIEW_LABEL = { pending_self: 'Waiting for self review', pending_manager: 'Waiting for manager', completed: 'Shared, to acknowledge', acknowledged: 'Acknowledged' }
export const REVIEW_TONE = { pending_self: 'gray', pending_manager: 'amber', completed: 'blue', acknowledged: 'green' }
export const CYCLE_TONE = { draft: 'gray', active: 'green', closed: 'blue' }

/** A rating dropdown showing the scale's own labels. */
export function RatingSelect({ scale, value, onChange, disabled, label, id }) {
  return (
    <Select id={id} aria-label={label} value={value ?? ''} disabled={disabled} onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}>
      <option value="">Not rated</option>
      {scale.levels.map((l) => <option key={l.value} value={l.value}>{l.value} · {l.label}</option>)}
    </Select>
  )
}

export const ratingLabel = (scale, v) => (v == null ? '—' : `${v} · ${scale?.levels.find((l) => l.value === v)?.label ?? ''}`.trim())
