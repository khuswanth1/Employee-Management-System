// Safe wrappers around localStorage / sessionStorage.
//  - localStorage   survives closing the browser: UI preferences (filters) and unsent drafts. Never tokens.
//  - sessionStorage dies with the tab: the auth tokens (see api.js) and per-tab view state (e.g. the open tab of a page).
// Storage can be missing or throw (private windows, blocked site data, quota), so every call is guarded and the
// app must work without it. Values are JSON. Keys are namespaced per user: ws.<kind>.<userId>.<name>.
function area(kind) {
  try {
    const s = window[kind]
    s.setItem('__ws_probe', '1')
    s.removeItem('__ws_probe')
    return s
  } catch {
    return null
  }
}

function wrap(kind) {
  return {
    get(key, fallback) {
      try {
        const raw = area(kind)?.getItem(key)
        return raw == null ? fallback : JSON.parse(raw)
      } catch {
        return fallback
      }
    },
    set(key, value) {
      try { area(kind)?.setItem(key, JSON.stringify(value)) } catch { /* quota or blocked: ignore */ }
    },
    remove(key) {
      try { area(kind)?.removeItem(key) } catch { /* ignore */ }
    },
    removeWhere(prefix) {
      try {
        const s = area(kind)
        if (!s) return
        Object.keys(s).filter((k) => k.startsWith(prefix)).forEach((k) => s.removeItem(k))
      } catch { /* ignore */ }
    },
  }
}

export const local = wrap('localStorage')
export const session = wrap('sessionStorage')
export const userKey = (kind, userId, name) => `ws.${kind}.${userId ?? 'anon'}.${name}`
