import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../components/ui'
import { useAction } from './hooks'

const setup = (opts) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const spy = vi.spyOn(qc, 'invalidateQueries')
  const wrapper = ({ children }) => <QueryClientProvider client={qc}><ToastProvider>{children}</ToastProvider></QueryClientProvider>
  return { spy, ...renderHook(() => useAction(() => Promise.reject(Object.assign(new Error('refused'), { code: 'conflict' })), opts), { wrapper }) }
}

describe('useAction', () => {
  it('re-reads the affected data after a refused request only when asked to', async () => {
    const a = setup({ invalidate: ['/attendance'], refreshOnError: true })
    await act(async () => { a.result.current.mutate() })
    await waitFor(() => expect(a.result.current.isError).toBe(true))
    expect(a.spy).toHaveBeenCalled()
    const b = setup({ invalidate: ['/attendance'] })
    await act(async () => { b.result.current.mutate() })
    await waitFor(() => expect(b.result.current.isError).toBe(true))
    expect(b.spy).not.toHaveBeenCalled()
  })
})
