/**
 * Deprecating a type, a field or a link type -- or making it active again
 * (the removal design, agreed 28 October). The step before anything can
 * be removed: a name is marked, with WHY, optionally what replaces it and
 * the day removal is planned; "Used by" says what still names it.
 *
 * ONE FLOW, as everywhere: fill in, review the plain-English
 * consequences and the lines that would be written, apply. Nothing about
 * the data or about who may read it changes, so it applies at once and
 * never waits for a second person.
 *
 * THE DATE IS A NOTE FOR NOW. The dialog says so rather than promising
 * an alert that does not exist yet.
 *
 * A LINK THAT TOOK ITS STATUS FROM A TYPE is not deprecated on its own,
 * and the dialog says which type it follows; deprecating it here gives it
 * a reason of its own.
 */

import { Button, Dialog, DialogBody, DialogFooter, HTMLSelect, InputGroup, TextArea } from '@blueprintjs/core'
import {
  ApiError,
  applyStatus,
  getErrorMessage,
  getOntologyDescriptions,
  handleIfSessionExpired,
  previewStatus,
  type StatusChange,
  type StatusPreview,
  type StatusTarget,
} from '@elysium/shell-api/api'
import ErrorState from '@elysium/shell-api/components/ErrorState'
import FileDiff from '@elysium/shell-api/components/FileDiff'
import LoadingState from '@elysium/shell-api/components/LoadingState'
import { ConfigImpact } from '@elysium/shell-api/components/RoleImpact'
import type { Deprecation, VisibleSchema } from '@elysium/shell-api/types'
import { useEffect, useRef, useState } from 'react'

export type DeprecateTarget = { objectType: string; field?: string } | { link: string }

interface Current {
  /** What the schema says now, which for a link may come from a type. */
  status: string
  deprecation: Deprecation | null
  inheritedFrom: string | null
}

interface Subject {
  /** How the person reads it: "Customer.email", "link CustomerTags". */
  name: string
  current: Current
  /** What may replace it: others of its kind that are not deprecated themselves. */
  candidates: { name: string; label: string }[]
  target: StatusTarget
}

function subjectOf(schema: VisibleSchema, target: DeprecateTarget): Subject | null {
  if ('link' in target) {
    const ends = Object.values(schema).flatMap((type) =>
      Object.values(type.fields ?? {}).filter((field) => field.link_type),
    )
    const mine = ends.find((field) => field.link_type === target.link)
    if (!mine) return null
    const others = new Map<string, string>()
    for (const field of ends) {
      if (field.link_type && field.link_type !== target.link && field.status !== 'deprecated') {
        others.set(field.link_type, field.link_type)
      }
    }
    return {
      name: `link ${target.link}`,
      current: {
        status: mine.status ?? 'active',
        deprecation: mine.deprecation ?? null,
        inheritedFrom: mine.status_inherited_from ?? null,
      },
      candidates: [...others.keys()].sort().map((name) => ({ name, label: name })),
      target: { kind: 'link', link: target.link },
    }
  }
  const type = schema[target.objectType]
  if (!type) return null
  if (target.field === undefined) {
    return {
      name: type.display_name ?? target.objectType,
      current: { status: type.status ?? 'active', deprecation: type.deprecation ?? null, inheritedFrom: null },
      candidates: Object.entries(schema)
        .filter(([name, other]) => name !== target.objectType && other.status !== 'deprecated')
        .map(([name, other]) => ({ name, label: other.display_name ?? name })),
      target: { kind: 'type', object_type: target.objectType },
    }
  }
  const field = type.fields?.[target.field]
  if (!field) return null
  return {
    name: `${type.display_name ?? target.objectType}.${field.display_name ?? target.field}`,
    current: { status: field.status ?? 'active', deprecation: field.deprecation ?? null, inheritedFrom: null },
    candidates: Object.entries(type.fields ?? {})
      .filter(([name, other]) => name !== target.field && other.type !== 'link' && other.status !== 'deprecated')
      .map(([name, other]) => ({ name, label: other.display_name ?? name })),
    target: { kind: 'field', object_type: target.objectType, field: target.field },
  }
}

export default function DeprecateDialog({
  schema,
  target,
  onClose,
  onApplied,
  onSessionExpired,
}: {
  schema: VisibleSchema
  target: DeprecateTarget
  onClose: () => void
  onApplied: (generation: number) => void
  onSessionExpired: () => void
}) {
  const subject = subjectOf(schema, target)
  const was = subject?.current.deprecation
  const alreadyDeprecated = subject?.current.status === 'deprecated' && !subject.current.inheritedFrom
  const [digest, setDigest] = useState<string | null>(null)
  const [reason, setReason] = useState(was?.reason ?? '')
  const [replacement, setReplacement] = useState(was?.replaced_by ?? '')
  const [date, setDate] = useState(was?.remove_after ?? '')
  const [change, setChange] = useState<StatusChange | null>(null)
  const [preview, setPreview] = useState<StatusPreview | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const [stale, setStale] = useState(false)
  const [busy, setBusy] = useState(false)
  const latestSessionExpired = useRef(onSessionExpired)
  useEffect(() => {
    latestSessionExpired.current = onSessionExpired
  })

  const fail = (caught: unknown) => {
    if (handleIfSessionExpired(caught, latestSessionExpired.current)) return
    setProblem(getErrorMessage(caught))
  }
  const load = () => {
    getOntologyDescriptions()
      .then((body) => {
        setDigest(body.digest)
        setStale(false)
        setProblem(null)
      })
      .catch(fail)
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, [])

  if (!subject) return null

  const deprecating = (): StatusChange => ({
    ...subject.target,
    status: 'deprecated',
    reason: reason.trim(),
    ...(replacement !== '' && { replaced_by: replacement }),
    ...(date.trim() !== '' && { remove_after: date.trim() }),
  })
  const restoring = (): StatusChange => ({ ...subject.target, status: 'active' })

  const review = (next: StatusChange) => {
    if (digest === null) return
    setBusy(true)
    setProblem(null)
    previewStatus(digest, next)
      .then((found) => {
        setChange(next)
        setPreview(found)
      })
      .catch(failed)
      .finally(() => setBusy(false))
  }
  const apply = () => {
    if (digest === null || change === null) return
    setBusy(true)
    applyStatus(digest, change)
      .then((result) => onApplied(result.to_generation ?? 0))
      .catch(failed)
      .finally(() => setBusy(false))
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

  const making = change?.status === 'active' ? 'active again' : 'deprecated'
  return (
    <Dialog
      isOpen
      onClose={onClose}
      title={`${alreadyDeprecated ? 'Deprecation of' : 'Deprecate'} ${subject.name}`}
      className="config-dialog"
    >
      <DialogBody>
        {digest === null && problem === null && <LoadingState />}
        {digest !== null && !preview && (
          <>
            <p className="config-dialog__lede">
              {alreadyDeprecated
                ? `${subject.name} is deprecated. Change what is said about it, or make it active again.`
                : 'Deprecating marks it as one to stop using and says why. Nothing is removed, and nobody gains or loses access.'}
            </p>
            {subject.current.inheritedFrom && (
              <p className="bp6-text-muted">
                {`It already reads as deprecated because ${subject.current.inheritedFrom} is. Deprecating it here gives it a reason of its own.`}
              </p>
            )}
            <fieldset className="add-fields__field">
              <legend>Why</legend>
              <label htmlFor="deprecate-reason">Why it is deprecated, for whoever reads it later</label>
              <TextArea
                id="deprecate-reason"
                fill
                value={reason}
                maxLength={300}
                onChange={(event) => setReason(event.target.value)}
              />
              <label htmlFor="deprecate-replacement">What to use instead</label>
              <HTMLSelect
                fill
                id="deprecate-replacement"
                value={replacement}
                onChange={(event) => setReplacement(event.target.value)}
              >
                <option value="">Nothing in particular</option>
                {subject.candidates.map((candidate) => (
                  <option key={candidate.name} value={candidate.name}>
                    {candidate.label}
                  </option>
                ))}
              </HTMLSelect>
              <label htmlFor="deprecate-date">Removal planned after</label>
              <InputGroup
                id="deprecate-date"
                type="date"
                value={date}
                onChange={(event) => setDate(event.target.value)}
              />
              <p className="bp6-text-muted">
                The date is a note for now: nothing happens on it. Removing is a separate step, refused while anything
                still names it.
              </p>
            </fieldset>
          </>
        )}
        {preview && (
          <>
            <h4 className="config-dialog__heading">What this does</h4>
            <ul className="add-fields__consequences">
              <li>
                {change?.status === 'active'
                  ? `${subject.name} stops being marked, and its reason is taken out.`
                  : `${subject.name} shows as deprecated, with your reason, wherever it appears in Schema.`}
              </li>
              <li>Data is not touched, and no grant changes.</li>
              {subject.target.kind === 'type' && <li>Its links read as deprecated too, until they are taken out.</li>}
              {subject.target.kind === 'link' && <li>The types it joins are not changed.</li>}
            </ul>
            <h4 className="config-dialog__heading">What it does to access</h4>
            <ConfigImpact impact={preview.impact} />
            <h4 className="config-dialog__heading">The lines of ontology_schema.yaml</h4>
            <FileDiff lines={preview.diff} label="Changes to ontology_schema.yaml" />
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
              <Button intent="primary" loading={busy} onClick={apply}>
                {`Make it ${making} and reload`}
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
              {alreadyDeprecated && (
                <Button disabled={digest === null || stale} loading={busy} onClick={() => review(restoring())}>
                  Make it active again
                </Button>
              )}
              <Button
                intent={alreadyDeprecated ? undefined : 'primary'}
                disabled={reason.trim() === '' || digest === null || stale}
                loading={busy}
                onClick={() => review(deprecating())}
              >
                {alreadyDeprecated ? 'Review the change' : 'Review'}
              </Button>
            </>
          )
        }
      />
    </Dialog>
  )
}
