import { useState } from 'react'
import { Alert, Badge, Button, EmptyState, ErrorState, Field, Input, Modal, PageHeader, PageLoader, Pagination, Select, StatusBadge, Table, Tabs } from '../../components/ui'
import { api, fieldErrors } from '../../lib/api'
import { fmtDateTime } from '../../lib/format'
import { useAction, useApi } from '../../lib/hooks'
import { useToast } from '../../components/ui'

function HookModal({ hook, events, onClose, onSecret }) {
  const [f, setF] = useState({ url: hook?.url || '', events: hook?.events || [], is_active: hook?.is_active ?? true })
  const save = useAction(() => (hook ? api.patch(`/webhooks/${hook.id}`, f) : api.post('/webhooks', f)), {
    invalidate: ['/webhooks'], success: 'Webhook saved', onSuccess: (r) => { onClose(); if (r.secret) onSecret(r.secret) },
  })
  const fe = fieldErrors(save.error)
  const toggle = (e) => setF((s) => ({ ...s, events: s.events.includes(e) ? s.events.filter((x) => x !== e) : [...s.events, e] }))
  return (
    <Modal open onClose={onClose} wide title={hook ? 'Edit webhook' : 'New webhook'} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={save.isPending} onClick={() => save.mutate()}>Save</Button></>}>
      <div className="space-y-4">
        {save.error && !Object.keys(fe).length && <Alert>{save.error.message}</Alert>}
        <Field label="Endpoint URL" required error={fe.url} hint="Must be a public HTTPS URL"><Input type="url" value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} placeholder="https://example.com/hooks/worksphere" /></Field>
        <fieldset><legend className="mb-1 text-sm font-medium text-slate-700">Events</legend>
          {fe.events && <p className="mb-1 text-xs text-red-600">{fe.events}</p>}
          <div className="grid gap-1.5 sm:grid-cols-2">{events.map((e) => (
            <label key={e} className="flex items-center gap-2 text-sm"><input type="checkbox" className="h-4 w-4 accent-brand-600" checked={f.events.includes(e)} onChange={() => toggle(e)} />{e}</label>))}</div></fieldset>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" className="h-4 w-4 accent-brand-600" checked={f.is_active} onChange={(e) => setF({ ...f, is_active: e.target.checked })} />Active</label>
      </div>
    </Modal>
  )
}

export default function WebhooksPage() {
  const toast = useToast()
  const [tab, setTab] = useState('endpoints')
  const [edit, setEdit] = useState(null)
  const [secret, setSecret] = useState(null)
  const [f, setF] = useState({ status: '', webhook_id: '' })
  const [page, setPage] = useState(1)
  const { data, isLoading, error, refetch } = useApi('/webhooks')
  const { data: ev } = useApi('/webhooks/events')
  const { data: log } = useApi('/webhooks/deliveries/log', { ...f, page, page_size: 15 }, { enabled: tab === 'log' })
  const test = useAction((h) => api.post(`/webhooks/${h.id}/test`), { invalidate: ['/webhooks'], success: (d) => `Test ${d.status}${d.last_status_code ? ` (HTTP ${d.last_status_code})` : d.last_error ? `: ${d.last_error}` : ''}` })
  const rotate = useAction((h) => api.post(`/webhooks/${h.id}/rotate-secret`), { onSuccess: (r) => setSecret(r.secret) })
  const del = useAction((h) => api.del(`/webhooks/${h.id}`), { invalidate: ['/webhooks'], success: 'Webhook deleted' })
  const retry = useAction((d) => api.post(`/webhooks/deliveries/${d.id}/retry`), { invalidate: ['/webhooks'], success: 'Queued for retry' })

  return (
    <>
      <PageHeader title="Webhooks" description="Send signed event notifications to external systems" actions={<Button onClick={() => setEdit({})}>New webhook</Button>} />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: 'endpoints', label: 'Endpoints' }, { id: 'log', label: 'Delivery log' }]} />
      {tab === 'endpoints' && (isLoading ? <PageLoader /> : error ? <ErrorState error={error} onRetry={refetch} /> : (
          <Table caption="Webhook endpoints" rows={data.items} empty={<EmptyState title="No webhooks" description="Add an endpoint to start receiving events." action={<Button onClick={() => setEdit({})}>New webhook</Button>} />}
            columns={[
              { key: 'url', header: 'Endpoint', render: (h) => <span className="font-mono text-xs">{h.url}</span> },
              { key: 'events', header: 'Events', render: (h) => <div className="flex max-w-xs flex-wrap gap-1">{h.events.slice(0, 3).map((e) => <Badge key={e} tone="indigo">{e}</Badge>)}{h.events.length > 3 && <Badge>+{h.events.length - 3}</Badge>}</div> },
              { key: 'is_active', header: 'State', render: (h) => <StatusBadge value={h.is_active ? 'active' : 'suspended'} /> },
              { key: 'act', header: '', render: (h) => <div className="flex gap-3 text-sm"><button className="text-brand-700 hover:underline" onClick={() => test.mutate(h)}>Test</button><button className="text-brand-700 hover:underline" onClick={() => setEdit(h)}>Edit</button>
                <button className="text-brand-700 hover:underline" onClick={() => window.confirm('Rotate the signing secret? The old one stops working.') && rotate.mutate(h)}>Rotate secret</button>
                <button className="text-red-600 hover:underline" onClick={() => window.confirm('Delete this webhook and its delivery history?') && del.mutate(h)}>Delete</button></div> },
            ]} />
      ))}
      {tab === 'log' && (
        <>
          <div className="mb-4 flex gap-3">
            <Select aria-label="Status" className="w-40" value={f.status} onChange={(e) => { setF({ ...f, status: e.target.value }); setPage(1) }}><option value="">All statuses</option><option value="pending">Pending</option><option value="success">Success</option><option value="failed">Failed</option></Select>
            <Select aria-label="Endpoint" className="w-64" value={f.webhook_id} onChange={(e) => { setF({ ...f, webhook_id: e.target.value }); setPage(1) }}><option value="">All endpoints</option>{data?.items.map((h) => <option key={h.id} value={h.id}>{h.url}</option>)}</Select>
          </div>
          {!log ? <PageLoader /> : <>
            <Table caption="Webhook deliveries" rows={log.items} empty={<EmptyState title="No deliveries yet" />}
              columns={[{ key: 'event', header: 'Event' }, { key: 'status', header: 'Status', render: (d) => <StatusBadge value={d.status} /> }, { key: 'attempts', header: 'Attempts' },
                { key: 'code', header: 'HTTP', render: (d) => d.last_status_code || '—' }, { key: 'err', header: 'Error', render: (d) => d.last_error || '—' }, { key: 'created_at', header: 'Created', render: (d) => fmtDateTime(d.created_at) },
                { key: 'act', header: '', render: (d) => d.status !== 'success' && <Button size="sm" variant="secondary" onClick={() => retry.mutate(d)}>Retry now</Button> }]} />
            <Pagination page={log.page} pageSize={log.page_size} total={log.total} onChange={setPage} /></>}
        </>
      )}
      {edit && <HookModal hook={edit.id ? edit : null} events={ev?.items || []} onClose={() => setEdit(null)} onSecret={setSecret} />}
      <Modal open={!!secret} onClose={() => setSecret(null)} title="Signing secret" footer={<><Button variant="secondary" onClick={() => { navigator.clipboard?.writeText(secret); toast('Copied') }}>Copy</Button><Button onClick={() => setSecret(null)}>Done</Button></>}>
        <Alert tone="amber">Copy this secret now. For security it is shown only once and cannot be retrieved later.</Alert>
        <p className="mt-3 break-all rounded-lg bg-slate-900 p-3 font-mono text-sm text-emerald-300">{secret}</p>
      </Modal>
    </>
  )
}
