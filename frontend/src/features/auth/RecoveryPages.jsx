import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Alert, Button, Field, Input, PasswordInput } from '../../components/ui'
import { api, fieldErrors } from '../../lib/api'
import AuthLayout from './AuthLayout'

const box = 'space-y-4 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm'

export function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [state, setState] = useState({ busy: false, sent: false, error: null })
  const submit = async (e) => {
    e.preventDefault()
    setState({ busy: true, sent: false, error: null })
    try {
      await api.post('/auth/password-reset/request', { email: email.trim() })
      setState({ busy: false, sent: true, error: null })
    } catch (error) {
      setState({ busy: false, sent: false, error })
    }
  }
  return (
    <AuthLayout subtitle="Reset your password">
      <form onSubmit={submit} className={box} noValidate>
        {state.sent && <Alert tone="green">If an account exists for that address, a reset link is on its way. It works once and expires in an hour.</Alert>}
        {state.error && <Alert>{state.error.message}</Alert>}
        <Field label="Work email" required>
          <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" required placeholder="you@company.com" />
        </Field>
        <Button type="submit" loading={state.busy} className="w-full" disabled={!email.trim()}>Send reset link</Button>
        <p className="text-center text-sm"><Link className="text-brand-700 hover:underline" to="/login">Back to sign in</Link></p>
      </form>
    </AuthLayout>
  )
}

export function ResetPasswordPage() {
  const [params] = useSearchParams()
  const company = params.get('company') || ''
  const token = params.get('token') || ''
  const [f, setF] = useState({ password: '', confirm: '' })
  const [state, setState] = useState({ busy: false, done: false, error: null })
  const mismatch = f.confirm && f.confirm !== f.password
  const fe = fieldErrors(state.error)
  const submit = async (e) => {
    e.preventDefault()
    if (mismatch) return
    setState({ busy: true, done: false, error: null })
    try {
      await api.post('/auth/password-reset/confirm', { company_slug: company, token, new_password: f.password })
      setState({ busy: false, done: true, error: null })
    } catch (error) {
      setState({ busy: false, done: false, error })
    }
  }
  if (!company || !token) {
    return <AuthLayout subtitle="Reset your password"><div className={box}><Alert>This link is incomplete. Request a new one.</Alert><Link className="text-sm text-brand-700 hover:underline" to="/forgot-password">Request a new link</Link></div></AuthLayout>
  }
  if (state.done) {
    return <AuthLayout subtitle="Password updated"><div className={box}><Alert tone="green">Your password was changed and you were signed out everywhere.</Alert><Link className="text-sm font-medium text-brand-700 hover:underline" to="/login">Sign in</Link></div></AuthLayout>
  }
  return (
    <AuthLayout subtitle="Choose a new password">
      <form onSubmit={submit} className={box} noValidate>
        {state.error && !Object.keys(fe).length && <Alert>{state.error.message}</Alert>}
        <Field label="New password" required error={fe.new_password} hint="10+ characters with upper/lower case and a digit">
          <PasswordInput autoComplete="new-password" value={f.password} onChange={(e) => setF((s) => ({ ...s, password: e.target.value }))} required />
        </Field>
        <Field label="Confirm new password" required error={mismatch ? 'Passwords do not match' : undefined}>
          <PasswordInput autoComplete="new-password" value={f.confirm} onChange={(e) => setF((s) => ({ ...s, confirm: e.target.value }))} required />
        </Field>
        <Button type="submit" loading={state.busy} className="w-full" disabled={!f.password || !!mismatch}>Change password</Button>
      </form>
    </AuthLayout>
  )
}

export function VerifyEmailPage() {
  const [params] = useSearchParams()
  const company = params.get('company') || ''
  const token = params.get('token') || ''
  const [state, setState] = useState(company && token ? { status: 'working' } : { status: 'error', message: 'This link is incomplete.' })
  const started = useRef(false)
  useEffect(() => {
    if (!company || !token || started.current) return
    started.current = true // the link is single-use: never submit it twice (React strict mode re-runs effects)
    api.post('/auth/verify-email/confirm', { company_slug: company, token })
      .then(() => setState({ status: 'ok' }))
      .catch((e) => setState({ status: 'error', message: e.message }))
  }, [company, token])
  return (
    <AuthLayout subtitle="Confirm your e-mail address">
      <div className={box}>
        {state.status === 'working' && <p className="text-sm text-slate-600" role="status">Confirming…</p>}
        {state.status === 'ok' && <Alert tone="green">Your e-mail address is confirmed.</Alert>}
        {state.status === 'error' && <Alert>{state.message}</Alert>}
        <Link className="text-sm font-medium text-brand-700 hover:underline" to="/">Continue to WorkSphere</Link>
      </div>
    </AuthLayout>
  )
}
