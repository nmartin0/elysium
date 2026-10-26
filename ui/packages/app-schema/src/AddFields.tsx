/**
 * Adding fields to a type (the ontology's shape, designed and agreed 26
 * October): a name, a data type, and optionally a description, access
 * labels and the source column when it is not named like the field --
 * written to ontology_schema.yaml (and source_bindings.yaml for the
 * column) as one generation.
 *
 * THE DATA TYPE IS CHOSEN HERE AND NEVER CHANGED HERE. The lake cannot
 * change a column's type in place, so a field's type is a decision made
 * when it is born; the list is the server's, so the form offers what it
 * will accept.
 *
 * REVIEW SAYS WHAT ELSE ADDING A FIELD DOES, not only which lines
 * change: whether the source has the column (asked of the source, where
 * it can say), that nobody can read the field until a grant names it,
 * and that the type's table in the lake is rebuilt at the next sync.
 *
 * THE SECOND PERSON IS THE PERMISSION CODE'S CALL, as for labels. A new
 * field normally widens nothing, so it applies at once; when a grant
 * already names it (a label a role holds) it waits, with a reason.
 */

import { Button, Dialog, DialogBody, DialogFooter, HTMLSelect, InputGroup, TextArea } from '@blueprintjs/core'
import {
  ApiError,
  applyNewFields,
  getErrorMessage,
  getOntologyDescriptions,
  handleIfSessionExpired,
  type NewField,
  type NewFieldsPreview,
  previewNewFields,
} from '@elysium/shell-api/api'
import ErrorState from '@elysium/shell-api/components/ErrorState'
import FileDiff from '@elysium/shell-api/components/FileDiff'
import LoadingState from '@elysium/shell-api/components/LoadingState'
import Notice from '@elysium/shell-api/components/Notice'
import { ConfigImpact } from '@elysium/shell-api/components/RoleImpact'
import { useEffect, useRef, useState } from 'react'

interface Draft {
  name: string
  dataType: string
  description: string
  labels: string
  column: string
}

const BLANK: Draft = { name: '', dataType: 'string', description: '', labels: '', column: '' }
const MOST_AT_ONCE = 8

/** The request for a draft: empty boxes are absent, not empty strings. */
function fieldFrom(objectType: string, draft: Draft): NewField {
  const labels = draft.labels
    .split(',')
    .map((label) => label.trim())
    .filter((label) => label !== '')
  return {
    object_type: objectType,
    name: draft.name.trim(),
    data_type: draft.dataType,
    ...(draft.description.trim() !== '' && { description: draft.description.trim() }),
    ...(labels.length > 0 && { labels }),
    ...(draft.column.trim() !== '' && { column: draft.column.trim() }),
  }
}

export default function AddFields({
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
  /** A grant already names a field, so it waits for a role manager. */
  onProposed: () => void
  onSessionExpired: () => void
}) {
  const [digest, setDigest] = useState<string | null>(null)
  const [dataTypes, setDataTypes] = useState<string[]>([])
  const [drafts, setDrafts] = useState<Draft[]>([BLANK])
  const [preview, setPreview] = useState<NewFieldsPreview | null>(null)
  const [reason, setReason] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const [stale, setStale] = useState(false)
  const [busy, setBusy] = useState(false)
  const latestSessionExpired = useRef(onSessionExpired)
  useEffect(() => {
    latestSessionExpired.current = onSessionExpired
  })

  // A RELOAD AFTER A 409 KEEPS WHAT WAS TYPED: only the digest moves.
  const load = () => {
    getOntologyDescriptions()
      .then((body) => {
        setDigest(body.digest)
        setDataTypes(body.data_types)
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

  const fields = drafts.map((draft) => fieldFrom(objectType, draft))
  const complete = drafts.every((draft) => draft.name.trim() !== '')

  // The form is shown only while there is no preview, so none of these
  // has one to discard.
  const change = (index: number, patch: Partial<Draft>) => {
    setProblem(null)
    setDrafts((current) => current.map((draft, at) => (at === index ? { ...draft, ...patch } : draft)))
  }

  const failed = (caught: unknown) => {
    if (handleIfSessionExpired(caught, latestSessionExpired.current)) return
    const conflict = caught instanceof ApiError && caught.status === 409
    setStale(conflict)
    setPreview(null)
    setProblem(
      conflict
        ? `${caught.message} What you typed is still here; load the file again to apply it to the new version.`
        : getErrorMessage(caught),
    )
  }

  const review = () => {
    // Narrowing for the types: Review is disabled until the file is read,
    // so there is no way to reach this without a digest to test.
    if (digest === null) return
    setBusy(true)
    previewNewFields(digest, fields)
      .then(setPreview)
      .catch(failed)
      .finally(() => setBusy(false))
  }

  const apply = () => {
    if (digest === null || !preview) return
    setBusy(true)
    applyNewFields(digest, fields, preview.needs_approval ? reason.trim() : null)
      .then((result) => {
        if (result.status === 'waiting') onProposed()
        else onApplied(result.to_generation ?? 0)
      })
      .catch(failed)
      .finally(() => setBusy(false))
  }

  return (
    <Dialog isOpen onClose={onClose} title={`Add a field to ${shownAs}`} className="config-dialog">
      <DialogBody>
        {digest === null && problem === null && <LoadingState />}
        {digest !== null && !preview && (
          <>
            <p className="config-dialog__lede">
              Lowercase letters, digits and underscores. The data type cannot be changed afterwards.
            </p>
            {drafts.map((draft, index) => (
              <fieldset key={index} className="add-fields__field">
                <legend>{drafts.length === 1 ? 'New field' : `New field ${index + 1}`}</legend>
                <label htmlFor={`add-field-${index}-name`}>Name</label>
                <InputGroup
                  id={`add-field-${index}-name`}
                  value={draft.name}
                  placeholder="nickname"
                  onChange={(event) => change(index, { name: event.target.value })}
                />
                <label htmlFor={`add-field-${index}-type`}>Data type</label>
                <HTMLSelect
                  fill
                  id={`add-field-${index}-type`}
                  value={draft.dataType}
                  options={dataTypes}
                  onChange={(event) => change(index, { dataType: event.target.value })}
                />
                <label htmlFor={`add-field-${index}-description`}>Description</label>
                <InputGroup
                  id={`add-field-${index}-description`}
                  value={draft.description}
                  placeholder="Optional"
                  onChange={(event) => change(index, { description: event.target.value })}
                />
                <label htmlFor={`add-field-${index}-labels`}>Access labels</label>
                <InputGroup
                  id={`add-field-${index}-labels`}
                  value={draft.labels}
                  placeholder="Optional: pii, financial"
                  onChange={(event) => change(index, { labels: event.target.value })}
                />
                <label htmlFor={`add-field-${index}-column`}>Source column</label>
                <InputGroup
                  id={`add-field-${index}-column`}
                  value={draft.column}
                  placeholder="Optional: when the source names it differently"
                  onChange={(event) => change(index, { column: event.target.value })}
                />
                {drafts.length > 1 && (
                  <Button
                    small
                    minimal
                    icon="cross"
                    onClick={() => setDrafts((current) => current.filter((_, at) => at !== index))}
                  >
                    Remove
                  </Button>
                )}
              </fieldset>
            ))}
            {drafts.length < MOST_AT_ONCE && (
              <Button small minimal icon="add" onClick={() => setDrafts((current) => [...current, BLANK])}>
                Another field
              </Button>
            )}
          </>
        )}
        {preview && (
          <>
            <h4 className="config-dialog__heading">What else this does</h4>
            <ul className="add-fields__consequences">
              {preview.fields.map((field) => (
                <li key={field.field}>
                  <strong>{field.field}</strong> reads the source column <code>{field.column}</code>
                  {field.source_has_column === true && ': the source table has it.'}
                  {field.source_has_column === false &&
                    ': the source table has no such column. Add it there first, or give the name of the column that holds it.'}
                  {field.source_has_column === null && ': the source could not be asked, so this is not checked.'}
                </li>
              ))}
              <li>
                Nobody can read {preview.fields.length === 1 ? 'it' : 'them'} until a grant names{' '}
                {preview.fields.length === 1 ? 'it' : 'each'} (Admin → Roles).
              </li>
              <li>
                At the next sync the lake’s {shownAs} table is rebuilt to include{' '}
                {preview.fields.length === 1 ? 'it' : 'them'}. Nothing is lost; its publication numbers start again and
                the first build records no history of changes.
              </li>
            </ul>
            <h4 className="config-dialog__heading">What it does to access</h4>
            <ConfigImpact impact={preview.impact} />
            <h4 className="config-dialog__heading">The lines of ontology_schema.yaml</h4>
            <FileDiff lines={preview.diff} label="Changes to ontology_schema.yaml" />
            {preview.needs_approval && (
              <div className="config-dialog__reason">
                <Notice state="pending" title="This waits for a second person">
                  A grant already names a field you are adding, so people could read more than they can now. Someone who
                  manages roles, other than you, approves it before it applies.
                </Notice>
                <label htmlFor="add-fields-reason" className="config-dialog__heading">
                  Why — shown to whoever approves it
                </label>
                <TextArea
                  id="add-fields-reason"
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
              <Button disabled={!complete || digest === null || stale} loading={busy} onClick={review}>
                Review
              </Button>
            </>
          )
        }
      />
    </Dialog>
  )
}
