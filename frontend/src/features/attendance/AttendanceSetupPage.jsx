import { useState } from 'react'
import { Alert, Badge, Button, Card, ConfirmDialog, EmptyState, ErrorState, Field, Input, Modal, PageHeader, PageLoader, Table } from '../../components/ui'
import MultiSelect from '../../components/MultiSelect'
import { api, fieldErrors } from '../../lib/api'
import { useAction, useApi } from '../../lib/hooks'

const blank = { name: '', flexible: false, start_time: '09:00', end_time: '18:00', grace_minutes: 10, required_hours: 8, half_day_hours: '', overtime_after_hours: '' }
const num = (v) => (v === '' || v == null ? null : Number(v))
const hhmm = (t) => (t ? t.slice(0, 5) : '')

function ShiftDialog({ shift, onClose }) {
  const [f, setF] = useState(shift ? { ...blank, ...shift, start_time: hhmm(shift.start_time), end_time: hhmm(shift.end_time), half_day_hours: shift.half_day_hours ?? '', overtime_after_hours: shift.overtime_after_hours ?? '' } : blank)
  const body = () => ({
    name: f.name.trim(), start_time: f.flexible ? null : f.start_time, end_time: f.flexible ? null : f.end_time, grace_minutes: Number(f.grace_minutes || 0),
    required_hours: Number(f.required_hours), half_day_hours: num(f.half_day_hours), overtime_after_hours: num(f.overtime_after_hours),
  })
  const save = useAction(() => (shift ? api.patch(`/attendance/shifts/${shift.id}`, body()) : api.post('/attendance/shifts', body())),
    { invalidate: ['/attendance/shifts'], success: shift ? 'Shift updated' : 'Shift created', onSuccess: onClose })
  const fe = fieldErrors(save.error)
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }))
  const overnight = !f.flexible && f.start_time && f.end_time && f.end_time <= f.start_time
  return (
    <Modal open onClose={onClose} title={shift ? 'Edit shift' : 'New shift'} wide
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={save.isPending} disabled={f.name.trim().length < 2} onClick={() => save.mutate()}>Save</Button></>}>
      <div className="grid gap-4 sm:grid-cols-2">
        {save.error && !Object.keys(fe).length && <div className="sm:col-span-2"><Alert>{save.error.message}</Alert></div>}
        {shift && <div className="sm:col-span-2"><Alert tone="amber">Changes apply to future check-ins. Days already recorded keep the numbers they were closed with.</Alert></div>}
        <Field label="Name" required error={fe.name}><Input value={f.name} onChange={set('name')} maxLength={80} /></Field>
        <label className="flex items-center gap-2 pt-7 text-sm"><input type="checkbox" checked={f.flexible} onChange={(e) => setF((s) => ({ ...s, flexible: e.target.checked }))} /> Flexible hours (no fixed start or end)</label>
        {!f.flexible && <>
          <Field label="Starts" required error={fe.start_time}><Input type="time" value={f.start_time} onChange={set('start_time')} /></Field>
          <Field label="Ends" required error={fe.end_time} hint={overnight ? 'Ends the next day (overnight shift)' : undefined}><Input type="time" value={f.end_time} onChange={set('end_time')} /></Field>
          <Field label="Grace period (minutes)" hint="Lateness and early departure only count beyond this" error={fe.grace_minutes}><Input type="number" min="0" max="120" value={f.grace_minutes} onChange={set('grace_minutes')} /></Field>
        </>}
        <Field label="Required hours per day" required error={fe.required_hours}><Input type="number" min="1" max="16" step="0.25" value={f.required_hours} onChange={set('required_hours')} /></Field>
        <Field label="Half-day from (hours)" hint="Blank = half the required hours" error={fe.half_day_hours}><Input type="number" min="0.5" max="16" step="0.25" value={f.half_day_hours} onChange={set('half_day_hours')} /></Field>
        <Field label="Overtime after (hours)" hint="Blank = the required hours" error={fe.overtime_after_hours}><Input type="number" min="0.5" max="24" step="0.25" value={f.overtime_after_hours} onChange={set('overtime_after_hours')} /></Field>
      </div>
    </Modal>
  )
}

function AssignDialog({ shift, onClose }) {
  const { data: dir } = useApi('/employees/directory')
  const [ids, setIds] = useState([])
  const assign = useAction(() => api.post('/attendance/shift-assignments', { shift_id: shift.id, user_ids: ids }),
    { invalidate: ['/attendance/shifts'], success: (r) => `${r.updated} people assigned`, onSuccess: onClose })
  const options = (dir?.items || []).map((u) => ({ value: u.id, label: u.full_name, hint: u.designation || u.role }))
  return (
    <Modal open onClose={onClose} title={`Assign “${shift.name}”`}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={assign.isPending} disabled={!ids.length} onClick={() => assign.mutate()}>Assign</Button></>}>
      <div className="space-y-3">
        {assign.error && <Alert>{assign.error.message}</Alert>}
        <p className="text-sm text-slate-600">Applies to their next check-in. People outside your scope cannot be selected.</p>
        <MultiSelect options={options} value={ids} onChange={setIds} placeholder="Search people…" />
      </div>
    </Modal>
  )
}

function Fence({ row }) {
  const [f, setF] = useState({ lat: row.lat ?? '', lng: row.lng ?? '', radius_m: row.radius_m ?? 200, required: row.required })
  const [msg, setMsg] = useState(null)
  const save = useAction(() => api.put(`/attendance/geofences/${row.branch_id}`, { lat: num(f.lat), lng: num(f.lng), radius_m: num(f.radius_m), required: f.required }),
    { invalidate: ['/attendance/geofences'], success: `${row.branch}: location rules saved` })
  const fe = fieldErrors(save.error)
  const here = () => {
    setMsg(null)
    navigator.geolocation?.getCurrentPosition(
      (p) => setF((s) => ({ ...s, lat: +p.coords.latitude.toFixed(6), lng: +p.coords.longitude.toFixed(6) })),
      () => setMsg('Your location could not be read. Type the coordinates instead.'), { timeout: 10000 })
  }
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }))
  return (
    <div className="rounded-lg border border-slate-200 p-4">
      <div className="mb-3 flex items-center justify-between"><h3 className="font-medium">{row.branch}</h3>{f.required ? <Badge tone="green">Enforced</Badge> : <Badge>Not enforced</Badge>}</div>
      {save.error && !Object.keys(fe).length && <div className="mb-3"><Alert>{save.error.message}</Alert></div>}
      {msg && <div className="mb-3"><Alert tone="amber">{msg}</Alert></div>}
      <div className="grid gap-3 sm:grid-cols-4">
        <Field label="Latitude" error={fe.lat}><Input type="number" step="any" value={f.lat} onChange={set('lat')} /></Field>
        <Field label="Longitude" error={fe.lng}><Input type="number" step="any" value={f.lng} onChange={set('lng')} /></Field>
        <Field label="Radius (m)" error={fe.radius_m}><Input type="number" min="20" value={f.radius_m} onChange={set('radius_m')} /></Field>
        <div className="flex items-end"><Button variant="secondary" onClick={here}>Use my location</Button></div>
      </div>
      <div className="mt-3 flex items-center justify-between">
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.required} onChange={(e) => setF((s) => ({ ...s, required: e.target.checked }))} /> Office check-ins must be inside this area (work from home is exempt)</label>
        <Button loading={save.isPending} onClick={() => save.mutate()}>Save</Button>
      </div>
    </div>
  )
}

export default function AttendanceSetupPage() {
  const { data, isLoading, error, refetch } = useApi('/attendance/shifts')
  const { data: fences } = useApi('/attendance/geofences')
  const [dlg, setDlg] = useState(null) // { kind: 'edit'|'assign'|'delete', shift? }
  const del = useAction(() => api.del(`/attendance/shifts/${dlg.shift.id}`), { invalidate: ['/attendance/shifts'], success: 'Shift deleted', onSuccess: () => setDlg(null) })
  if (isLoading) return <PageLoader />
  if (error) return <ErrorState error={error} onRetry={refetch} />
  return (
    <>
      <PageHeader title="Shifts and locations" description="Working hours, grace periods and where people may check in."
        actions={<Button onClick={() => setDlg({ kind: 'edit' })}>New shift</Button>} />
      <Card title="Shifts" pad={false}>
        <div className="p-1">
          <Table caption="Shifts" rows={data.items} empty={<EmptyState title="No shifts yet" description="Without a shift people work flexible hours against the company's standard day." />}
            columns={[
              { key: 'name', header: 'Name', render: (s) => <>{s.name}{!s.is_active && <> <Badge>inactive</Badge></>}</> },
              { key: 'time', header: 'Hours', render: (s) => (s.flexible ? 'Flexible' : `${hhmm(s.start_time)} – ${hhmm(s.end_time)}${s.overnight ? ' (+1 day)' : ''}`) },
              { key: 'grace_minutes', header: 'Grace', render: (s) => (s.flexible ? '—' : `${s.grace_minutes} min`) },
              { key: 'required_hours', header: 'Required', render: (s) => `${s.required_hours} h` },
              { key: 'assigned', header: 'People' },
              { key: 'a', header: '', render: (s) => (
                <div className="flex gap-2">
                  <Button size="sm" variant="secondary" onClick={() => setDlg({ kind: 'assign', shift: s })} disabled={!s.is_active}>Assign</Button>
                  <Button size="sm" variant="ghost" onClick={() => setDlg({ kind: 'edit', shift: s })}>Edit</Button>
                  <Button size="sm" variant="ghost" onClick={() => setDlg({ kind: 'delete', shift: s })}>Delete</Button>
                </div>) },
            ]} />
        </div>
      </Card>
      <h2 className="mb-3 mt-8 text-lg font-semibold">Check-in locations</h2>
      <div className="space-y-4">
        {fences?.items?.length ? fences.items.map((r) => <Fence key={`${r.branch_id}-${r.lat}-${r.lng}-${r.radius_m}-${r.required}`} row={r} />) : <EmptyState title="No branches" description="Create a branch first to set a check-in area." />}
      </div>
      {dlg?.kind === 'edit' && <ShiftDialog shift={dlg.shift} onClose={() => setDlg(null)} />}
      {dlg?.kind === 'assign' && <AssignDialog shift={dlg.shift} onClose={() => setDlg(null)} />}
      <ConfirmDialog open={dlg?.kind === 'delete'} danger title="Delete shift" confirmLabel="Delete" loading={del.isPending} onClose={() => setDlg(null)} onConfirm={() => del.mutate()}
        message={`Delete “${dlg?.shift?.name}”? A shift that is assigned or has attendance history cannot be deleted; deactivate it instead.`} />
    </>
  )
}
