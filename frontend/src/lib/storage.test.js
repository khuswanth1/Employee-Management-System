import { afterEach, describe, expect, it, vi } from 'vitest'
import { local, session, userKey } from './storage'

afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); sessionStorage.clear() })

describe('storage helpers', () => {
  it('round-trips JSON in localStorage and sessionStorage independently', () => {
    local.set('a', { x: 1 }); session.set('a', 'tab')
    expect(local.get('a')).toEqual({ x: 1 })
    expect(session.get('a')).toBe('tab')
    local.remove('a')
    expect(local.get('a', 'fallback')).toBe('fallback')
    expect(session.get('a')).toBe('tab')
  })
  it('namespaces keys per user and clears a prefix', () => {
    local.set(userKey('draft', 1, 'u'), 'one'); local.set(userKey('draft', 2, 'u'), 'two'); local.set(userKey('pref', 1, 'f'), 'keep')
    local.removeWhere('ws.draft.1.')
    expect(local.get(userKey('draft', 1, 'u'))).toBeUndefined()
    expect(local.get(userKey('draft', 2, 'u'))).toBe('two')
    expect(local.get(userKey('pref', 1, 'f'))).toBe('keep')
  })
  it('survives corrupt data and storage that throws', () => {
    localStorage.setItem('bad', '{not json')
    expect(local.get('bad', 'ok')).toBe('ok')
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota') })
    expect(() => local.set('k', 1)).not.toThrow()
    expect(local.get('k', 'none')).toBe('none')
  })
})
