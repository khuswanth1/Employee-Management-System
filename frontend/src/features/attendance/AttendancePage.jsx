import { useEffect, useState } from 'react'
import { Alert, Badge, Button, Card, ConfirmDialog, EmptyState, ErrorState, Field, Input, Modal, PageHeader, PageLoader, Pagination, Select, StatCard, Table, Textarea } from '../../components/ui'
import { api, fieldErrors } from '../../lib/api'
import { fmtDate, fmtTimeIn } from '../../lib/format'
import { useAction, useApi } from '../../lib/hooks'
import { hm, statusInfo } from './labels'

function useNow() {
  const [now, setNow] = useState(Date.now())
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t) }, [])
  return now
}

/** One-shot position request; rejects with a readable message. */
const getPosition = () => new Promise((resolve, reject) => {
  if (!navigator.geolocation) return reject(new Error('This browser cannot share its location.'))
  navigator.geolocation.getCurrentPosition(
    (p) => resolve({ lat: p.coords.latitude, lng: p.coords.longitude }),
    (e) => reject(new Error(e.code === 1 ? 'Location access was denied. Allow it in the browser to check in at this branch, or choose work from home.' : 'Your location could not be determined.')),
    { enableHighAccuracy: true, timeout: 15000, maximumAge: 30000 },
  )
})

function CorrectionDialog({ onClose, prefill }) {
  const [f, setF] = useState({ check_in: prefill?.check_in || '', check_out: prefill?.check_out || '', reason: '' })
  const send = useAction(() => api.post('/attendance/corrections', f), { invalidate: ['/attendance'], success: 'Correction requested', onSuccess: onClose })
  const fe = fieldErrors(send.error)
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }))
  return (
    <Modal open onClose={onClose} title="Request an attendance correction"
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={send.isPending} disabled={!f.check_in || !f.check_out || f.reason.trim().length < 5} onClick={() => send.mutate()}>Send request</Button></>}>
      <div className="space-y-4">
        {send.error && !Object.keys(fe).length && <Alert>{send.error.message}</Alert>}
        <p className="text-sm text-slate-600">Enter the times as they should have been, in your local time. Your manager or HR decides; nothing changes until it is approved.</p>
        <Field label="Check-in" required error={fe.check_in}><Input type="datetime-local" value={f.check_in} onChange={set('check_in')} /></Field>
        <Field label="Check-out" required error={fe.check_out}><Input type="datetime-local" value={f.check_out} onChange={set('check_out')} /></Field>
        <Field label="Reason" required error={fe.reason} hint="At least 5 characters"><Textarea value={f.reason} onChange={set('reason')} maxLength={1000} /></Field>
      </div>
    </Modal>
  )
}

function MyRequests() {
  const { data } = useApi('/attendance/corrections/mine', { page_size: 5 })
  const [cancelling, setCancelling] = useState(null)
  const cancel = useAction(() => api.del(`/attendance/corrections/${cancelling}`), { invalidate: ['/attendance'], success: 'Request cancelled', onSuccess: () => setCancelling(null) })
  if (!data?.items?.length) return null
  const tone = { pending: 'amber', approved: 'green', rejected: 'red', cancelled: 'gray' }
  return (
    <Card title="My correction requests" className="mt-6" pad={false}>
      <div className="p-1">
        <Table caption="My correction requests" rows={data.items}
          columns={[
            { key: 'work_date', header: 'Day', render: (c) => fmtDate(c.work_date) },
            { key: 'times', header: 'Requested', render: (c) => `${fmtTimeIn(c.check_in, c.timezone)} – ${fmtTimeIn(c.check_out, c.timezone)}` },
            { key: 'status', header: 'Status', render: (c) => <Badge tone={tone[c.status]}>{c.status}</Badge> },
            { key: 'note', header: 'Decision', render: (c) => c.decision_note || '—' },
            { key: 'a', header: '', render: (c) => (c.status === 'pending' ? <Button size="sm" variant="ghost" onClick={() => setCancelling(c.id)}>Cancel</Button> : null) },
          ]} />
      </div>
      <ConfirmDialog open={!!cancelling} title="Cancel request" confirmLabel="Cancel request" loading={cancel.isPending} onClose={() => setCancelling(null)} onConfirm={() => cancel.mutate()}
        message="Withdraw this correction request?" />
    </Card>
  )
}

export default function AttendancePage() {
  const now = useNow()
  const [page, setPage] = useState(1)
  const [mode, setMode] = useState('office')
  const [locating, setLocating] = useState(false)
  const [locError, setLocError] = useState(null)
  const [correcting, setCorrecting] = useState(null)
  const { data: today, isLoading, error, refetch } = useApi('/attendance/today')
  const { data: hist } = useApi('/attendance/mine', { page, page_size: 10 })
  const rec = today?.record
  const act = (path, msg) => useAction(() => api.post(`/attendance/${path}`), { invalidate: ['/attendance', '/dashboard'], success: msg, refreshOnError: true }) // eslint-disable-line react-hooks/rules-of-hooks
  const checkOut = act('check-out', 'Checked out')
  const brkStart = act('break/start', 'Break started'), brkEnd = act('break/end', 'Welcome back')
  const checkIn = useAction((body) => api.post('/attendance/check-in', body), { invalidate: ['/attendance', '/dashboard'], success: 'Checked in', refreshOnError: true })

  const doCheckIn = async () => {
    setLocError(null)
    const body = { work_mode: mode }
    if (mode === 'office' && today?.geofence_required) {
      setLocating(true)
      try { Object.assign(body, await getPosition()) } catch (e) { setLocError(e.message); return } finally { setLocating(false) }
    }
    checkIn.mutate(body)
  }

  if (isLoading) return <PageLoader />
  if (error) return <ErrorState error={error} onRetry={refetch} />
  const iso = (d) => (d.endsWith('Z') || d.includes('+') ? d : `${d}Z`)
  let elapsed = 0
  if (rec && !rec.check_out) {
    const brk = rec.breaks.reduce((a, b) => a + ((b.end ? new Date(iso(b.end)) : now) - new Date(iso(b.start))), 0)
    elapsed = Math.max(0, now - new Date(iso(rec.check_in)) - brk)
  } else if (rec) elapsed = rec.worked_hours * 3600000
  const hms = (ms) => { const s = Math.floor(ms / 1000); return [Math.floor(s / 3600), Math.floor(s / 60) % 60, s % 60].map((n) => String(n).padStart(2, '0')).join(':') }
  const state = !rec ? 'Not checked in' : rec.check_out ? 'Day complete' : rec.on_break ? 'On break' : 'Working'
  const sh = today?.shift

  return (
    <>
      <PageHeader title="Attendance" description={`Check in, take breaks and review your hours. Times use ${today?.timezone || 'UTC'}.`}
        actions={<Button variant="secondary" onClick={() => setCorrecting({})}>Request a correction</Button>} />
      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="Today" className="lg:col-span-2">
          <div className="flex flex-col items-center py-4 text-center">
            <p className="text-sm text-slate-500" aria-live="polite">{state}{rec?.work_mode === 'wfh' ? ' · from home' : ''}</p>
            <p className="my-2 font-mono text-5xl font-semibold tabular-nums text-slate-900" aria-label="Time worked today">{hms(elapsed)}</p>
            {rec && <p className="text-sm text-slate-500">In at {fmtTimeIn(rec.check_in, today?.timezone)}{rec.check_out ? ` · Out at ${fmtTimeIn(rec.check_out, today?.timezone)}` : ''}</p>}
            {rec && (rec.late_minutes > 0 || rec.early_minutes > 0) && (
              <p className="mt-1 flex gap-2 text-xs">{rec.late_minutes > 0 && <Badge tone="amber">Late {hm(rec.late_minutes)}</Badge>}{rec.early_minutes > 0 && <Badge tone="amber">Left early {hm(rec.early_minutes)}</Badge>}</p>
            )}
            {sh && <p className="mt-1 text-xs text-slate-500">Shift: {sh.name}{sh.start ? ` (${sh.start.slice(0, 5)}–${sh.end.slice(0, 5)}, ${sh.grace_minutes} min grace)` : ` (flexible, ${sh.required_hours} h)`}</p>}
            {locError && <div className="mt-3 w-full max-w-md text-left"><Alert>{locError}</Alert></div>}
            {!rec && today?.allow_wfh && (
              <div className="mt-4 w-48">
                <Field label="Working from"><Select value={mode} onChange={(e) => setMode(e.target.value)}><option value="office">Office</option><option value="wfh">Home</option></Select></Field>
              </div>
            )}
            <div className="mt-6 flex flex-wrap justify-center gap-3">
              {!rec && <Button loading={checkIn.isPending || locating} onClick={doCheckIn}>Check in</Button>}
              {rec && !rec.check_out && !rec.on_break && <Button variant="secondary" loading={brkStart.isPending} onClick={() => brkStart.mutate()}>Start break</Button>}
              {rec && !rec.check_out && rec.on_break && <Button variant="secondary" loading={brkEnd.isPending} onClick={() => brkEnd.mutate()}>End break</Button>}
              {rec && !rec.check_out && <Button variant="danger" loading={checkOut.isPending} onClick={() => checkOut.mutate()}>Check out</Button>}
            </div>
          </div>
        </Card>
        <div className="grid gap-4 content-start">
          <StatCard title="Breaks today" value={rec ? `${rec.break_minutes} min` : '—'} />
          <StatCard title="Overtime today" value={rec ? `${rec.overtime_hours} h` : '—'} />
        </div>
      </div>
      <MyRequests />
      <h2 className="mb-3 mt-8 text-lg font-semibold">Last 30 days</h2>
      <Table caption="Attendance history" rows={hist?.items} empty={<EmptyState title="No attendance records" />}
        columns={[
          { key: 'work_date', header: 'Date', render: (a) => fmtDate(a.work_date) },
          { key: 'check_in', header: 'In', render: (a) => fmtTimeIn(a.check_in, a.timezone) },
          { key: 'check_out', header: 'Out', render: (a) => (a.check_out ? <>{fmtTimeIn(a.check_out, a.timezone)}{a.auto_closed && <span title="No check-out was recorded; the day was closed automatically"> ⚠</span>}</> : '—') },
          { key: 'break_minutes', header: 'Breaks', render: (a) => `${a.break_minutes} min` },
          { key: 'worked_hours', header: 'Worked', render: (a) => `${a.worked_hours} h` },
          { key: 'overtime_hours', header: 'Overtime', render: (a) => (a.overtime_hours ? `${a.overtime_hours} h` : '—') },
          { key: 'status', header: 'Status', render: (a) => (a.status ? <Badge tone={statusInfo(a.status)[1]}>{statusInfo(a.status)[0]}</Badge> : '—') },
          { key: 'fix', header: '', render: (a) => (a.check_out ? <Button size="sm" variant="ghost" onClick={() => setCorrecting({})}>Correct</Button> : null) },
        ]} />
      {hist && <Pagination page={hist.page} pageSize={hist.page_size} total={hist.total} onChange={setPage} />}
      {correcting && <CorrectionDialog prefill={correcting} onClose={() => setCorrecting(null)} />}
    </>
  )
}
