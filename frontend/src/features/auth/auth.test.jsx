import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const auth = { user: null, login: vi.fn(), completeMfa: vi.fn() }
vi.mock('./AuthContext', () => ({ useAuth: () => auth }))
const post = vi.fn()
vi.mock('../../lib/api', async (orig) => ({ ...(await orig()), api: { post: (...a) => post(...a) } }))

import LoginPage from './LoginPage'
import { ForgotPasswordPage, ResetPasswordPage, VerifyEmailPage } from './RecoveryPages'

beforeEach(() => { vi.clearAllMocks(); auth.user = null })

const at = (path, element, route = '/x') => render(<MemoryRouter initialEntries={[path]}><Routes><Route path={route} element={element} /></Routes></MemoryRouter>)

describe('LoginPage two-step verification', () => {
  it('asks for a code after the password step and finishes with it', async () => {
    auth.login.mockResolvedValue({ mfa_required: true, mfa_token: 'half-way' })
    auth.completeMfa.mockResolvedValue()
    at('/x', <LoginPage />)
    await userEvent.type(screen.getByLabelText(/email/i), 'a@b.co')
    await userEvent.type(screen.getByLabelText(/^password/i), 'Secret-Pass-1')
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }))
    const code = await screen.findByLabelText(/authenticator code/i)
    expect(screen.queryByLabelText(/^password/i)).not.toBeInTheDocument()
    const verify = screen.getByRole('button', { name: /verify/i })
    expect(verify).toBeDisabled() // needs at least 6 characters
    await userEvent.type(code, '123456')
    await userEvent.click(verify)
    expect(auth.completeMfa).toHaveBeenCalledWith('half-way', '123456')
  })

  it('shows the server message for a wrong code and keeps the code step open', async () => {
    auth.login.mockResolvedValue({ mfa_required: true, mfa_token: 't' })
    auth.completeMfa.mockRejectedValue(Object.assign(new Error('Invalid verification code'), { status: 400 }))
    at('/x', <LoginPage />)
    await userEvent.type(screen.getByLabelText(/email/i), 'a@b.co')
    await userEvent.type(screen.getByLabelText(/^password/i), 'Secret-Pass-1')
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }))
    await userEvent.type(await screen.findByLabelText(/authenticator code/i), '000000')
    await userEvent.click(screen.getByRole('button', { name: /verify/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid verification code')
    expect(screen.getByLabelText(/authenticator code/i)).toBeInTheDocument()
  })

  it('goes back to the password step when the half-way token has expired (401)', async () => {
    auth.login.mockResolvedValue({ mfa_required: true, mfa_token: 't' })
    auth.completeMfa.mockRejectedValue(Object.assign(new Error('expired'), { status: 401 }))
    at('/x', <LoginPage />)
    await userEvent.type(screen.getByLabelText(/email/i), 'a@b.co')
    await userEvent.type(screen.getByLabelText(/^password/i), 'Secret-Pass-1')
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }))
    await userEvent.type(await screen.findByLabelText(/authenticator code/i), '123456')
    await userEvent.click(screen.getByRole('button', { name: /verify/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/enter your password again/i)
    expect(screen.getByLabelText(/^password/i)).toBeInTheDocument()
  })

  it('links to password reset', () => {
    at('/x', <LoginPage />)
    expect(screen.getByRole('link', { name: /forgot your password/i })).toHaveAttribute('href', '/forgot-password')
  })
})

describe('password reset pages', () => {
  it('requests a link and shows the same confirmation either way', async () => {
    post.mockResolvedValue({})
    at('/x', <ForgotPasswordPage />)
    await userEvent.type(screen.getByLabelText(/work email/i), ' me@acme.com ')
    await userEvent.click(screen.getByRole('button', { name: /send reset link/i }))
    expect(post).toHaveBeenCalledWith('/auth/password-reset/request', { email: 'me@acme.com' })
    expect(await screen.findByRole('status')).toHaveTextContent(/if an account exists/i)
  })

  it('sends the company and token from the link with the new password', async () => {
    post.mockResolvedValue(null)
    at('/x?company=acme&token=tok123', <ResetPasswordPage />)
    await userEvent.type(screen.getByLabelText(/^new password/i), 'N3w-Strong-Pw-99')
    await userEvent.type(screen.getByLabelText(/confirm new password/i), 'N3w-Strong-Pw-99')
    await userEvent.click(screen.getByRole('button', { name: /change password/i }))
    expect(post).toHaveBeenCalledWith('/auth/password-reset/confirm', { company_slug: 'acme', token: 'tok123', new_password: 'N3w-Strong-Pw-99' })
    expect(await screen.findByText(/signed out everywhere/i)).toBeInTheDocument()
  })

  it('blocks mismatching passwords and reports a bad link', async () => {
    post.mockRejectedValue(Object.assign(new Error('This link is invalid or has expired'), { status: 400 }))
    at('/x?company=acme&token=tok123', <ResetPasswordPage />)
    await userEvent.type(screen.getByLabelText(/^new password/i), 'N3w-Strong-Pw-99')
    await userEvent.type(screen.getByLabelText(/confirm new password/i), 'different')
    expect(screen.getByText(/do not match/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /change password/i })).toBeDisabled()
    await userEvent.clear(screen.getByLabelText(/confirm new password/i))
    await userEvent.type(screen.getByLabelText(/confirm new password/i), 'N3w-Strong-Pw-99')
    await userEvent.click(screen.getByRole('button', { name: /change password/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/invalid or has expired/i)
  })

  it('refuses an incomplete link without calling the server', () => {
    at('/x?token=only', <ResetPasswordPage />)
    expect(screen.getByRole('alert')).toHaveTextContent(/incomplete/i)
    expect(post).not.toHaveBeenCalled()
  })
})

describe('VerifyEmailPage', () => {
  it('confirms once', async () => {
    post.mockResolvedValue(null)
    at('/x?company=acme&token=abc', <VerifyEmailPage />)
    expect(await screen.findByText(/e-mail address is confirmed/i)).toBeInTheDocument()
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1))
    expect(post).toHaveBeenCalledWith('/auth/verify-email/confirm', { company_slug: 'acme', token: 'abc' })
  })
})
