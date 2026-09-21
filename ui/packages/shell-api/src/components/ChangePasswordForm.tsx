/**
 * ChangePasswordForm -- choose a new password, giving the current one.
 *
 * REQUIRED AFTER AN ADMINISTRATOR'S RESET. The administrator knows the
 * reset password, so until its owner replaces it the account may do
 * nothing else. The shell shows this form instead of the apps, and says
 * why -- somebody who arrives here without the reason will assume
 * something is broken.
 *
 * WHAT THE POLICY IS, stated beside the field: at least 15 characters,
 * and length rather than symbols. NIST SP 800-63B-4. The server decides;
 * this only saves a round trip for the two things a person can check
 * themselves -- length, and that both entries match.
 *
 * LOGGING OUT IS OFFERED, because a required step with no way out
 * traps somebody who is not ready to choose a password now.
 */
import { Button, FormGroup, InputGroup } from '@blueprintjs/core'
import { useState } from 'react'

import { changeOwnPassword, getErrorMessage } from '../api'
import ErrorState from './ErrorState'

const MIN_LENGTH = 15

interface ChangePasswordFormProps {
  /** After an administrator's reset: explains why, and offers logout. */
  required: boolean
  /** Given how many OTHER sessions the change ended. */
  onChanged: (otherSessionsEnded: number) => void
  onLogout?: () => void
}

export default function ChangePasswordForm({ required, onChanged, onLogout }: ChangePasswordFormProps) {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const tooShort = next.length > 0 && next.length < MIN_LENGTH
  const mismatch = confirm.length > 0 && confirm !== next
  const ready = current !== '' && next.length >= MIN_LENGTH && confirm === next

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!ready) return
    setError(null)
    setSubmitting(true)
    try {
      onChanged(await changeOwnPassword(current, next))
    } catch (caught: unknown) {
      setError(getErrorMessage(caught))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form className="change-password" onSubmit={handleSubmit}>
      {required && (
        <p>
          An administrator reset your password. Choose your own before continuing -- until you do, they know the one you
          have.
        </p>
      )}
      {error !== null && <ErrorState>{error}</ErrorState>}
      <FormGroup label="Current password" labelFor="current-password">
        <InputGroup
          id="current-password"
          type="password"
          autoComplete="current-password"
          value={current}
          onChange={(event) => setCurrent(event.target.value)}
        />
      </FormGroup>
      <FormGroup
        label="New password"
        labelFor="new-password"
        helperText={
          tooShort
            ? `${MIN_LENGTH - next.length} more character(s) needed.`
            : `At least ${MIN_LENGTH} characters. A few words together work well -- length matters more than symbols.`
        }
        intent={tooShort ? 'warning' : 'none'}
      >
        <InputGroup
          id="new-password"
          type="password"
          autoComplete="new-password"
          value={next}
          onChange={(event) => setNext(event.target.value)}
        />
      </FormGroup>
      <FormGroup
        label="New password, again"
        labelFor="confirm-password"
        helperText={mismatch ? 'The two entries do not match.' : undefined}
        intent={mismatch ? 'warning' : 'none'}
      >
        <InputGroup
          id="confirm-password"
          type="password"
          autoComplete="new-password"
          value={confirm}
          onChange={(event) => setConfirm(event.target.value)}
        />
      </FormGroup>
      <div className="change-password__actions">
        <Button type="submit" intent="primary" disabled={!ready} loading={submitting}>
          Change password
        </Button>
        {onLogout !== undefined && (
          <Button variant="minimal" onClick={onLogout}>
            Log out
          </Button>
        )}
      </div>
    </form>
  )
}
