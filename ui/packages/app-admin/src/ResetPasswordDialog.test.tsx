/**
 * An administrator resets somebody else's password.
 *
 * WHAT HAPPENS IS SAID BEFORE IT HAPPENS -- their sessions end, and they
 * must choose their own at next login -- and the handover is named after.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return { ...actual, resetUserPassword: vi.fn() }
})

import { resetUserPassword } from '@elysium/shell-api/api'
import ResetPasswordDialog, { suggestPassword } from './ResetPasswordDialog'

const mocked = vi.mocked(resetUserPassword)

beforeEach(() => {
  vi.clearAllMocks()
  mocked.mockResolvedValue(undefined)
})

function open() {
  return render(<ResetPasswordDialog username="cy" onClose={vi.fn()} onSessionExpired={vi.fn()} />)
}

describe('before resetting', () => {
  it('says what will happen to them', () => {
    open()

    expect(screen.getByText(/Every session of cy's ends now/)).toBeInTheDocument()
    expect(screen.getByText(/choose their own password/)).toBeInTheDocument()
  })

  it('waits for a long enough password, entered twice alike', () => {
    open()
    fireEvent.change(screen.getByLabelText('New password'), { target: { value: 'long-enough-password' } })
    fireEvent.change(screen.getByLabelText('New password, again'), { target: { value: 'long-enough-passwordX' } })

    expect(screen.getByText(/do not match/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reset password' })).toBeDisabled()
  })
})

describe('suggesting one', () => {
  it('fills both fields, and SHOWS it -- it has to be handed over', () => {
    open()

    fireEvent.click(screen.getByRole('button', { name: 'Suggest one' }))

    const field = screen.getByLabelText('New password') as HTMLInputElement
    expect(field.type).toBe('text')
    expect(field.value.length).toBeGreaterThanOrEqual(15)
    expect((screen.getByLabelText('New password, again') as HTMLInputElement).value).toBe(field.value)
    expect(screen.getByRole('button', { name: 'Reset password' })).toBeEnabled()
  })

  it('is long, and free of look-alikes', () => {
    /** SOMEBODY MAY READ IT ALOUD: no 0/O, no 1/l/I. */
    for (let i = 0; i < 50; i += 1) {
      const password = suggestPassword()
      expect(password).toHaveLength(20)
      expect(password).not.toMatch(/[0O1lI]/)
    }
  })

  it('differs each time', () => {
    expect(new Set(Array.from({ length: 20 }, () => suggestPassword())).size).toBe(20)
  })
})

describe('resetting', () => {
  it('sends the password, then names the handover', async () => {
    open()
    fireEvent.click(screen.getByRole('button', { name: 'Suggest one' }))
    const chosen = (screen.getByLabelText('New password') as HTMLInputElement).value

    fireEvent.click(screen.getByRole('button', { name: 'Reset password' }))

    expect(await screen.findByText(/through a channel only they see/)).toBeInTheDocument()
    expect(mocked).toHaveBeenCalledWith('cy', chosen)
  })

  it("shows the server's refusal -- the escalation rule among them", async () => {
    mocked.mockRejectedValue(new Error("The 'debug' role carries manage:roles, which you do not hold"))
    open()
    fireEvent.click(screen.getByRole('button', { name: 'Suggest one' }))

    fireEvent.click(screen.getByRole('button', { name: 'Reset password' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/do not hold/)
    await waitFor(() => expect(screen.queryByText(/through a channel/)).toBeNull())
  })
})
