import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

// Partial mock via importOriginal, not a hand-duplicated module shape
// -- see App.test.tsx's own header comment for the full reasoning.
// login() never throws through handleIfSessionExpired's own logic
// (there's no session yet at login time), so this file never needed
// it mocked even before this -- converted to the same, consistent
// pattern as every other test file mocking this module regardless.
vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>()
  return {
    ...actual,
    login: vi.fn(),
  }
})

import { login } from '../api'
import LoginForm from './LoginForm'

// vi.mocked(), not the plain imported `login` -- vi.mock() replaces
// the real module at runtime, but the IMPORTED binding still carries
// api.ts's own real function type (a plain async function), not a
// Mock -- vi.mocked() is Vitest's own, documented way to get back a
// properly-typed mock reference (mockResolvedValue, mockRejectedValue,
// ...) while still checked against the real function's own parameter
// and return types.
const mockedLogin = vi.mocked(login)

beforeEach(() => {
  vi.clearAllMocks()
})

function fillAndSubmit(username: string, password: string) {
  fireEvent.change(screen.getByLabelText('Username'), { target: { value: username } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: password } })
  fireEvent.click(screen.getByRole('button', { name: /log in/i }))
}

describe('LoginForm -- rendering', () => {
  it('renders username and password inputs and a submit button', () => {
    render(<LoginForm onSuccess={vi.fn()} />)
    expect(screen.getByLabelText('Username')).toBeInTheDocument()
    expect(screen.getByLabelText('Password')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Log in' })).toBeInTheDocument()
  })

  it('the password input has type="password", so it is genuinely masked', () => {
    render(<LoginForm onSuccess={vi.fn()} />)
    expect(screen.getByLabelText('Password')).toHaveAttribute('type', 'password')
  })

  it('shows no error message on first render', () => {
    const { container } = render(<LoginForm onSuccess={vi.fn()} />)
    expect(container.querySelector('.error')).not.toBeInTheDocument()
  })
})

describe('LoginForm -- submitting', () => {
  it('calls login() with exactly what was typed into each field', async () => {
    mockedLogin.mockResolvedValue(undefined)
    render(<LoginForm onSuccess={vi.fn()} />)

    fillAndSubmit('alice', 'correct-pw')

    await waitFor(() => expect(mockedLogin).toHaveBeenCalledWith('alice', 'correct-pw'))
  })

  it('calls onSuccess() after a successful login', async () => {
    mockedLogin.mockResolvedValue(undefined)
    const onSuccess = vi.fn()
    render(<LoginForm onSuccess={onSuccess} />)

    fillAndSubmit('alice', 'correct-pw')

    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1))
  })

  it('shows "Logging in…" and disables the button while the request is in flight', async () => {
    // A promise that never resolves during this test -- lets us
    // observe the genuine, real in-flight state, not just infer it.
    let resolveLogin: () => void
    mockedLogin.mockReturnValue(
      new Promise((resolve) => {
        resolveLogin = resolve
      }),
    )
    render(<LoginForm onSuccess={vi.fn()} />)

    fillAndSubmit('alice', 'correct-pw')

    await waitFor(() => expect(screen.getByRole('button', { name: 'Logging in…' })).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Logging in…' })).toBeDisabled()

    // Resolve and let the resulting state update (setSubmitting(false))
    // actually flush before the test ends -- otherwise React warns
    // that an update happened outside act(), since the test function
    // would otherwise return while that update was still pending.
    resolveLogin!()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Log in' })).toBeInTheDocument())
  })
})

describe('LoginForm -- failure handling', () => {
  it("shows the backend's own error message exactly, not reinterpreted", async () => {
    mockedLogin.mockRejectedValue(new Error('Invalid username or password'))
    render(<LoginForm onSuccess={vi.fn()} />)

    fillAndSubmit('alice', 'wrong-pw')

    await waitFor(() => expect(screen.getByText('Invalid username or password')).toBeInTheDocument())
  })

  it('does NOT call onSuccess() when login fails', async () => {
    mockedLogin.mockRejectedValue(new Error('Invalid username or password'))
    const onSuccess = vi.fn()
    render(<LoginForm onSuccess={onSuccess} />)

    fillAndSubmit('alice', 'wrong-pw')

    await waitFor(() => expect(screen.getByText('Invalid username or password')).toBeInTheDocument())
    expect(onSuccess).not.toHaveBeenCalled()
  })

  it('re-enables the button and clears "Logging in…" after a failure', async () => {
    mockedLogin.mockRejectedValue(new Error('Invalid username or password'))
    render(<LoginForm onSuccess={vi.fn()} />)

    fillAndSubmit('alice', 'wrong-pw')

    await waitFor(() => expect(screen.getByRole('button', { name: 'Log in' })).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Log in' })).not.toBeDisabled()
  })

  it('clears a previous error on a new submit attempt, even before the new result comes back', async () => {
    mockedLogin.mockRejectedValueOnce(new Error('Invalid username or password'))
    render(<LoginForm onSuccess={vi.fn()} />)

    fillAndSubmit('alice', 'wrong-pw')
    await waitFor(() => expect(screen.getByText('Invalid username or password')).toBeInTheDocument())

    // Second attempt -- a real promise that never resolves during this
    // test, so we can observe the CLEARED error state before any new
    // result exists at all.
    mockedLogin.mockReturnValue(new Promise(() => {}))
    fillAndSubmit('alice', 'correct-pw-this-time')

    await waitFor(() => expect(screen.queryByText('Invalid username or password')).not.toBeInTheDocument())
  })
})
