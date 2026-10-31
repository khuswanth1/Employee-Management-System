import { useMemo, useState } from 'react'
import { Button, Card, PageHeader, Tabs } from '../../components/ui'
import { useApi } from '../../lib/hooks'
import { fmtDate } from '../../lib/format'
import { useAuth } from '../auth/AuthContext'
import HolidayCalendar, { HolidayModal } from './HolidayCalendar'

const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

/** Month grid with the company holidays highlighted. Editors click a holiday to edit it or a weekday to add one. */
function MonthView({ canEdit }) {
  const [cursor, setCursor] = useState(() => new Date(new Date().getFullYear(), new Date().getMonth(), 1))
  const [editing, setEditing] = useState(null) // holiday | { date } | null
  const year = cursor.getFullYear()
  const { data } = useApi('/leave/holidays', { year })
  const byDate = useMemo(() => Object.fromEntries((data?.items || []).map((h) => [h.date, h])), [data])
  const last = new Date(year, cursor.getMonth() + 1, 0)
  const cells = useMemo(() => {
    const offset = (cursor.getDay() + 6) % 7 // weeks start on Monday
    return [...Array(offset).fill(null), ...Array.from({ length: last.getDate() }, (_, i) => new Date(year, cursor.getMonth(), i + 1))]
  }, [cursor]) // eslint-disable-line react-hooks/exhaustive-deps
  const monthHolidays = (data?.items || []).filter((h) => h.date.startsWith(`${year}-${String(cursor.getMonth() + 1).padStart(2, '0')}`))
  const todayIso = iso(new Date())
  return (
    <Card title={cursor.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })} action={
      <div className="flex gap-1">
        <Button size="sm" variant="secondary" aria-label="Previous month" onClick={() => setCursor(new Date(year, cursor.getMonth() - 1, 1))}>←</Button>
        <Button size="sm" variant="secondary" onClick={() => setCursor(new Date(new Date().getFullYear(), new Date().getMonth(), 1))}>Today</Button>
        <Button size="sm" variant="secondary" aria-label="Next month" onClick={() => setCursor(new Date(year, cursor.getMonth() + 1, 1))}>→</Button>
      </div>}>
      <div className="grid grid-cols-7 gap-px overflow-hidden rounded-lg border border-slate-200 bg-slate-200 text-xs" role="grid" aria-label="Holiday calendar">
        <div role="row" className="contents">{['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((d) => <div key={d} role="columnheader" className="bg-slate-50 py-1.5 text-center font-semibold text-slate-500">{d}</div>)}</div>
        {Array.from({ length: Math.ceil(cells.length / 7) }, (_, w) => <div key={w} role="row" className="contents">{cells.slice(w * 7, w * 7 + 7).map((d, j) => { const i = w * 7 + j;
          const key = d && iso(d)
          const h = key && byDate[key]
          const weekend = d && (d.getDay() === 0 || d.getDay() === 6)
          const clickable = canEdit && d && (h || !weekend)
          const Cell = clickable ? 'button' : 'div'
          return (
            <Cell key={i} role="gridcell" type={clickable ? 'button' : undefined}
              onClick={clickable ? () => setEditing(h || { date: key }) : undefined}
              aria-label={d ? `${d.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' })}${h ? `: ${h.name}` : ''}` : undefined}
              className={`min-h-16 p-1 text-left ${weekend ? 'bg-slate-50' : 'bg-white'} ${clickable ? 'hover:bg-brand-50' : ''}`}>
              {d && <>
                <span className={`text-slate-500 ${key === todayIso ? 'rounded-full bg-brand-600 px-1.5 py-0.5 font-semibold text-white' : ''}`}>{d.getDate()}</span>
                {h && <p className="mt-0.5 truncate rounded bg-purple-100 px-1 text-purple-800" title={h.name}>{h.name}</p>}
              </>}
            </Cell>
          )
        })}</div>)}
      </div>
      <h3 className="mb-1 mt-4 text-sm font-semibold text-slate-700">This month</h3>
      {monthHolidays.length ? (
        <ul className="divide-y divide-slate-100 text-sm">{monthHolidays.map((h) => <li key={h.id} className="flex justify-between py-1.5"><span>{h.name}</span><span className="text-slate-500">{fmtDate(h.date)}</span></li>)}</ul>
      ) : <p className="text-sm text-slate-500">No holidays this month.</p>}
      {canEdit && <HolidayModal open={!!editing} onClose={() => setEditing(null)} holiday={editing?.id ? editing : null} presetDate={editing?.id ? undefined : editing?.date} year={year} />}
    </Card>
  )
}

/** Company holiday calendar for every role: a month view and a yearly list. Founders and HR can edit; the API enforces it. */
export default function HolidaysPage() {
  const { role } = useAuth()
  const canEdit = role === 'founder' || role === 'hr'
  const [tab, setTab] = useState('calendar')
  return (
    <>
      <PageHeader title="Holiday calendar" description={canEdit ? 'Company holidays. Click a day to add a holiday, or a holiday to edit it. The working week is Monday to Friday.' : 'Company holidays. The working week is Monday to Friday.'} />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: 'calendar', label: 'Calendar' }, { id: 'list', label: 'List' }]} />
      <div className="max-w-3xl">
        {tab === 'calendar' ? <MonthView canEdit={canEdit} /> : <HolidayCalendar canEdit={canEdit} />}
      </div>
    </>
  )
}
