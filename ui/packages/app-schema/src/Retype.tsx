/**
 * Changing the data type of a stored field (slice R1 of the retype design,
 * the removed planning-file item "RETYPE, CHECKED AND SLICED"). Modelled on Remove.tsx: the
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
 * only tables that need it. Closing instead leaves the rebuild for later: the
 * list is derived from the lake each time, so it cannot go stale. Waiting is
 * not free, though (while silver is refused it and gold of the type are not
 * updated, and a value that cannot convert is handled at every sync as
 * on_type_mismatch says), and this says so rather than "nothing is lost".
 *
 * THE REPLY'S LIST IS EVERY TABLE OWED, not only this field's: an earlier change
 * may have left others, and they are labelled as such. If the mirror could not be
 * read the reply says so (`rebuild_unknown`) and the dialog does not guess. After
 * a refused "Rebuild now" the list is fetched again, not retried stale.
 *
 * A PREVIEW REPLY IS SHOWN ONLY FOR THE CHOICE IT WAS ASKED FOR: replies may
 * arrive out of order, and applying is possible only when the one on screen is
 * for the type that is selected.
 */

import { Button, Dialog, DialogBody, DialogFooter, HTMLSelect } from '@blueprintjs/core'
import {
  applyRetype,
  getErrorMessage,
  getOntologyDescriptions,
  getTablesToRebuild,
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
  const [applied, setApplied] = useState<{ tables: string[]; rebuild: string[]; unknown: boolean } | null>(null)
  const [rebuild, setRebuild] = useState<'idle' | 'busy' | 'started'>('idle')
  const latestSessionExpired = useRef(onSessionExpired)
  useEffect(() => {
    latestSessionExpired.current = onSessionExpired
  })
  const generation = useRef(0)
  // Which preview request is the current one: a reply for any other is dropped.
  const previewRequest = useRef(0)

  const fail = (caught: unknown) => {
    if (handleIfSessionExpired(caught, latestSessionExpired.current)) return
    setProblem(getErrorMessage(caught))
  }
  const load = () => {
    previewRequest.current += 1
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
    const mine = ++previewRequest.current
    setChoice(dataType)
    setPreview(null)
    setProblem(null)
    if (dataType === NONE || digest === null) return
    previewRetype(digest, { object_type: target.objectType, field: target.field, data_type: dataType })
      .then((reply) => {
        if (mine === previewRequest.current) setPreview(reply)
      })
      .catch((caught: unknown) => {
        if (mine !== previewRequest.current) return
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
        setApplied({ tables: result.tables, rebuild: result.rebuild, unknown: result.rebuild_unknown })
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
        // THE SET THAT WAS REFUSED MAY BE STALE (a rebuild done by hand, a sync
        // that got there first): ask what is owed now instead of retrying it.
        getTablesToRebuild()
          .then((now) => setApplied((was) => (was ? { ...was, rebuild: now.rebuild, unknown: now.unknown } : was)))
          .catch(() => undefined)
      })
  }

  const done = () => onApplied(generation.current)

  if (applied) {
    return (
      <Dialog isOpen onClose={done} title={`${name} is now ${choice}`} className="config-dialog">
        <DialogBody>
          <p className="config-dialog__lede">
            The type is changed and the deployment has reloaded. The mirror is not rebuilt yet.
          </p>
          {applied.unknown ? (
            <Notice>
              The mirror could not be read, so this cannot tell which tables need a rebuild. Look at the mirror panel,
              or run scripts/repair_catalog.py, and the Schema screen will list them when it can be read again. The
              change itself has been made.
            </Notice>
          ) : applied.rebuild.length === 0 ? (
            <Notice>
              No silver table needs rebuilding: the silver of {name} is not built yet or already has the new type.
            </Notice>
          ) : (
            <>
              <h4 className="config-dialog__heading">Tables whose silver is owed a rebuild</h4>
              <p>
                Silver cannot take a new type in place, so the sync refuses{' '}
                {applied.rebuild.length === 1 ? 'this table' : 'these tables'} until{' '}
                {applied.rebuild.length === 1 ? 'it is' : 'they are'} rebuilt from bronze, and meanwhile does not update
                silver or gold of the types stored in {applied.rebuild.length === 1 ? 'it' : 'them'}. Rebuilding
                discards the snapshot history of {applied.rebuild.length === 1 ? 'that table' : 'those tables'},
                rebuilds gold of every type stored in {applied.rebuild.length === 1 ? 'it' : 'them'} and restarts its
                publication tags. Bronze and the changelog are kept.
              </p>
              <p>
                Waiting is allowed, but every sync until then still reads the source: a value that cannot be read as{' '}
                {choice} is handled as the <code>on_type_mismatch</code> setting says (the table stops, or the row is
                set aside), as the preview said.
              </p>
              <ul className="add-fields__consequences">
                {applied.rebuild.map((table) => (
                  <li key={table}>
                    <code>{table}</code>
                    {applied.tables.includes(table) ? ' (this field)' : ' (owed from an earlier change, not this one)'}
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
              deployment. Silver and gold are not rebuilt until you say so; what the change does to stored data is
              listed below.
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
            <Button
              intent="danger"
              disabled={preview === null || preview.to_type !== choice || stale}
              loading={busy}
              onClick={apply}
            >
              Change the type and reload
            </Button>
          </>
        }
      />
    </Dialog>
  )
}
