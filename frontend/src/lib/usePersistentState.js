import { useCallback, useState } from 'react'
import { useAuth } from '../features/auth/AuthContext'
import { local, session, userKey } from './storage'

/**
 * useState that remembers its value for this user.
 *   store: 'local'   (default) survives closing the browser: filters, preferences
 *          'session' lasts for this tab only: which tab of a page is open
 * Returns [value, setValue, reset]. Without working storage it behaves like plain useState.
 */
export function usePersistentState(name, initial, { store = 'local' } = {}) {
  const { user } = useAuth()
  const area = store === 'session' ? session : local
  const key = userKey(store === 'session' ? 'tab' : 'pref', user?.id, name)
  const read = () => ({ key, value: area.get(key, initial) })
  const [box, setBox] = useState(read)
  let current = box
  if (box.key !== key) { current = read(); setBox(current) } // another user / another item: load its value
  const setValue = useCallback((v) => {
    setBox((b) => {
      const value = typeof v === 'function' ? v(b.value) : v
      area.set(b.key, value)
      return { key: b.key, value }
    })
  }, [area])
  const reset = useCallback(() => { area.remove(key); setBox({ key, value: initial }) }, [area, key]) // eslint-disable-line react-hooks/exhaustive-deps
  return [current.value, setValue, reset]
}
