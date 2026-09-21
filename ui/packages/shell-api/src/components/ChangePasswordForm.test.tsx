/**
 * ChangePasswordForm -- the current password, and a new one twice.
 *
 * THE SERVER DECIDES; the form checks only what a person can see for
 * themselves -- length, and that both entries match -- and shows the
 * server's reason when it refuses, since only it knows the blocklist.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>()
  return { ...actual, changeOwnPassword: vi.fn() }
})

import { changeOwnPassword } from '../api'
import ChangePasswordForm from './ChangePasswordForm'

const mocked = vi.mocked(changeOwnPassword)

beforeEach(() => {
  vi.clearAllMocks()
  mocked.mockResolvedValue(undefined)
})

function fill(current: string, next: string, again = next) {
  fireEvent.change(screen.getByLabelText('Current password'), { target: { value: current } })
  fireEvent.change(screen.getByLabelText('New password'), { target: { value: next } })
  fireEvent.change(screen.getByLabelText('New password, again'), { target: { value: again } })
}

describe('before it can be submitted', () => {
  it('waits for all three fields', () => {
    render(<ChangePasswordForm required={false} onChanged={vi.fn()} />)

    expect(screen.getByRole('button', { name: 'Change password' })).toBeDisabled()
  })

  it('says how many more characters are needed', () => {
    render(<ChangePasswordForm required={false} onChanged={vi.fn()} />)
    fill('old-one', 'twelve-chars')

    expect(screen.getByText(/3 more character/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Change password' })).toBeDisabled()
  })

  it('says when the two entries differ', () => {
    render(<ChangePasswordForm required={false} onChanged={vi.fn()} />)
    fill('old-one', 'a-long-enough-passphrase', 'a-long-enough-passphrasE')

    expect(screen.getByText(/do not match/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Change password' })).toBeDisabled()
  })
})

describe('submitting', () => {
  it('sends the current and the new password', async () => {
    const onChanged = vi.fn()
    render(<ChangePasswordForm required={false} onChanged={onChanged} />)
    fill('the-old-one', 'a-long-enough-passphrase')

    fireEvent.click(screen.getByRole('button', { name: 'Change password' }))

    await waitFor(() => expect(onChanged).toHaveBeenCalled())
    expect(mocked).toHaveBeenCalledWith('the-old-one', 'a-long-enough-passphrase')
  })

  it("shows the server's reason, announced", async () => {
    /** ONLY THE SERVER KNOWS THE BLOCKLIST, so its refusal is shown. */
    mocked.mockRejectedValue(new Error('That password is too common to use.'))
    const onChanged = vi.fn()
    render(<ChangePasswordForm required={false} onChanged={onChanged} />)
    fill('the-old-one', 'passwordpassword')

    fireEvent.click(screen.getByRole('button', { name: 'Change password' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/too common/)
    expect(onChanged).not.toHaveBeenCalled()
  })
})

describe('when required', () => {
  it('says why, and offers a way out', () => {
    render(<ChangePasswordForm required onChanged={vi.fn()} onLogout={vi.fn()} />)

    expect(screen.getByText(/An administrator reset your password/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Log out' })).toBeInTheDocument()
  })

  it('is quiet about it otherwise', () => {
    render(<ChangePasswordForm required={false} onChanged={vi.fn()} />)

    expect(screen.queryByText(/An administrator reset/)).toBeNull()
  })
})
