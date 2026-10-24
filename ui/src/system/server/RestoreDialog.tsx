/**
 * Putting an earlier configuration back (DEV_UI 13.7, decided 16 October).
 *
 * A NEW GENERATION, NOT A REWIND. Grafana: restoring "creates a new
 * version ... so your previous dashboard versions are not affected";
 * Terraform has no undo, only the old configuration applied again. So
 * the history keeps every version, the one restored from included.
 *
 * WHAT IT SHOWS FIRST: which files go back, the ontology's lines (any
 * other file is named, never printed -- it can hold where each source is
 * and how to reach it), and what that does to every role. Roles kept in
 * the role store are not part of any version, and it says so.
 *
 * ONLY A WIDENING ONE WAITS. A restore is often urgent; one that lets
 * anyone read more waits, with a reason, for someone who manages roles.
 * What the server refuses -- a data type the lake cannot follow back, a
 * file that would have to be deleted, nothing to do -- is said in its
 * words, with nothing to press.
 */

import { Button, Dialog, DialogBody, DialogFooter, TextArea } from '@blueprintjs/core'
import {
  ApiError,
  getErrorMessage,
  handleIfSessionExpired,
  previewRestore,
  type RestorePreview,
  restoreGeneration,
} from '@elysium/shell-api/api'
import ErrorState from '@elysium/shell-api/components/ErrorState'
import FileDiff from '@elysium/shell-api/components/FileDiff'
import LoadingState from '@elysium/shell-api/components/LoadingState'
import Notice from '@elysium/shell-api/components/Notice'
import { ConfigImpact } from '@elysium/shell-api/components/RoleImpact'
import { useEffect, useRef, useState } from 'react'

export type RestoreOutcome = { status: 'applied'; generation: number } | { status: 'waiting' }

export default function RestoreDialog({
  generation,
  onClose,
  onDone,
  onSessionExpired,
}: {
  generation: number
  onClose: () => void
  onDone: (outcome: RestoreOutcome) => void
  onSessionExpired: () => void
}) {
  const [preview, setPreview] = useState<RestorePreview | null>(null)
  const [refused, setRefused] = useState<string | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const latestSessionExpired = useRef(onSessionExpired)
  useEffect(() => {
    latestSessionExpired.current = onSessionExpired
  })

  const load = () => {
    setPreview(null)
    setRefused(null)
    setProblem(null)
    previewRestore(generation)
      .then(setPreview)
      .catch((caught: unknown) => {
        if (handleIfSessionExpired(caught, latestSessionExpired.current)) return
        setRefused(getErrorMessage(caught))
      })
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, [])

  const restore = () => {
    if (!preview) return
    setBusy(true)
    setProblem(null)
    restoreGeneration(generation, preview.digest, preview.needs_approval ? reason.trim() : null)
      .then((result) =>
        onDone(
          result.status === 'waiting'
            ? { status: 'waiting' }
            : { status: 'applied', generation: result.to_generation ?? 0 },
        ),
      )
      .catch((caught: unknown) => {
        if (handleIfSessionExpired(caught, latestSessionExpired.current)) return
        // A 409 is a file moved since this was shown: look again rather
        // than act on a picture that is no longer true.
        setProblem(
          caught instanceof ApiError && caught.status === 409
            ? `${caught.message} Press “Look again” to see it as it is now.`
            : getErrorMessage(caught),
        )
      })
      .finally(() => setBusy(false))
  }

  return (
    <Dialog isOpen onClose={onClose} title={`Put generation ${generation} back`} className="config-dialog">
      <DialogBody>
        {preview === null && refused === null && <LoadingState />}
        {refused !== null && <ErrorState>{refused}</ErrorState>}
        {preview && (
          <>
            <p className="config-dialog__lede">
              Its files become the configuration again, as a new generation; every version stays in the history, this
              one included.
            </p>
            {preview.roles_in_store && (
              <Notice state="neutral" title="Roles stay as they are">
                Roles are kept in the role store once anyone edits one on the Roles screen, and no version of the files
                holds them. Change roles there.
              </Notice>
            )}
            <h4 className="config-dialog__heading">What it does to access</h4>
            <ConfigImpact impact={preview.impact} />
            <h4 className="config-dialog__heading">The files that go back</h4>
            {preview.files.map((file) => (
              <FileDiff key={file.name} lines={file.diff} label={`Changes to ${file.name}`} />
            ))}
            {preview.needs_approval && (
              <div className="config-dialog__reason">
                <Notice state="pending" title="This waits for a second person">
                  It lets people read more than they can now, so someone who manages roles, other than you, approves it
                  before it applies.
                </Notice>
                <label htmlFor="restore-reason" className="config-dialog__heading">
                  Why — shown to whoever approves it
                </label>
                <TextArea
                  id="restore-reason"
                  fill
                  value={reason}
                  maxLength={500}
                  onChange={(event) => setReason(event.target.value)}
                />
              </div>
            )}
          </>
        )}
        {problem && <ErrorState>{problem}</ErrorState>}
      </DialogBody>
      <DialogFooter
        actions={
          <>
            {problem && (
              <Button minimal onClick={load}>
                Look again
              </Button>
            )}
            <Button minimal onClick={onClose}>
              Cancel
            </Button>
            {preview && (
              <Button
                intent="primary"
                loading={busy}
                disabled={preview.needs_approval && reason.trim() === ''}
                onClick={restore}
              >
                {preview.needs_approval ? 'Propose for approval' : 'Put it back and reload'}
              </Button>
            )}
          </>
        }
      />
    </Dialog>
  )
}
