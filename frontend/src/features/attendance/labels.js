export const hm = (minutes) => {
  const m = Math.max(0, Math.round(minutes || 0))
  return m >= 60 ? `${Math.floor(m / 60)} h ${m % 60 ? `${m % 60} min` : ''}`.trim() : `${m} min`
}

const STATUS = {
  in_progress: ['In progress', 'blue'], present: ['Present', 'green'], half_day: ['Half day', 'amber'], short_day: ['Short day', 'red'],
  weekend_work: ['Weekend work', 'purple'], holiday_work: ['Holiday work', 'purple'],
}

/** [text, badge tone] for a day status. */
export const statusInfo = (s) => STATUS[s] || [s || '—', 'gray']
export const STATUS_OPTIONS = Object.entries(STATUS).map(([value, [text]]) => ({ value, text }))
