import { useState } from 'react'
import { Link, Navigate, useLocation } from 'react-router-dom'
import { Alert, Button, Field, Input, PasswordInput } from '../../components/ui'
import { useAuth } from './AuthContext'
import { fieldErrors } from '../../lib/api'
import AuthLayout from './AuthLayout'

export default function LoginPage() {
  const { user, login, completeMfa } = useAuth()
  const location = useLocation()
  const [form, setForm] = useState({ email: '', password: '' })
  const [mfaToken, setMfaToken] = useState(null) // set after the password step when two-step verification is on
  const [code, setCode] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  if (user) return <Navigate to={location.state?.from || (user.role === 'platform_admin' ? '/platform' : '/')} replace />

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))
  const run = async (fn) => {
    setBusy(true); setError(null)
    try { await fn() } catch (err) { setError(err) } finally { setBusy(false) }
  }
  const submit = (e) => {
    e.preventDefault()
    run(async () => {
      const res = await login({ email: form.email.trim(), password: form.password })
      if (res?.mfa_required) setMfaToken(res.mfa_token)
    })
  }
  const submitCode = (e) => {
    e.preventDefault()
    run(async () => {
      try { await completeMfa(mfaToken, code.trim()) } catch (err) {
        if (err.status === 401) { setMfaToken(null); setCode(''); throw new Error('That sign-in attempt expired. Enter your password again.') }
        throw err
      }
    })
  }
  const fe = fieldErrors(error)

  if (mfaToken) {
    return (
      <AuthLayout subtitle="Two-step verification">
        <form onSubmit={submitCode} className="space-y-4 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm" noValidate>
          {error && <Alert>{error.message}</Alert>}
          <Field label="Authenticator code" required hint="The 6-digit code from your authenticator app, or one of your recovery codes">
            <Input value={code} onChange={(e) => setCode(e.target.value)} autoComplete="one-time-code" inputMode="text" autoFocus required maxLength={20} placeholder="123456" />
          </Field>
          <Button type="submit" loading={busy} className="w-full" disabled={code.trim().length < 6}>Verify</Button>
          <button type="button" className="w-full text-center text-sm text-slate-600 hover:underline" onClick={() => { setMfaToken(null); setCode(''); setError(null) }}>Use a different account</button>
        </form>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout subtitle="Sign in to your workspace">
      <form onSubmit={submit} className="space-y-4 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm" noValidate>
        {error && !Object.keys(fe).length && <Alert>{error.message}</Alert>}
        <Field label="Email" required error={fe.email}>
          <Input type="email" value={form.email} onChange={set('email')} autoComplete="username" required placeholder="you@company.com" />
        </Field>
        <Field label="Password" required error={fe.password}>
          <PasswordInput value={form.password} onChange={set('password')} autoComplete="current-password" required placeholder="••••••••" />
        </Field>
        <Button type="submit" loading={busy} className="w-full">Sign in</Button>
        <p className="text-center text-sm"><Link className="text-brand-700 hover:underline" to="/forgot-password">Forgot your password?</Link></p>
      </form>
    </AuthLayout>
  )
}
