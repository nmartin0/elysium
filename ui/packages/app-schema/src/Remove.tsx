/**
 * Removing a stored field, a link type or a whole object type (the removal
 * design, agreed 28 October): the last of deprecate, wait, remove. The screen opens already
 * knowing the answer -- it asks the server to PREVIEW as soon as it has
 * the file's digest -- because the useful part is not the button but what
 * stands in front of it: that the name is not yet deprecated, or what
 * still names it.
 *
 * WHAT IT SAYS ABOUT DATA is the server's own list (core/ontology/
 * removal.py), word for word, never this file's: those sentences are
 * pinned by a test that syncs before and after, and a copy here could
 * drift from them. Nothing is deleted from the source; what the lake
 * holds is described layer by layer.
 *
 * THE BLOCKERS ARE WHAT THIS PERSON MAY SEE. Some name things they cannot
 * discover; those are counted, never described, and the dialog says that
 * someone else has to clear them.
 *
 * APPLYING IS JUDGED AGAIN. A 409 carries the blockers as they are now, and
 * the dialog shows them instead of the preview it was holding.
 */

import { Button, Dialog, DialogBody, DialogFooter } from '@blueprintjs/core'
import {
  ApiError,
  applyRemoval,
  getErrorMessage,
  getOntologyDescriptions,
  handleIfSessionExpired,
  previewRemoval,
  type RemovalPreview,
  type RemovalRefusal,
  type RemovalTarget,
  type UsedByRow,
} from '@elysium/shell-api/api'
import DataTable from '@elysium/shell-api/components/DataTable'
import ErrorState from '@elysium/shell-api/components/ErrorState'
import FileDiff from '@elysium/shell-api/components/FileDiff'
import LoadingState from '@elysium/shell-api/components/LoadingState'
import Notice from '@elysium/shell-api/components/Notice'
import { ConfigImpact } from '@elysium/shell-api/components/RoleImpact'
import type { VisibleSchema } from '@elysium/shell-api/types'
import { useEffect, useRef, useState } from 'react'

export type RemoveTarget = { objectType: string; field: string } | { link: string } | { objectType: string }

function targetOf(target: RemoveTarget): RemovalTarget {
  if ('link' in target) return { kind: 'link', link: target.link }
  if ('field' in target) return { kind: 'field', object_type: target.objectType, field: target.field }
  return { kind: 'type', object_type: target.objectType }
}

function nameOf(schema: VisibleSchema, target: RemoveTarget): string {
  if ('link' in target) return `link ${target.link}`
  if (!('field' in target)) return `type ${schema[target.objectType]?.display_name ?? target.objectType}`
  const type = schema[target.objectType]
  return `${type?.display_name ?? target.objectType}.${type?.fields?.[target.field]?.display_name ?? target.field}`
}

function refusalOf(caught: unknown): RemovalRefusal | null {
  if (!(caught instanceof ApiError) || caught.status !== 409) return null
  const body = caught.body as Partial<RemovalRefusal> | null
  return body && Array.isArray(body.blockers) && typeof body.hidden_blockers === 'number'
    ? { deprecated: body.deprecated !== false, blockers: body.blockers, hidden_blockers: body.hidden_blockers }
    : null
}

// The one 409 that loading again cures: the server's "ontology_schema.yaml has
// changed since you opened it" (_ontology_as_read). The other 409s -- a
// widening, a configuration that would not load -- carry no blockers, and
// loading again would show the same; their sentence is what the person needs.
const FILE_CHANGED = /changed since you opened it/

function Blockers({ rows, hidden, notListed }: { rows: UsedByRow[]; hidden: number; notListed: string }) {
  return (
    <>
      <p>
        Something still names it, and each place must be changed by its owner before it can be removed.
        {hidden > 0 &&
          ` ${hidden === 1 ? 'One more place names' : `${hidden} more places name`} something you cannot see in Schema; someone who can must clear ${hidden === 1 ? 'it' : 'them'}.`}
      </p>
      {rows.length > 0 && (
        <DataTable className="used-by__table">
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.kind}|${row.place}|${row.says}`}>
                <td>
                  <strong>{row.place}</strong>
                </td>
                <td>{row.says}</td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      )}
      <p className="bp6-text-muted used-by__note">{notListed}</p>
    </>
  )
}

export default function RemoveDialog({
  schema,
  target,
  onClose,
  onApplied,
  onSessionExpired,
}: {
  schema: VisibleSchema
  target: RemoveTarget
  onClose: () => void
  onApplied: (generation: number) => void
  onSessionExpired: () => void
}) {
  const name = nameOf(schema, target)
  const goes = ['link', 'field'].some((key) => key in target)
    ? 'its lines from the ontology'
    : 'its lines from the ontology and its entry in source_bindings.yaml (if the deployment has one)'
  const [digest, setDigest] = useState<string | null>(null)
  const [preview, setPreview] = useState<RemovalPreview | null>(null)
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
    setPreview(null)
    setProblem(null)
    setStale(false)
    getOntologyDescriptions()
      .then((body) => {
        setDigest(body.digest)
        return previewRemoval(body.digest, targetOf(target))
      })
      .then(setPreview)
      .catch(fail)
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, [])

  const apply = () => {
    if (digest === null) return
    setBusy(true)
    applyRemoval(digest, targetOf(target))
      .then((result) => onApplied(result.to_generation ?? 0))
      .catch((caught: unknown) => {
        if (handleIfSessionExpired(caught, latestSessionExpired.current)) return
        const refusal = refusalOf(caught)
        if (refusal && preview) {
          setPreview({ ...preview, ...refusal, can_remove: false, impact: null })
          setProblem(getErrorMessage(caught))
        } else {
          setStale(caught instanceof ApiError && caught.status === 409 && FILE_CHANGED.test(getErrorMessage(caught)))
          setProblem(getErrorMessage(caught))
        }
      })
      .finally(() => setBusy(false))
  }

  const early =
    preview?.remove_after != null && preview.deprecated && new Date(`${preview.remove_after}T23:59:59`) > new Date()
  const blocked = preview !== null && (preview.blockers.length > 0 || preview.hidden_blockers > 0)

  return (
    <Dialog isOpen onClose={onClose} title={`Remove ${name}`} className="config-dialog">
      <DialogBody>
        {preview === null && problem === null && <LoadingState label="Checking what names it…" />}
        {preview !== null && (
          <>
            {!preview.deprecated && (
              <Notice>
                {name} is not deprecated. Removing is the last of three steps: deprecate it and say why, give people
                time to stop using it, then remove it.
              </Notice>
            )}
            {preview.deprecated && early && (
              <Notice>
                Removal was planned after {preview.remove_after}, which has not come yet. You can still remove it now.
              </Notice>
            )}
            {preview.deprecated && blocked && (
              <Blockers rows={preview.blockers} hidden={preview.hidden_blockers} notListed={preview.not_listed} />
            )}
            {preview.deprecated && !blocked && (
              <>
                <p className="config-dialog__lede">
                  Nothing in the configuration names {name}. Removing it deletes {goes} and changes nothing else;
                  comments in the file stay where they are.
                </p>
                <h4 className="config-dialog__heading">What happens to the data already stored</h4>
                <ul className="add-fields__consequences">
                  {preview.stored_data.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
                <p className="bp6-text-muted used-by__note">{preview.not_listed}</p>
                {preview.impact && (
                  <>
                    <h4 className="config-dialog__heading">What it does to access</h4>
                    <ConfigImpact impact={preview.impact} />
                  </>
                )}
              </>
            )}
            {preview.diff.length > 0 && (
              <>
                <h4 className="config-dialog__heading">The lines that go</h4>
                <FileDiff lines={preview.diff} label="Changes to ontology_schema.yaml" />
              </>
            )}
          </>
        )}
        {problem && <ErrorState>{problem}</ErrorState>}
      </DialogBody>
      <DialogFooter
        actions={
          <>
            {stale && (
              <Button minimal onClick={load}>
                Load the file again
              </Button>
            )}
            <Button minimal onClick={onClose}>
              Cancel
            </Button>
            <Button
              intent="danger"
              disabled={preview === null || !preview.can_remove || stale}
              loading={busy}
              onClick={apply}
            >
              Remove it and reload
            </Button>
          </>
        }
      />
    </Dialog>
  )
}
