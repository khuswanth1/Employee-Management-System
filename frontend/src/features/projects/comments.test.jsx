import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../../components/ui'

const get = vi.fn(), post = vi.fn(), del = vi.fn()
const auth = { user: { id: 2, role: 'employee' }, role: 'employee' }
vi.mock('../auth/AuthContext', () => ({ useAuth: () => auth }))
vi.mock('../../lib/api', async (orig) => ({ ...(await orig()), api: { get: (...a) => get(...a), post: (...a) => post(...a), del: (...a) => del(...a), patch: vi.fn(), put: vi.fn() } }))
import TaskComments from './TaskComments'

const wrap = (ui) => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ToastProvider>{ui}</ToastProvider></QueryClientProvider>)
const list = (items, can = true) => get.mockResolvedValue({ items, can_comment: can })
const c = (id, author_id, author, body) => ({ id, task_id: 5, author_id, author, body, created_at: '2030-01-02T10:00:00Z' })
beforeEach(() => { vi.clearAllMocks(); auth.user = { id: 2, role: 'employee' }; auth.role = 'employee' })

describe('TaskComments', () => {
  it('shows an empty state and posts a trimmed-length comment, disabling Post while blank', async () => {
    list([])
    post.mockResolvedValue(c(1, 2, 'Me', 'Looks good'))
    wrap(<TaskComments taskId={5} isOwner={false} />)
    expect(await screen.findByText('No comments yet')).toBeInTheDocument()
    const btn = screen.getByRole('button', { name: 'Post comment' })
    expect(btn).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Write a comment'), '   ')
    expect(btn).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Write a comment'), 'Looks good')
    await userEvent.click(btn)
    await waitFor(() => expect(post).toHaveBeenCalledWith('/tasks/5/comments', { body: '   Looks good' }))
    await waitFor(() => expect(screen.getByLabelText('Write a comment')).toHaveValue(''))
  })

  it('lets people delete their own comments, the owner delete any, and nobody else delete', async () => {
    list([c(1, 2, 'Me', 'mine'), c(2, 3, 'Zoe', 'hers')])
    del.mockResolvedValue(null)
    wrap(<TaskComments taskId={5} isOwner={false} />)
    expect(await screen.findByText('mine')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Delete comment by Me' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Delete comment by Zoe' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Delete comment by Me' }))
    await waitFor(() => expect(del).toHaveBeenCalledWith('/tasks/5/comments/1'))
  })

  it('the project owner can delete anybody\'s comment', async () => {
    list([c(2, 3, 'Zoe', 'hers')])
    wrap(<TaskComments taskId={5} isOwner />)
    expect(await screen.findByRole('button', { name: 'Delete comment by Zoe' })).toBeInTheDocument()
  })

  it('read-only viewers see the thread but no box to write in; server refusals are shown', async () => {
    list([c(2, 3, 'Zoe', 'hers')], false)
    wrap(<TaskComments taskId={5} isOwner={false} />)
    expect(await screen.findByText('hers')).toBeInTheDocument()
    expect(screen.queryByLabelText('Write a comment')).not.toBeInTheDocument()
  })

  it('shows the server message when posting is refused', async () => {
    list([])
    post.mockRejectedValue(Object.assign(new Error('Only the project owner, its members and the assignee can comment on this task'), { status: 403 }))
    wrap(<TaskComments taskId={5} isOwner={false} />)
    await userEvent.type(await screen.findByLabelText('Write a comment'), 'hello')
    await userEvent.click(screen.getByRole('button', { name: 'Post comment' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/only the project owner/i)
  })
})
