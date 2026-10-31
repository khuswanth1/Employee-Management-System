// Single place that talks to the backend. The tenant is never sent from here: the server derives it
// from the session. The session lives in httpOnly cookies the page cannot read; they are tied to this browser, so a
// copied token is useless elsewhere (see README security notes). X-WS-Client doubles as the CSRF check.
const BASE = '/api/v1'
const CLIENT = { 'X-WS-Client': 'web' }

export class ApiError extends Error {
  constructor(status, code, message, details) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

// "ws_session" is a non-secret marker cookie set next to the httpOnly ones: it only says a session may exist,
// so the app does not call the API (and log a 401) on the login page.
function markerPresent() {
  return typeof document !== 'undefined' && /(?:^|;\s*)ws_session=1/.test(document.cookie)
}
export const session = {
  exists: markerPresent,
  clear() { document.cookie = 'ws_session=; Max-Age=0; path=/' }, // fallback; the server's logout clears the real cookies
}

let refreshing = null
async function refreshTokens() {
  if (!markerPresent()) return false
  refreshing ??= fetch(`${BASE}/auth/refresh`, { method: 'POST', headers: CLIENT })
    .then((r) => r.ok).catch(() => false).finally(() => { refreshing = null })
  return refreshing
}

export function buildQuery(params) {
  const q = new URLSearchParams()
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') q.set(k, v)
  })
  const s = q.toString()
  return s ? `?${s}` : ''
}

async function parse(res) {
  const type = res.headers.get('content-type') || ''
  if (res.status === 204) return null
  if (type.includes('application/json')) return res.json()
  return res.text()
}

export async function request(path, { method = 'GET', body, params, form, retry = true } = {}) {
  const headers = { ...CLIENT }
  let payload
  if (form) payload = form
  else if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body) }
  let res
  try {
    res = await fetch(`${BASE}${path}${buildQuery(params)}`, { method, headers, body: payload })
  } catch {
    throw new ApiError(0, 'network_error', 'Cannot reach the server. Check your connection and try again.')
  }
  if (res.status === 401) {
    if (retry && markerPresent() && path !== '/auth/login' && path !== '/auth/platform/login' && path !== '/auth/refresh' && path !== '/auth/mfa/verify') {
      if (await refreshTokens()) return request(path, { method, body, params, form, retry: false })
    }
    if (path !== '/auth/login' && path !== '/auth/platform/login') {
      session.clear()
      window.dispatchEvent(new Event('ws:logout'))
    }
  }
  const data = await parse(res)
  if (!res.ok) {
    const e = data?.error
    throw new ApiError(res.status, e?.code || 'error', e?.message || `Request failed (${res.status})`, e?.details)
  }
  return data
}

export const api = {
  get: (p, params) => request(p, { params }),
  post: (p, body) => request(p, { method: 'POST', body }),
  put: (p, body) => request(p, { method: 'PUT', body }),
  patch: (p, body) => request(p, { method: 'PATCH', body }),
  del: (p) => request(p, { method: 'DELETE' }),
  upload: (p, file, fields = {}) => {
    const form = new FormData()
    form.append('file', file)
    Object.entries(fields).forEach(([k, v]) => form.append(k, v))
    return request(p, { method: 'POST', form })
  },
}

// Authenticated file download (the session cookie is sent automatically).
/** Multipart upload with progress and cancellation (fetch cannot report upload progress). Rejects with ApiError, or with name "AbortError" when cancelled. */
export function uploadWithProgress(path, file, fields = {}, { onProgress, signal } = {}) {
  const attempt = (retry) => new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    const form = new FormData()
    form.append('file', file)
    Object.entries(fields).forEach(([k, v]) => v !== undefined && v !== null && form.append(k, v))
    xhr.open('POST', `${BASE}${path}`)
    Object.entries(CLIENT).forEach(([k, v]) => xhr.setRequestHeader(k, v))
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(Math.round((e.loaded / e.total) * 100))
    xhr.onerror = () => reject(new ApiError(0, 'network_error', 'Upload failed: cannot reach the server. Check your connection and try again.'))
    xhr.ontimeout = xhr.onerror
    xhr.onabort = () => reject(Object.assign(new Error('Upload cancelled'), { name: 'AbortError' }))
    xhr.onload = async () => {
      if (xhr.status === 401 && retry && markerPresent() && (await refreshTokens())) { attempt(false).then(resolve, reject); return }
      let data = null
      try { data = xhr.responseText ? JSON.parse(xhr.responseText) : null } catch { /* not JSON */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data)
      else reject(new ApiError(xhr.status, data?.error?.code || 'error', data?.error?.message || `Upload failed (${xhr.status})`, data?.error?.details))
    }
    if (signal) {
      if (signal.aborted) { xhr.abort(); return }
      signal.addEventListener('abort', () => xhr.abort(), { once: true })
    }
    xhr.send(form)
  })
  return attempt(true)
}

export async function download(path, filename, params) {
  const res = await fetch(`${BASE}${path}${buildQuery(params)}`, { headers: CLIENT })
  if (!res.ok) throw new ApiError(res.status, 'download_failed', 'Download failed')
  const url = URL.createObjectURL(await res.blob())
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

/** Authenticated image/file fetch returning an object URL (img tags cannot add headers). */
export async function fetchBlobUrl(path) {
  const res = await fetch(`${BASE}${path}`, { headers: CLIENT })
  if (!res.ok) throw new ApiError(res.status, 'fetch_failed', 'Could not load image')
  return URL.createObjectURL(await res.blob())
}

export function wsUrl(path) {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}${BASE}${path}`
}

export function fieldErrors(err) {
  const out = {}
  if (err?.code === 'validation_error' && Array.isArray(err.details)) {
    err.details.forEach((d) => { out[d.field] = d.message.replace(/^Value error, /, '') })
  }
  return out
}

