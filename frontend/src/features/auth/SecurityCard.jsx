import { useState } from 'react'
import { Alert, Badge, Button, Card, ConfirmDialog, Field, Input, Modal, PasswordInput } from '../../components/ui'
import { api, fieldErrors } from '../../lib/api'
import { useAction } from '../../lib/hooks'
import { useAuth } from './AuthContext'

function EnrolDialog({ onClose, onDone, base }) {
  const [setup, setSetup] = useState(null)
  const [code, setCode] = useState('')
  const [codes, setCodes] = useState(null)
  const start = useAction(() => api.post(`${base}/mfa/setup`), { onSuccess: setSetup })
  const enable = useAction(() => api.post(`${base}/mfa/enable`, { code: code.trim() }), { onSuccess: (r) => { setCodes(r.recovery_codes); onDone() } })

  if (codes) {
    return (
      <Modal open onClose={onClose} title="Save your recovery codes" footer={<Button onClick={onClose}>I have saved them</Button>}>
        <Alert tone="amber">Each code works once if you lose your phone. They are shown only now.</Alert>
        <ul className="mt-3 grid grid-cols-2 gap-2 font-mono text-sm" aria-label="Recovery codes">{codes.map((c) => <li key={c}>{c}</li>)}</ul>
        <Button variant="secondary" size="sm" className="mt-3" onClick={() => navigator.clipboard?.writeText(codes.join('\n'))}>Copy codes</Button>
      </Modal>
    )
  }
  return (
    <Modal open onClose={onClose} title="Set up two-step verification"
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button>
        {setup ? <Button loading={enable.isPending} disabled={code.trim().length !== 6} onClick={() => enable.mutate()}>Turn on</Button>
          : <Button loading={start.isPending} onClick={() => start.mutate()}>Start</Button>}</>}>
      {!setup ? (
        <p className="text-sm text-slate-600">You will need an authenticator app (for example Google Authenticator, Microsoft Authenticator or 1Password). Sign-in will then ask for a 6-digit code.</p>
      ) : (
        <div className="space-y-3 text-sm">
          <p>Add this account in your authenticator app: choose <em>enter a setup key</em> and paste:</p>
          <p className="select-all break-all rounded bg-slate-100 p-2 font-mono" aria-label="Setup key">{setup.secret}</p>
          <p className="text-xs text-slate-500">On a phone you can also <a className="text-brand-700 underline" href={setup.otpauth_uri}>open it in your authenticator</a>.</p>
          <Field label="6-digit code from the app" required error={enable.error?.message}>
            <Input value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} inputMode="numeric" autoComplete="one-time-code" maxLength={6} />
          </Field>
        </div>
      )}
    </Modal>
  )
}

function DisableDialog({ onClose, onDone, base }) {
  const [f, setF] = useState({ password: '', code: '' })
  const off = useAction(() => api.post(`${base}/mfa/disable`, { password: f.password, code: f.code.trim() }), { success: 'Two-step verification is off', onSuccess: onDone })
  const fe = fieldErrors(off.error)
  return (
    <Modal open onClose={onClose} title="Turn off two-step verification"
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button variant="danger" loading={off.isPending} disabled={!f.password || f.code.trim().length < 6} onClick={() => off.mutate()}>Turn off</Button></>}>
      <div className="space-y-3">
        {off.error && !Object.keys(fe).length && <Alert>{off.error.message}</Alert>}
        <Field label="Password" required><PasswordInput autoComplete="current-password" value={f.password} onChange={(e) => setF((s) => ({ ...s, password: e.target.value }))} /></Field>
        <Field label="Authenticator or recovery code" required><Input value={f.code} onChange={(e) => setF((s) => ({ ...s, code: e.target.value }))} autoComplete="one-time-code" maxLength={20} /></Field>
      </div>
    </Modal>
  )
}

/** `platform`: the platform administrator's own endpoints (/auth/platform/...), and no e-mail verification row. */
export default function SecurityCard({ platform = false }) {
  const base = platform ? '/auth/platform' : '/auth'
  const { user, refresh, logout } = useAuth()
  const [dialog, setDialog] = useState(null)
  const verify = useAction(() => api.post('/auth/verify-email/request'), { success: 'Verification e-mail sent' })
  const everywhere = useAction(() => api.post(`${base}/logout-all`), { onSuccess: () => logout() })
  return (
    <Card title={platform ? 'Your sign-in security' : 'Sign-in security'}>
      <ul className="space-y-4 text-sm">
        {!platform && <li className="flex items-center justify-between gap-4">
          <div><p className="font-medium">E-mail address</p><p className="text-slate-500">{user.email}</p></div>
          {user.email_verified ? <Badge tone="green">Verified</Badge>
            : <Button size="sm" variant="secondary" loading={verify.isPending} onClick={() => verify.mutate()}>Send verification e-mail</Button>}
        </li>}
        <li className="flex items-center justify-between gap-4">
          <div><p className="font-medium">Two-step verification</p><p className="text-slate-500">{user.mfa_enabled ? 'On: sign-in asks for a code from your authenticator app.' : 'Off: add a second step to protect your account.'}</p></div>
          {user.mfa_enabled ? <Button size="sm" variant="secondary" onClick={() => setDialog('off')}>Turn off</Button> : <Button size="sm" onClick={() => setDialog('on')}>Set up</Button>}
        </li>
        <li className="flex items-center justify-between gap-4">
          <div><p className="font-medium">Sign out everywhere</p><p className="text-slate-500">Ends every session on every device, including this one.</p></div>
          <Button size="sm" variant="secondary" onClick={() => setDialog('all')}>Sign out all</Button>
        </li>
      </ul>
      {dialog === 'on' && <EnrolDialog base={base} onClose={() => setDialog(null)} onDone={() => refresh()} />}
      {dialog === 'off' && <DisableDialog base={base} onClose={() => setDialog(null)} onDone={() => { setDialog(null); refresh() }} />}
      <ConfirmDialog open={dialog === 'all'} title="Sign out everywhere" confirmLabel="Sign out all" loading={everywhere.isPending} onClose={() => setDialog(null)} onConfirm={() => everywhere.mutate()}
        message="Every session on every device will end, and you will have to sign in again." />
    </Card>
  )
}
