import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './api'
import { useToast } from '../components/ui'

export function useDebounce(value, ms = 300) {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

/** GET with caching. `key` should include every param that changes the result. */
export function useApi(path, params, options = {}) {
  return useQuery({ queryKey: [path, params ?? {}], queryFn: () => api.get(path, params), ...options })
}

/** Mutation that toasts errors and invalidates the given path prefixes on success. */
export function useAction(fn, { invalidate = [], success, onSuccess, refreshOnError = false } = {}) {
  const qc = useQueryClient()
  const toast = useToast()
  const refresh = () => invalidate.forEach((p) => qc.invalidateQueries({ predicate: (q) => typeof q.queryKey[0] === 'string' && q.queryKey[0].startsWith(p) }))
  return useMutation({
    mutationFn: fn,
    onSuccess: (data, vars) => {
      refresh()
      if (success) toast(typeof success === 'function' ? success(data) : success)
      onSuccess?.(data, vars)
    },
    onError: (e) => {
      if (refreshOnError) refresh() // the server may know something the page does not (e.g. a session it closed): show the real state
      if (e.code !== 'validation_error') toast(e.message, 'red')
    },
  })
}
