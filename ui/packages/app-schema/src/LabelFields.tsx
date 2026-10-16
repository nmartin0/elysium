/**
 * A type's access labels (DEV_UI 13.7, decided 16 October): what each
 * field's values ARE -- pii, financial -- written to ontology_schema.yaml.
 *
 * WHAT A LABEL DOES DEPENDS ON THE DEPLOYMENT, and the dialog says which
 * before anything else. With label enforcement off, a label only marks
 * what a field holds (it is carried to every copy in the lake) and every
 * change applies at once. With it on, labels decide who reads a field.
 *
 * THE SECOND PERSON IS DECIDED BY THE PERMISSION CODE, not by whether a
 * label was added or removed: Review asks the server what the change
 * would do to every role, and when anyone could read more it waits for
 * someone who manages roles -- adding a label can open a field to a role
 * holding that label's grant, so direction alone would be wrong.
 *
 * A REASON FOR A WIDENING, shown to the approver: Purview asks for a
 * justification whenever a label is lowered; here the person it is for
 * reads it.
 */

import { Button, Dialog, DialogBody, DialogFooter, InputGroup, TextArea } from '@blueprintjs/core'
import {
  ApiError,
  applyLabels,
  type DescribedType,
  getErrorMessage,
  getOntologyDescriptions,
  handleIfSessionExpired,
  type LabelChange,
  type LabelPreview,
  type OntologyDescriptions,
  previewLabels,
} from '@elysium/shell-api/api'
import ErrorState from '@elysium/shell-api/components/ErrorState'
import FileDiff from '@elysium/shell-api/components/FileDiff'
import LoadingState from '@elysium/shell-api/components/LoadingState'
import Notice from '@elysium/shell-api/components/Notice'
import { ConfigImpact } from '@elysium/shell-api/components/RoleImpact'
import { useEffect, useRef, useState } from 'react'

/** "pii, financial" as the labels it names; spelling is the server's to judge. */
function parse(text: string): string[] {
  return text
    .split(',')
    .map((label) => label.trim())
    .filter((label) => label !== '')
}

function changesFrom(objectType: string, type: DescribedType, drafts: Record<string, string>): LabelChange[] {
  return Object.entries(type.fields).flatMap(([name, field]) => {
    const now = parse(drafts[name] ?? field.labels.join(', '))
    return now.join(',') === field.labels.join(',') ? [] : [{ object_type: objectType, field: name, labels: now }]
  })
}

export default function LabelFields({
  objectType,
  shownAs,
  onClose,
  onApplied,
  onProposed,
  onSessionExpired,
}: {
  objectType: string
  shownAs: string
  onClose: () => void
  onApplied: (generation: number) => void
  /** It widened access, and now waits for a role manager. */
  onProposed: () => void
  onSessionExpired: () => void
}) {
  const [loaded, setLoaded] = useState<OntologyDescriptions | null>(null)
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [preview, setPreview] = useState<LabelPreview | null>(null)
  const [reason, setReason] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const [stale, setStale] = useState(false)
  const [busy, setBusy] = useState(false)
  const latestSessionExpired = useRef(onSessionExpired)
  useEffect(() => {
    latestSessionExpired.current = onSessionExpired
  })

  // A RELOAD AFTER A 409 KEEPS WHAT WAS TYPED: drafts are only what the
  // reader changed, so they apply to the new file as they were meant.
  const load = () => {
    getOntologyDescriptions()
      .then((body) => {
        setLoaded(body)
        setStale(false)
        setProblem(null)
      })
      .catch((caught: unknown) => {
        if (handleIfSessionExpired(caught, latestSessionExpired.current)) return
        setProblem(getErrorMessage(caught))
      })
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, [])

  const type = loaded?.types[objectType]
  const changes = type ? changesFrom(objectType, type, drafts) : []
  const inUse = loaded
    ? [
        ...new Set(
          Object.values(loaded.types).flatMap((t) => Object.values(t.fields).flatMap((field) => field.labels)),
        ),
      ].sort((a, b) => a.localeCompare(b))
    : []

  const failed = (caught: unknown) => {
    if (handleIfSessionExpired(caught, latestSessionExpired.current)) return
    const conflict = caught instanceof ApiError && caught.status === 409
    setStale(conflict)
    setPreview(null)
    setProblem(
      conflict
        ? `${caught.message} Your changes are still here; load the file again to apply them to it.`
        : getErrorMessage(caught),
    )
  }

  const review = () => {
    if (!loaded) return
    setBusy(true)
    previewLabels(loaded.digest, changes)
      .then(setPreview)
      .catch(failed)
      .finally(() => setBusy(false))
  }

  const apply = () => {
    if (!loaded || !preview) return
    setBusy(true)
    applyLabels(loaded.digest, changes, preview.needs_approval ? reason.trim() : null)
      .then((result) => {
        if (result.status === 'waiting') onProposed()
        else onApplied(result.to_generation ?? 0)
      })
      .catch(failed)
      .finally(() => setBusy(false))
  }

  const enforced = preview?.label_enforcement ?? loaded?.label_enforcement ?? false

  return (
    <Dialog isOpen onClose={onClose} title={`Labels on ${shownAs}`} className="config-dialog">
      <DialogBody>
        {loaded === null && problem === null && <LoadingState />}
        {loaded !== null && !type && <ErrorState>{objectType} is no longer in ontology_schema.yaml.</ErrorState>}
        {type && !preview && (
          <>
            <Notice state="neutral" title={enforced ? 'Labels decide access here' : 'Labels describe, here'}>
              {enforced
                ? 'A field with a label can be read only by roles holding that label. A change that lets anyone read more waits for someone who manages roles to approve it.'
                : 'Label enforcement is off, so labels say what a field holds without changing who can read it. Changes apply at once; the lake’s copies are relabelled at the next sync.'}
            </Notice>
            <p className="config-dialog__lede">
              Lowercase words, separated by commas.
              {inUse.length > 0 && <> In use: {inUse.join(', ')}.</>}
            </p>
            <table className="describe-type__fields">
              <thead>
                <tr>
                  <th scope="col">Field</th>
                  <th scope="col">Labels</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(type.fields).map(([name, field]) => (
                  <tr key={name}>
                    <th scope="row" className="describe-type__field-name">
                      {name}
                    </th>
                    <td>
                      <InputGroup
                        aria-label={`${name} labels`}
                        value={drafts[name] ?? field.labels.join(', ')}
                        placeholder="None"
                        onChange={(event) => {
                          setPreview(null)
                          setProblem(null)
                          setDrafts((current) => ({ ...current, [name]: event.target.value }))
                        }}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
        {preview && (
          <>
            <h4 className="config-dialog__heading">What it does to access</h4>
            <ConfigImpact impact={preview.impact} />
            <h4 className="config-dialog__heading">The lines of ontology_schema.yaml</h4>
            <FileDiff lines={preview.diff} label="Changes to ontology_schema.yaml" />
            {preview.needs_approval && (
              <div className="config-dialog__reason">
                <Notice state="pending" title="This waits for a second person">
                  It lets people read more than they can now, so someone who manages roles, other than you, approves it
                  before it applies.
                </Notice>
                <label htmlFor="labels-reason" className="config-dialog__heading">
                  Why — shown to whoever approves it
                </label>
                <TextArea
                  id="labels-reason"
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
          preview ? (
            <>
              <Button minimal onClick={() => setPreview(null)}>
                Back
              </Button>
              <Button
                intent="primary"
                loading={busy}
                disabled={preview.needs_approval && reason.trim() === ''}
                onClick={apply}
              >
                {preview.needs_approval ? 'Propose for approval' : 'Apply and reload'}
              </Button>
            </>
          ) : (
            <>
              {stale && (
                <Button minimal onClick={load}>
                  Load the file again
                </Button>
              )}
              <Button minimal onClick={onClose}>
                Cancel
              </Button>
              <Button disabled={changes.length === 0 || stale} loading={busy} onClick={review}>
                {changes.length === 0
                  ? 'Review changes'
                  : `Review ${changes.length === 1 ? '1 change' : `${changes.length} changes`}`}
              </Button>
            </>
          )
        }
      />
    </Dialog>
  )
}
