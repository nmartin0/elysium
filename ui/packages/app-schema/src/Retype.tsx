/**
 * Changing the data type of a stored field (slice R1 of the retype design,
 * BLOCKING.md, "RETYPE, CHECKED AND SLICED"). Modelled on Remove.tsx: the
 * dialog reads the file's digest when it opens, asks the server to PREVIEW
 * as soon as a new type is chosen, and applying is judged again there.
 *
 * WHAT IT SAYS ABOUT DATA is the server's own list (core/ontology/retype.py),
 * word for word, never this file's: those sentences are pinned by a test that
 * syncs before and after, and a copy here could drift from them.
 *
 * THE PLACES THAT NAME THE FIELD ARE NOTES, NOT BLOCKERS. Changing a type
 * removes nothing, so nothing stops it; each owner is left to check that their
 * rule still means what they wrote. Places naming something this person cannot
 * discover are counted, never described.
 *
 * AFTER IT APPLIES the dialog stays open on one more step: the tables whose
 * silver now differs from the declared type, which the sync refuses until they
 * are rebuilt. "Rebuild now" starts a sync that names them; the server accepts
 * only tables that need it. Closing instead leaves the rebuild for later, and
 * nothing is lost by waiting: the list is derived from the lake each time.
 */

import { Button, Dialog, DialogBody, DialogFooter, HTMLSelect } from '@blueprintjs/core'
import {
  applyRetype,
  getErrorMessage,
  getOntologyDescriptions,
  handleIfSessionExpired,
  previewRetype,
  type RetypePreview,
  startMirrorSync,
} from '@elysium/shell-api/api'
import DataTable from '@elysium/shell-api/components/DataTable'
import ErrorState from '@elysium/shell-api/components/ErrorState'
import FileDiff from '@elysium/shell-api/components/FileDiff'
import LoadingState from '@elysium/shell-api/components/LoadingState'
import Notice from '@elysium/shell-api/components/Notice'
import type { VisibleSchema } from '@elysium/shell-api/types'
import { useEffect, useRef, useState } from 'react'

export type RetypeTarget = { objectType: string; field: string }

// The one 409 that loading again cures: the server's "ontology_schema.yaml has
// changed since you opened it" (_ontology_as_read).
const FILE_CHANGED = /changed since you opened it/

const NONE = ''

export default function RetypeDialog({
  schema,
  target,
  onClose,
  onApplied,
  onSessionExpired,
}: {
  schema: VisibleSchema
  target: RetypeTarget
  onClose: () => void
  onApplied: (generation: number) => void
  onSessionExpired: () => void
}) {
  const type = schema[target.objectType]
  const field = type?.fields?.[target.field]
  const name = `${type?.display_name ?? target.objectType}.${field?.display_name ?? target.field}`
  const current = field?.data_type ?? 'string'
  const [digest, setDigest] = useState<string | null>(null)
  const [dataTypes, setDataTypes] = useState<string[]>([])
  const [choice, setChoice] = useState(NONE)
  const [preview, setPreview] = useState<RetypePreview | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const [stale, setStale] = useState(false)
  const [busy, setBusy] = useState(false)
  // Set once the type has changed: the tables to rebuild, and how the rebuild is going.
  const [applied, setApplied] = useState<{ rebuild: string[] } | null>(null)
  const [rebuild, setRebuild] = useState<'idle' | 'busy' | 'started'>('idle')
  const latestSessionExpired = useRef(onSessionExpired)
  useEffect(() => {
    latestSessionExpired.current = onSessionExpired
  })
  const generation = useRef(0)

  const fail = (caught: unknown) => {
    if (handleIfSessionExpired(caught, latestSessionExpired.current)) return
    setProblem(getErrorMessage(caught))
  }
  const load = () => {
    setPreview(null)
    setProblem(null)
    setStale(false)
    setChoice(NONE)
    getOntologyDescriptions()
      .then((body) => {
        setDigest(body.digest)
        setDataTypes(body.data_types)
      })
      .catch(fail)
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, [])

  const choose = (dataType: string) => {
    setChoice(dataType)
    setPreview(null)
    setProblem(null)
    if (dataType === NONE || digest === null) return
    previewRetype(digest, { object_type: target.objectType, field: target.field, data_type: dataType })
      .then(setPreview)
      .catch((caught: unknown) => {
        setStale(FILE_CHANGED.test(getErrorMessage(caught)))
        fail(caught)
      })
  }

  const apply = () => {
    if (digest === null || choice === NONE) return
    setBusy(true)
    applyRetype(digest, { object_type: target.objectType, field: target.field, data_type: choice })
      .then((result) => {
        generation.current = result.to_generation ?? 0
        setApplied({ rebuild: result.rebuild })
      })
      .catch((caught: unknown) => {
        if (handleIfSessionExpired(caught, latestSessionExpired.current)) return
        setStale(FILE_CHANGED.test(getErrorMessage(caught)))
        setProblem(getErrorMessage(caught))
      })
      .finally(() => setBusy(false))
  }

  const rebuildNow = () => {
    if (!applied) return
    setRebuild('busy')
    setProblem(null)
    startMirrorSync(applied.rebuild)
      .then(() => setRebuild('started'))
      .catch((caught: unknown) => {
        setRebuild('idle')
        fail(caught)
      })
  }

  const done = () => onApplied(generation.current)

  if (applied) {
    return (
      <Dialog isOpen onClose={done} title={`${name} is now ${choice}`} className="config-dialog">
        <DialogBody>
          <p className="config-dialog__lede">
            The type is changed and the deployment has reloaded; nothing stored has been touched yet.
          </p>
          {applied.rebuild.length === 0 ? (
            <Notice>No silver table needs rebuilding: none was built for this field yet.</Notice>
          ) : (
            <>
              <h4 className="config-dialog__heading">Tables to rebuild</h4>
              <p>
                Silver cannot take the new type in place, so the sync refuses{' '}
                {applied.rebuild.length === 1 ? 'this table' : 'these tables'} until{' '}
                {applied.rebuild.length === 1 ? 'it is' : 'they are'} rebuilt from bronze. Rebuilding discards the
                snapshot history of {applied.rebuild.length === 1 ? 'that table' : 'those tables'} and nothing else.
              </p>
              <ul className="add-fields__consequences">
                {applied.rebuild.map((table) => (
                  <li key={table}>
                    <code>{table}</code>
                  </li>
                ))}
              </ul>
              {rebuild === 'started' && (
                <Notice>
                  A sync is running with the rebuild. Its outcome appears in the mirror panel&apos;s last-attempt
                  column.
                </Notice>
              )}
            </>
          )}
          {problem && <ErrorState>{problem}</ErrorState>}
        </DialogBody>
        <DialogFooter
          actions={
            <>
              <Button minimal onClick={done}>
                {applied.rebuild.length > 0 && rebuild !== 'started' ? 'Rebuild later' : 'Done'}
              </Button>
              {applied.rebuild.length > 0 && rebuild !== 'started' && (
                <Button intent="primary" loading={rebuild === 'busy'} onClick={rebuildNow}>
                  Rebuild now
                </Button>
              )}
            </>
          }
        />
      </Dialog>
    )
  }

  return (
    <Dialog isOpen onClose={onClose} title={`Change the type of ${name}`} className="config-dialog">
      <DialogBody>
        {digest === null && problem === null && <LoadingState label="Reading the file…" />}
        {digest !== null && (
          <>
            <p className="config-dialog__lede">
              {name} is <strong>{current}</strong> now. Changing it edits one line of the ontology and reloads the
              deployment. Nothing stored is touched until you rebuild.
            </p>
            <label htmlFor="retype-to">New data type</label>
            <HTMLSelect
              fill
              id="retype-to"
              value={choice}
              onChange={(event) => choose(event.target.value)}
              options={[
                { value: NONE, label: 'Choose a type…' },
                ...dataTypes.filter((each) => each !== current).map((each) => ({ value: each, label: each })),
              ]}
            />
          </>
        )}
        {preview !== null && (
          <>
            <h4 className="config-dialog__heading">What changes, and what stays</h4>
            <ul className="add-fields__consequences">
              {preview.stored_data.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
            {(preview.places.length > 0 || preview.hidden_places > 0) && (
              <>
                <h4 className="config-dialog__heading">Places that name it</h4>
                <p>
                  These do not stop the change, and each owner decides whether their rule still means what they wrote
                  with a {preview.to_type} here.
                  {preview.hidden_places > 0 &&
                    ` ${preview.hidden_places === 1 ? 'One more place names' : `${preview.hidden_places} more places name`} something you cannot see in Schema.`}
                </p>
                {preview.places.length > 0 && (
                  <DataTable className="used-by__table">
                    <tbody>
                      {preview.places.map((row) => (
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
              </>
            )}
            <p className="bp6-text-muted used-by__note">{preview.not_listed}</p>
            {preview.diff.length > 0 && (
              <>
                <h4 className="config-dialog__heading">The line that changes</h4>
                <FileDiff lines={preview.diff} label="Changes to ontology_schema.yaml" />
              </>
            )}
          </>
        )}
        {choice !== NONE && preview === null && problem === null && <LoadingState label="Checking what it changes…" />}
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
            <Button intent="danger" disabled={preview === null || stale} loading={busy} onClick={apply}>
              Change the type and reload
            </Button>
          </>
        }
      />
    </Dialog>
  )
}
