/**
 * ResetPasswordDialog -- an administrator sets somebody else's password.
 *
 * WHAT HAPPENS IS SAID BEFORE IT HAPPENS. Every session of theirs ends,
 * and they must choose their own password at next login -- patch 302.
 * An administrator resetting a colleague's password should not learn
 * that from the colleague.
 *
 * "SUGGEST ONE" fills a random password. The administrator has to pick
 * something that clears the 15-character policy AND hand it over; a
 * random one does both, and is stronger than one invented on the spot.
 * It is SHOWN, not masked, because the administrator must pass it on.
 *
 * AND THE HANDOVER IS NAMED AFTERWARDS: through a channel only that
 * person sees. The policy protects nothing if the password then goes
 * out in a shared chat.
 *
 * THE SERVER'S REFUSAL IS SHOWN. Only it knows the blocklist -- and the
 * escalation rule: resetting an account whose administrative grants you
 * lack is refused, and the reason says so.
 */
import { Button, Dialog, DialogBody, DialogFooter, FormGroup, InputGroup } from '@blueprintjs/core'
import { getErrorMessage, handleIfSessionExpired, resetUserPassword } from '@elysium/shell-api/api'
import ErrorState from '@elysium/shell-api/components/ErrorState'
import { useState } from 'react'

const MIN_LENGTH = 15
// NO LOOK-ALIKES -- 0/O, 1/l/I -- because somebody may read this aloud
// or copy it by hand.
const ALPHABET = 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789'

/** A random password: 20 characters from a 55-symbol alphabet, about
 *  115 bits, from the browser's cryptographic generator. */
export function suggestPassword(length = 20): string {
  const bytes = new Uint32Array(length)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (value) => ALPHABET[value % ALPHABET.length]).join('')
}

interface ResetPasswordDialogProps {
  username: string | null
  onClose: () => void
  onSessionExpired: () => void
}

export default function ResetPasswordDialog({ username, onClose, onSessionExpired }: ResetPasswordDialogProps) {
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [shown, setShown] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [done, setDone] = useState(false)

  function close() {
    setNext('')
    setConfirm('')
    setShown(false)
    setError(null)
    setDone(false)
    onClose()
  }

  function suggest() {
    const password = suggestPassword()
    setNext(password)
    setConfirm(password)
    setShown(true)
  }

  const ready = next.length >= MIN_LENGTH && confirm === next

  async function submit() {
    if (username === null || !ready) return
    setError(null)
    setSubmitting(true)
    try {
      await resetUserPassword(username, next)
      setDone(true)
    } catch (caught: unknown) {
      if (handleIfSessionExpired(caught, onSessionExpired)) return
      setError(getErrorMessage(caught))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog isOpen={username !== null} onClose={close} title={`Reset ${username ?? ''}'s password`}>
      {done ? (
        <>
          <DialogBody>
            <p>
              Done. Give {username} the new password through a channel only they see -- not a shared chat or ticket.
              They will choose their own when they next log in.
            </p>
          </DialogBody>
          <DialogFooter actions={<Button onClick={close}>Close</Button>} />
        </>
      ) : (
        <>
          <DialogBody>
            <p>
              Every session of {username}'s ends now, and they will have to choose their own password when they next log
              in.
            </p>
            {error !== null && <ErrorState>{error}</ErrorState>}
            <FormGroup label="New password" labelFor="reset-password" helperText={`At least ${MIN_LENGTH} characters.`}>
              <InputGroup
                id="reset-password"
                type={shown ? 'text' : 'password'}
                autoComplete="new-password"
                value={next}
                onChange={(event) => setNext(event.target.value)}
              />
            </FormGroup>
            <FormGroup
              label="New password, again"
              labelFor="reset-password-confirm"
              helperText={confirm.length > 0 && confirm !== next ? 'The two entries do not match.' : undefined}
              intent={confirm.length > 0 && confirm !== next ? 'warning' : 'none'}
            >
              <InputGroup
                id="reset-password-confirm"
                type={shown ? 'text' : 'password'}
                autoComplete="new-password"
                value={confirm}
                onChange={(event) => setConfirm(event.target.value)}
              />
            </FormGroup>
            <Button variant="minimal" onClick={suggest}>
              Suggest one
            </Button>
          </DialogBody>
          <DialogFooter
            actions={
              <>
                <Button onClick={close}>Cancel</Button>
                <Button intent="primary" disabled={!ready} loading={submitting} onClick={() => void submit()}>
                  Reset password
                </Button>
              </>
            }
          />
        </>
      )}
    </Dialog>
  )
}
