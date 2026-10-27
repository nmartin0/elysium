/**
 * Adding a link between two object types (the ontology's shape, designed
 * and agreed 26-27 October): which two types, how many of each, and the
 * columns that join them -- written to ontology_schema.yaml as one link
 * type, whose two directions both come from that one declaration.
 *
 * FOUNDRY'S TWO SHAPES, as the loader adopted them. "Each Customer has
 * many Transactions" is a FOREIGN KEY: one column of the Transactions
 * table holds the customer's id. "Customers and Tags have many of each
 * other" is a JOIN TABLE: a table of pairs of ids, and the two columns
 * that name each side. Nothing else is asked.
 *
 * HOW MANY IS NEVER PRE-CHOSEN, and neither is a column the form cannot
 * recognise: a guess about which column joins two tables is a wiring
 * decision, and a wrong one reads as a link that quietly finds nothing.
 * The one guess made is the exact one -- `<from type>_id` -- and the
 * review says whether the source has the column.
 *
 * WHEN THE SOURCE CANNOT BE ASKED the form says so and takes the names by
 * hand; the review then says nothing was checked.
 */

import { Button, Dialog, DialogBody, DialogFooter, HTMLSelect, InputGroup, TextArea } from '@blueprintjs/core'
import {
  ApiError,
  applyNewLink,
  getErrorMessage,
  getLinkableTypeColumns,
  getLinkableTypes,
  getOntologyDescriptions,
  getSourceColumns,
  getSourceTables,
  handleIfSessionExpired,
  type LinkableType,
  type LinkCardinality,
  type NewLink,
  type NewLinkPreview,
  previewNewLink,
} from '@elysium/shell-api/api'
import ErrorState from '@elysium/shell-api/components/ErrorState'
import FileDiff from '@elysium/shell-api/components/FileDiff'
import LoadingState from '@elysium/shell-api/components/LoadingState'
import Notice from '@elysium/shell-api/components/Notice'
import { ConfigImpact } from '@elysium/shell-api/components/RoleImpact'
import { useEffect, useRef, useState } from 'react'

type Kind = '' | LinkCardinality

/** "SupportTicket" → "support_ticket". */
function snake(typeName: string): string {
  return typeName.replace(/([a-z0-9])([A-Z])/g, '$1_$2').toLowerCase()
}

function plural(word: string): string {
  return word.endsWith('s') ? word : `${word}s`
}

export default function AddLink({
  onClose,
  onApplied,
  onProposed,
  onSessionExpired,
}: {
  onClose: () => void
  onApplied: (generation: number) => void
  /** If the permission code ever says a link widens access, it waits. */
  onProposed: () => void
  onSessionExpired: () => void
}) {
  const [digest, setDigest] = useState<string | null>(null)
  const [types, setTypes] = useState<LinkableType[] | null>(null)
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [kind, setKind] = useState<Kind>('')
  // undefined: not asked yet. null: the source could not say.
  const [toColumns, setToColumns] = useState<string[] | null | undefined>(undefined)
  const [foreignKey, setForeignKey] = useState('')
  const [tables, setTables] = useState<string[] | null | undefined>(undefined)
  const [joinTable, setJoinTable] = useState('')
  const [joinColumns, setJoinColumns] = useState<string[] | null | undefined>(undefined)
  const [joinFrom, setJoinFrom] = useState('')
  const [joinTo, setJoinTo] = useState('')
  const [fromName, setFromName] = useState('')
  const [toName, setToName] = useState('')
  const [linkName, setLinkName] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [description, setDescription] = useState('')
  // A name the person typed is theirs: choosing other types does not rewrite it.
  const typed = useRef({ fromName: false, toName: false, linkName: false })
  const [preview, setPreview] = useState<NewLinkPreview | null>(null)
  const [reason, setReason] = useState('')
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

  useEffect(() => {
    getLinkableTypes().then(setTypes).catch(fail)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const shown = (name: string) => types?.find((candidate) => candidate.name === name)?.display_name ?? name
  const fromType = types?.find((candidate) => candidate.name === from)

  // Names the two ends and the link, until the person writes their own.
  useEffect(() => {
    if (from === '' || to === '' || kind === '') return
    if (!typed.current.fromName) setFromName(kind === 'one_to_one' ? snake(to) : plural(snake(to)))
    if (!typed.current.toName) setToName(kind === 'many_to_many' ? plural(snake(from)) : snake(from))
    if (!typed.current.linkName) setLinkName(`${from}${to}`)
  }, [from, to, kind])

  // The columns of the table that holds the foreign key: the TARGET's.
  useEffect(() => {
    setToColumns(undefined)
    setForeignKey('')
    if (to === '' || kind === '' || kind === 'many_to_many') return
    getLinkableTypeColumns(to)
      .then((found) => {
        setToColumns(found)
        const exact = `${snake(from)}_id`
        if (found?.includes(exact)) setForeignKey(exact)
      })
      .catch((caught: unknown) => {
        setToColumns(null)
        fail(caught)
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [to, from, kind])

  // The join table is one of the first type's source's tables.
  useEffect(() => {
    setTables(undefined)
    setJoinTable('')
    if (kind !== 'many_to_many' || !fromType?.silo) return
    getSourceTables(fromType.silo)
      .then(setTables)
      .catch((caught: unknown) => {
        setTables(null)
        fail(caught)
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, fromType?.silo])

  useEffect(() => {
    setJoinColumns(undefined)
    setJoinFrom('')
    setJoinTo('')
    if (kind !== 'many_to_many' || !fromType?.silo || joinTable.trim() === '') return
    getSourceColumns(fromType.silo, joinTable)
      .then(setJoinColumns)
      .catch((caught: unknown) => {
        setJoinColumns(null)
        fail(caught)
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind, fromType?.silo, joinTable])

  const request = (): NewLink => ({
    name: linkName.trim(),
    ...(displayName.trim() !== '' && { display_name: displayName.trim() }),
    ...(description.trim() !== '' && { description: description.trim() }),
    source: { object_type: from, api_name: fromName.trim() },
    target: { object_type: to, api_name: toName.trim() },
    cardinality: kind as LinkCardinality,
    ...(kind === 'many_to_many'
      ? { join_table: { table: joinTable.trim(), source_column: joinFrom.trim(), target_column: joinTo.trim() } }
      : { foreign_key_column: foreignKey.trim() }),
  })

  const backed =
    kind === 'many_to_many'
      ? joinTable.trim() !== '' && joinFrom.trim() !== '' && joinTo.trim() !== ''
      : kind !== '' && foreignKey.trim() !== ''
  const complete =
    from !== '' &&
    to !== '' &&
    kind !== '' &&
    backed &&
    fromName.trim() !== '' &&
    toName.trim() !== '' &&
    linkName.trim() !== ''

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
    if (digest === null) return
    setBusy(true)
    setProblem(null)
    previewNewLink(digest, request())
      .then(setPreview)
      .catch(failed)
      .finally(() => setBusy(false))
  }

  const apply = () => {
    if (digest === null || !preview) return
    setBusy(true)
    applyNewLink(digest, request(), preview.needs_approval ? reason.trim() : null)
      .then((result) => {
        if (result.status === 'waiting') onProposed()
        else onApplied(result.to_generation ?? 0)
      })
      .catch(failed)
      .finally(() => setBusy(false))
  }

  const ready = digest !== null && types !== null
  const typeOptions = (types ?? []).map((candidate) => (
    <option key={candidate.name} value={candidate.name}>
      {candidate.display_name ?? candidate.name}
    </option>
  ))
  const F = shown(from)
  const T = shown(to)

  const columnPicker = (
    id: string,
    label: string,
    value: string,
    set: (value: string) => void,
    columns: string[] | null | undefined,
    noun = 'column',
  ) => (
    <>
      <label htmlFor={id}>{label}</label>
      {Array.isArray(columns) ? (
        <HTMLSelect fill id={id} value={value} onChange={(event) => set(event.target.value)}>
          <option value="">{`Choose a ${noun}…`}</option>
          {columns.map((column) => (
            <option key={column} value={column}>
              {column}
            </option>
          ))}
        </HTMLSelect>
      ) : (
        <InputGroup
          id={id}
          value={value}
          placeholder={columns === null ? `The source could not list its ${noun}s: type the name` : ''}
          onChange={(event) => set(event.target.value)}
        />
      )}
    </>
  )

  return (
    <Dialog isOpen onClose={onClose} title="Add a link between two object types" className="config-dialog">
      <DialogBody>
        {!ready && problem === null && <LoadingState />}
        {ready && !preview && (
          <>
            <p className="config-dialog__lede">
              A link lets each type reach the other. Choose the two types, how many of each, and the columns that join
              them.
            </p>
            <fieldset className="add-fields__field">
              <legend>What it joins</legend>
              <label htmlFor="add-link-from">From</label>
              <HTMLSelect fill id="add-link-from" value={from} onChange={(event) => setFrom(event.target.value)}>
                <option value="">Choose a type…</option>
                {typeOptions}
              </HTMLSelect>
              <label htmlFor="add-link-to">To</label>
              <HTMLSelect fill id="add-link-to" value={to} onChange={(event) => setTo(event.target.value)}>
                <option value="">Choose a type…</option>
                {typeOptions}
              </HTMLSelect>
              <label htmlFor="add-link-kind">How many</label>
              <HTMLSelect
                fill
                id="add-link-kind"
                value={kind}
                disabled={from === '' || to === ''}
                onChange={(event) => setKind(event.target.value as Kind)}
              >
                <option value="">Choose…</option>
                <option value="one_to_many">{`Each ${F || 'From'} has many ${plural(T || 'To')}`}</option>
                <option value="one_to_one">{`Each ${F || 'From'} has one ${T || 'To'}`}</option>
                <option value="many_to_many">{`${F || 'From'} and ${T || 'To'} have many of each other`}</option>
              </HTMLSelect>
            </fieldset>

            {kind !== '' && kind !== 'many_to_many' && (
              <fieldset className="add-fields__field">
                <legend>The column that joins them</legend>
                {columnPicker(
                  'add-link-fk',
                  `Column of the ${T} table holding the ${F} id`,
                  foreignKey,
                  setForeignKey,
                  toColumns,
                )}
              </fieldset>
            )}

            {kind === 'many_to_many' && (
              <fieldset className="add-fields__field">
                <legend>The table of pairs</legend>
                {columnPicker('add-link-table', 'Join table', joinTable, setJoinTable, tables, 'table')}
                {joinTable.trim() !== '' &&
                  columnPicker('add-link-join-from', `Column naming the ${F}`, joinFrom, setJoinFrom, joinColumns)}
                {joinTable.trim() !== '' &&
                  columnPicker('add-link-join-to', `Column naming the ${T}`, joinTo, setJoinTo, joinColumns)}
              </fieldset>
            )}

            {kind !== '' && (
              <fieldset className="add-fields__field">
                <legend>What it is called</legend>
                <label htmlFor="add-link-from-name">{`On ${F}`}</label>
                <InputGroup
                  id="add-link-from-name"
                  value={fromName}
                  onChange={(event) => {
                    typed.current.fromName = true
                    setFromName(event.target.value)
                  }}
                />
                <label htmlFor="add-link-to-name">{`On ${T}`}</label>
                <InputGroup
                  id="add-link-to-name"
                  value={toName}
                  onChange={(event) => {
                    typed.current.toName = true
                    setToName(event.target.value)
                  }}
                />
                <label htmlFor="add-link-name">Link name</label>
                <InputGroup
                  id="add-link-name"
                  value={linkName}
                  onChange={(event) => {
                    typed.current.linkName = true
                    setLinkName(event.target.value)
                  }}
                />
                <label htmlFor="add-link-display">Display name</label>
                <InputGroup
                  id="add-link-display"
                  value={displayName}
                  placeholder="Optional"
                  onChange={(event) => setDisplayName(event.target.value)}
                />
                <label htmlFor="add-link-description">Description</label>
                <InputGroup
                  id="add-link-description"
                  value={description}
                  placeholder="Optional"
                  onChange={(event) => setDescription(event.target.value)}
                />
              </fieldset>
            )}
          </>
        )}
        {preview && (
          <>
            <h4 className="config-dialog__heading">What else this does</h4>
            <ul className="add-fields__consequences">
              <li>
                {preview.problems.length > 0
                  ? preview.problems.join(' ')
                  : preview.checked
                    ? kind === 'many_to_many'
                      ? 'The source has the join table and both columns.'
                      : `The source has the column ${foreignKey}.`
                    : 'The source could not be asked, so its table and columns are not checked.'}
              </li>
              <li>
                {`${F} reaches ${T} as ${fromName.trim()}, and ${T} reaches ${F} as ${toName.trim()}. Both come from this one link.`}
              </li>
              <li>
                Nobody can read either until a grant names it (Admin → Roles). Nobody holds a new field yet, so the
                first grant of each has to come from someone holding manage:escalation.
              </li>
              <li>
                {kind === 'many_to_many'
                  ? `At the next sync the lake reads the table ${joinTable.trim()}.`
                  : 'The lake needs no new table: the link is read through the two types’ own.'}
              </li>
            </ul>
            <h4 className="config-dialog__heading">What it does to access</h4>
            <ConfigImpact impact={preview.impact} />
            <h4 className="config-dialog__heading">The lines of ontology_schema.yaml</h4>
            <FileDiff lines={preview.diff} label="Changes to ontology_schema.yaml" />
            {preview.needs_approval && (
              <div className="config-dialog__reason">
                <Notice state="pending" title="This waits for a second person">
                  People could read more than they can now. Someone who manages roles, other than you, approves it
                  before it applies.
                </Notice>
                <label htmlFor="add-link-reason" className="config-dialog__heading">
                  Why — shown to whoever approves it
                </label>
                <TextArea
                  id="add-link-reason"
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
