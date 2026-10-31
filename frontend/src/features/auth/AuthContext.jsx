import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, session } from '../../lib/api'
import { local } from '../../lib/storage'

const AuthCtx = createContext(null)
export const useAuth = () => useContext(AuthCtx)

export function AuthProvider({ children }) {
  const qc = useQueryClient()
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    if (!session.exists()) { setUser(null); setLoading(false); return }
    try {
      setUser(await api.get('/auth/session'))
    } catch {
      session.clear()
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    const onLogout = () => { setUser(null); qc.clear() }
    window.addEventListener('ws:logout', onLogout)
    return () => window.removeEventListener('ws:logout', onLogout)
  }, [qc])

  /** Resolves to `{ mfa_required, mfa_token }` when a second step is needed (no session yet), otherwise signs in. */
  const login = useCallback(async (creds) => {
    const res = await api.post('/auth/login', creds)
    if (res?.mfa_required) return res
    qc.clear()
    await load()
    return res
  }, [load, qc])

  const completeMfa = useCallback(async (mfa_token, code) => {
    await api.post('/auth/mfa/verify', { mfa_token, code })
    qc.clear()
    await load()
  }, [load, qc])

  const logout = useCallback(() => {
    if (user) local.removeWhere(`ws.draft.${user.id}.`) // unsent drafts must not outlive an explicit sign-out
    api.post('/auth/logout').catch(() => {}).finally(() => session.clear())
    setUser(null)
    qc.clear()
  }, [qc, user])

  const value = useMemo(() => ({ user, loading, login, completeMfa, logout, refresh: load, role: user?.role }), [user, loading, login, completeMfa, logout, load])
  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>
}
