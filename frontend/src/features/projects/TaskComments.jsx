import { useState } from 'react'
import { Alert, Button, Textarea } from '../../components/ui'
import { api } from '../../lib/api'
import { fmtDateTime } from '../../lib/format'
import { useAction, useApi } from '../../lib/hooks'
import { useAuth } from '../auth/AuthContext'

const MAX = 2000

/** Discussion on one task. Everyone who can see the task reads it; the server decides who may write (owner, members, assignee, HR, founders). */
export default function TaskComments({ taskId, isOwner }) {
  const { user, role } = useAuth()
  const [text, setText] = useState('')
  const path = `/tasks/${taskId}/comments`
  const { data, isLoading, error } = useApi(path)
  const post = useAction(() => api.post(path, { body: text }), { invalidate: [path], onSuccess: () => setText('') })
  const remove = useAction((id) => api.del(`${path}/${id}`), { invalidate: [path], success: 'Comment deleted' })
  const items = data?.items || []
  return (
    <section aria-label="Comments" className="mt-4">
      <h3 className="mb-2 text-sm font-medium text-slate-700">Comments{items.length ? ` (${items.length})` : ''}</h3>
      {isLoading ? <p className="text-sm text-slate-500">Loading…</p> : error ? <Alert>{error.message}</Alert> : items.length === 0 ? (
        <p className="text-sm text-slate-500">No comments yet</p>
      ) : (
        <ul className="max-h-64 divide-y divide-slate-100 overflow-y-auto rounded-lg border border-slate-200 text-sm">
          {items.map((c) => (
            <li key={c.id} className="px-3 py-2">
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-slate-900">{c.author}</span>
                <span className="flex items-center gap-2 text-xs text-slate-500">
                  {fmtDateTime(c.created_at)}
                  {(c.author_id === user.id || isOwner || role === 'founder') && (
                    <button type="button" className="text-red-600 hover:underline" aria-label={`Delete comment by ${c.author}`} onClick={() => remove.mutate(c.id)}>Delete</button>
                  )}
                </span>
              </div>
              <p className="mt-1 whitespace-pre-wrap break-words text-slate-700">{c.body}</p>
            </li>
          ))}
        </ul>
      )}
      {data?.can_comment && (
        <div className="mt-3 space-y-2">
          {post.error && <Alert>{post.error.message}</Alert>}
          <Textarea aria-label="Write a comment" rows={2} maxLength={MAX} value={text} onChange={(e) => setText(e.target.value)} placeholder="Write a comment…" />
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-500">{text.length}/{MAX}</span>
            <Button type="button" size="sm" loading={post.isPending} disabled={!text.trim()} onClick={() => post.mutate()}>Post comment</Button>
          </div>
        </div>
      )}
    </section>
  )
}
