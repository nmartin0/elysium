/**
 * Adding an object type (the ontology's shape, designed and agreed 26-27
 * October): choose a source and one of its tables, keep the columns you
 * want as fields, say who may see its rows, and review the lines before
 * they are written -- to ontology_schema.yaml (and source_bindings.yaml
 * for where it comes from) as one generation.
 *
 * THE PRECEDENT IS FOUNDRY'S: creating an object type from a dataset maps
 * every column as a property at once, which you then untick, and the
 * object type takes its permissions from where the datasource lives.
 * So every column starts ticked, and "follow the source" is the row rule
 * offered when the source declares one.
 *
 * WHO SEES THE ROWS IS NEVER PRE-CHOSEN when the source declares no rule.
 * A default there would be a decision nobody made, and the safe-looking
 * default (a field rule) needs a field the person has not picked yet. The
 * Review button stays off until one is chosen.
 *
 * WHEN THE SOURCE CANNOT BE ASKED (a folder, an API, a failure) the form
 * says so and takes the names by hand; the review then says nothing was
 * checked. Nothing here is a guess dressed as a fact.
 */

import { Button, Checkbox, Dialog, DialogBody, DialogFooter, HTMLSelect, InputGroup, TextArea } from '@blueprintjs/core'
import {
  ApiError,
  applyNewType,
  getErrorMessage,
  getNewTypeSources,
  getOntologyDescriptions,
  getSourceColumns,
  getSourceTables,
  handleIfSessionExpired,
  type NewType,
  type NewTypePreview,
  type NewTypeSource,
  previewNewType,
} from '@elysium/shell-api/api'
import ErrorState from '@elysium/shell-api/components/ErrorState'
import FileDiff from '@elysium/shell-api/components/FileDiff'
import LoadingState from '@elysium/shell-api/components/LoadingState'
import Notice from '@elysium/shell-api/components/Notice'
import { ConfigImpact } from '@elysium/shell-api/components/RoleImpact'
import { useEffect, useRef, useState } from 'react'

type Rule = '' | 'inherit' | 'unrestricted' | 'field'

/** A column's name as a field name: lowercase, digits and underscores,
 *  starting with a letter. The column keeps its own name in the bindings. */
function fieldNameOf(column: string): string {
  const cleaned = column
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
  return /^[a-z]/.test(cleaned) ? cleaned : `f_${cleaned}`
}

/** A table's name as a type name: "customer_orders" → "CustomerOrders". */
function typeNameOf(table: string): string {
  const name = table
    .split(/[^A-Za-z0-9]+/)
    .filter((part) => part !== '')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join('')
  return /^[A-Z]/.test(name) ? name : ''
}

/** The column that most likely identifies a row: `id`, or the table's own
 *  name with `_id` ("transactions" → transaction_id), before any other
 *  column ending in id -- which in a table of transactions is the
 *  customer they point at. */
function likelyId(columns: string[], table: string): string {
  const own = table.toLowerCase().replace(/[^a-z0-9]+/g, '_')
  const named = [`${own}_id`, `${own.replace(/s$/, '')}_id`, 'id']
  return (
    columns.find((column) => named.includes(column.toLowerCase())) ??
    columns.find((column) => /(^|_)id$/i.test(column)) ??
    columns[0] ??
    ''
  )
}

function ruleSentence(rule: NewTypeSource['rule']): string {
  if (!rule) return ''
  return rule.unrestricted ? 'everyone whose role reads it' : `rows tagged by ${rule.field ?? 'a field'}`
}

export default function AddType({
  onClose,
  onApplied,
  onProposed,
  onSessionExpired,
}: {
  onClose: () => void
  onApplied: (generation: number) => void
  /** Listing it to everyone waits for a role manager. */
  onProposed: () => void
  onSessionExpired: () => void
}) {
  const [digest, setDigest] = useState<string | null>(null)
  const [dataTypes, setDataTypes] = useState<string[]>([])
  const [sources, setSources] = useState<NewTypeSource[] | null>(null)
  const [silo, setSilo] = useState('')
  const [tables, setTables] = useState<string[] | null | undefined>(undefined)
  const [table, setTable] = useState('')
  // undefined: not asked yet. null: the source could not say.
  const [columns, setColumns] = useState<string[] | null | undefined>(undefined)
  const [manual, setManual] = useState('')
  const [picked, setPicked] = useState<Record<string, boolean>>({})
  const [dataTypeOf, setDataTypeOf] = useState<Record<string, string>>({})
  const [idColumn, setIdColumn] = useState('')
  const [idType, setIdType] = useState('string')
  const [titleColumn, setTitleColumn] = useState('')
  const [name, setName] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [description, setDescription] = useState('')
  const [rule, setRule] = useState<Rule>('')
  const [ruleField, setRuleField] = useState('')
  const [listed, setListed] = useState(false)
  const [preview, setPreview] = useState<NewTypePreview | null>(null)
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

  // A RELOAD AFTER A 409 KEEPS WHAT WAS TYPED: only the digest moves.
  const load = () => {
    getOntologyDescriptions()
      .then((body) => {
        setDigest(body.digest)
        setDataTypes(body.data_types)
        setStale(false)
        setProblem(null)
      })
      .catch(fail)
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, [])

  useEffect(() => {
    getNewTypeSources()
      .then((found) => {
        setSources(found)
        if (found.length === 1) setSilo(found[0]?.silo ?? '')
      })
      .catch(fail)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // The source's tables, when it is chosen.
  useEffect(() => {
    setTables(undefined)
    setTable('')
    if (silo === '') return
    getSourceTables(silo)
      .then(setTables)
      .catch((caught: unknown) => {
        setTables(null)
        fail(caught)
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [silo])

  // The table's columns, when it is chosen: all ticked, as Foundry maps them.
  useEffect(() => {
    setColumns(undefined)
    setPicked({})
    setDataTypeOf({})
    setIdColumn('')
    setTitleColumn('')
    if (silo === '' || table === '') return
    setName((current) => (current === '' ? typeNameOf(table) : current))
    getSourceColumns(silo, table)
      .then((found) => {
        setColumns(found)
        if (found) {
          setPicked(Object.fromEntries(found.map((column) => [column, true])))
          setIdColumn(likelyId(found, table))
        }
      })
      .catch((caught: unknown) => {
        setColumns(null)
        fail(caught)
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [silo, table])

  const source = sources?.find((candidate) => candidate.silo === silo)
  const sourceRule = source?.rule ?? null
  const columnNames =
    columns ??
    manual
      .split(/[\n,]/)
      .map((column) => column.trim())
      .filter((column) => column !== '')
  const isPicked = (column: string) => (columns ? picked[column] === true : true)
  const kept = columnNames.filter((column) => column !== idColumn && isPicked(column))

  const request = (): NewType => ({
    name: name.trim(),
    ...(displayName.trim() !== '' && { display_name: displayName.trim() }),
    ...(description.trim() !== '' && { description: description.trim() }),
    silo,
    table: table.trim(),
    id_column: idColumn.trim(),
    ...(fieldNameOf(idColumn) !== idColumn.trim() && { id_field: fieldNameOf(idColumn) }),
    ...(idType !== 'string' && { id_type: idType }),
    fields: kept.map((column) => ({
      name: fieldNameOf(column),
      ...(fieldNameOf(column) !== column && { column }),
      ...((dataTypeOf[column] ?? 'string') !== 'string' && { data_type: dataTypeOf[column] }),
    })),
    ...(titleColumn !== '' && { title_field: fieldNameOf(titleColumn) }),
    security: rule === 'field' ? { field: ruleField } : (rule as 'inherit' | 'unrestricted'),
    ...(listed && { discoverable: true }),
  })

  const complete =
    silo !== '' &&
    table.trim() !== '' &&
    idColumn.trim() !== '' &&
    name.trim() !== '' &&
    kept.length > 0 &&
    (rule === 'inherit' || rule === 'unrestricted' || (rule === 'field' && ruleField !== ''))

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
    previewNewType(digest, request())
      .then(setPreview)
      .catch(failed)
      .finally(() => setBusy(false))
  }

  const apply = () => {
    if (digest === null || !preview) return
    setBusy(true)
    applyNewType(digest, request(), preview.needs_approval ? reason.trim() : null)
      .then((result) => {
        if (result.status === 'waiting') onProposed()
        else onApplied(result.to_generation ?? 0)
      })
      .catch(failed)
      .finally(() => setBusy(false))
  }

  const ready = digest !== null && sources !== null

  return (
    <Dialog isOpen onClose={onClose} title="Add an object type" className="config-dialog">
      <DialogBody>
        {!ready && problem === null && <LoadingState />}
        {ready && !preview && (
          <>
            <p className="config-dialog__lede">
              An object type is one table of one source. Choose them, keep the columns you want as fields, and say who
              may see its rows.
            </p>

            <fieldset className="add-fields__field">
              <legend>Where it comes from</legend>
              <label htmlFor="add-type-source">Source</label>
              <HTMLSelect
                fill
                id="add-type-source"
                value={silo}
                onChange={(event) => {
                  setRule('')
                  setSilo(event.target.value)
                }}
              >
                <option value="">Choose a source…</option>
                {sources.map((candidate) => (
                  <option key={candidate.silo} value={candidate.silo}>
                    {candidate.silo}
                  </option>
                ))}
              </HTMLSelect>
              <label htmlFor="add-type-table">Table</label>
              {Array.isArray(tables) ? (
                <HTMLSelect fill id="add-type-table" value={table} onChange={(event) => setTable(event.target.value)}>
                  <option value="">Choose a table…</option>
                  {tables.map((candidate) => (
                    <option key={candidate} value={candidate}>
                      {candidate}
                    </option>
                  ))}
                </HTMLSelect>
              ) : (
                <InputGroup
                  id="add-type-table"
                  value={table}
                  disabled={silo === ''}
                  placeholder={tables === null ? 'The source could not list its tables: type the name' : ''}
                  onChange={(event) => setTable(event.target.value)}
                />
              )}
            </fieldset>

            {silo !== '' && table.trim() !== '' && columns === null && (
              <fieldset className="add-fields__field">
                <legend>Its columns</legend>
                <Notice state="neutral" className="add-type__wide">
                  The source could not list this table’s columns, so they are typed here and are not checked until the
                  review.
                </Notice>
                <label htmlFor="add-type-id">Id column</label>
                <InputGroup id="add-type-id" value={idColumn} onChange={(event) => setIdColumn(event.target.value)} />
                <label htmlFor="add-type-manual">Other columns to keep, separated by commas</label>
                <TextArea
                  id="add-type-manual"
                  fill
                  value={manual}
                  onChange={(event) => setManual(event.target.value)}
                />
              </fieldset>
            )}

            {Array.isArray(columns) && (
              <fieldset className="add-fields__field">
                <legend>Its fields</legend>
                <label htmlFor="add-type-id">Id column</label>
                <HTMLSelect
                  fill
                  id="add-type-id"
                  value={idColumn}
                  onChange={(event) => setIdColumn(event.target.value)}
                >
                  {columns.map((column) => (
                    <option key={column} value={column}>
                      {column}
                    </option>
                  ))}
                </HTMLSelect>
                <label htmlFor="add-type-id-type">The id is</label>
                <HTMLSelect
                  fill
                  id="add-type-id-type"
                  value={idType}
                  options={[
                    { value: 'string', label: 'Text' },
                    { value: 'integer', label: 'A whole number' },
                  ]}
                  onChange={(event) => setIdType(event.target.value)}
                />
                <p className="config-dialog__lede add-type__wide">Untick any column that should not become a field.</p>
                {columns
                  .filter((column) => column !== idColumn)
                  .map((column) => (
                    <div key={column} className="add-type__column add-type__wide">
                      <Checkbox
                        inline
                        label={column}
                        checked={picked[column] === true}
                        onChange={() => setPicked((current) => ({ ...current, [column]: !current[column] }))}
                      />
                      {picked[column] === true && (
                        <HTMLSelect
                          aria-label={`Data type of ${column}`}
                          value={dataTypeOf[column] ?? 'string'}
                          options={dataTypes}
                          onChange={(event) =>
                            setDataTypeOf((current) => ({ ...current, [column]: event.target.value }))
                          }
                        />
                      )}
                    </div>
                  ))}
              </fieldset>
            )}

            {silo !== '' && table.trim() !== '' && columns !== undefined && (
              <>
                <fieldset className="add-fields__field">
                  <legend>What it is</legend>
                  <label htmlFor="add-type-name">Name</label>
                  <InputGroup
                    id="add-type-name"
                    value={name}
                    placeholder="Ticker"
                    onChange={(event) => setName(event.target.value)}
                  />
                  <label htmlFor="add-type-display">Display name</label>
                  <InputGroup
                    id="add-type-display"
                    value={displayName}
                    placeholder="Optional"
                    onChange={(event) => setDisplayName(event.target.value)}
                  />
                  <label htmlFor="add-type-description">Description</label>
                  <InputGroup
                    id="add-type-description"
                    value={description}
                    placeholder="Optional"
                    onChange={(event) => setDescription(event.target.value)}
                  />
                  <label htmlFor="add-type-title">Title column</label>
                  <HTMLSelect
                    fill
                    id="add-type-title"
                    value={titleColumn}
                    onChange={(event) => setTitleColumn(event.target.value)}
                  >
                    <option value="">None: show the id</option>
                    {[idColumn, ...kept]
                      .filter((column) => column !== '')
                      .map((column) => (
                        <option key={column} value={column}>
                          {column}
                        </option>
                      ))}
                  </HTMLSelect>
                </fieldset>

                <fieldset className="add-fields__field">
                  <legend>Who may see its rows</legend>
                  <label htmlFor="add-type-rule">Rows are seen by</label>
                  <HTMLSelect
                    fill
                    id="add-type-rule"
                    value={rule}
                    onChange={(event) => setRule(event.target.value as Rule)}
                  >
                    <option value="">Choose…</option>
                    {sourceRule && <option value="inherit">{`Follow ${silo}: ${ruleSentence(sourceRule)}`}</option>}
                    <option value="unrestricted">Everyone whose role reads it</option>
                    <option value="field">Only rows tagged by one of its fields</option>
                  </HTMLSelect>
                  {!sourceRule && (
                    <p className="config-dialog__lede add-type__wide">
                      {silo} declares no row rule for its types to follow, so choose one here.
                    </p>
                  )}
                  {rule === 'field' && (
                    <>
                      <label htmlFor="add-type-rule-field">The field</label>
                      <HTMLSelect
                        fill
                        id="add-type-rule-field"
                        value={ruleField}
                        onChange={(event) => setRuleField(event.target.value)}
                      >
                        <option value="">Choose a field…</option>
                        {kept.map((column) => (
                          <option key={column} value={fieldNameOf(column)}>
                            {fieldNameOf(column)}
                          </option>
                        ))}
                      </HTMLSelect>
                    </>
                  )}
                </fieldset>

                <Checkbox
                  label="List this type to everyone by name"
                  checked={listed}
                  onChange={() => setListed((current) => !current)}
                />
                <p className="config-dialog__lede">
                  People who cannot read it will see that it exists, in orange and marked view only: its name, never an
                  id, a count or a value. Off, it is hidden from anyone not granted it. Turning it on waits for a second
                  person.
                </p>
              </>
            )}
          </>
        )}
        {preview && (
          <>
            <h4 className="config-dialog__heading">What else this does</h4>
            <ul className="add-fields__consequences">
              <li>
                {preview.source_has_table === true && `The source has the table ${table}.`}
                {preview.source_has_table === false &&
                  `The source has no table ${table}. Add it there first, or choose another.`}
                {preview.source_has_table === null &&
                  'The source could not be asked, so its table and columns are not checked.'}
                {preview.columns_missing.length > 0 &&
                  ` These columns are not in it: ${preview.columns_missing.join(', ')}.`}
              </li>
              <li>
                {rule === 'inherit' && `Its rows follow ${silo}: ${ruleSentence(sourceRule)}, now and if that changes.`}
                {rule === 'unrestricted' && 'Everyone whose role reads it sees every row.'}
                {rule === 'field' && `A person sees only the rows tagged with their own ${ruleField}.`}
              </li>
              <li>
                Nobody can read {name.trim()} until a role is granted it (Admin → Roles). Nobody holds a new type yet,
                so the first grant has to come from someone holding manage:escalation.
                {listed
                  ? ' Everyone will see that it exists, by name only.'
                  : ' Until then, people who are not granted it will not know it exists.'}
              </li>
              <li>At the next sync the lake gets a new table, {name.trim()}.</li>
            </ul>
            <h4 className="config-dialog__heading">What it does to access</h4>
            <ConfigImpact impact={preview.impact} />
            <h4 className="config-dialog__heading">The lines of ontology_schema.yaml</h4>
            <FileDiff lines={preview.diff} label="Changes to ontology_schema.yaml" />
            {preview.needs_approval && (
              <div className="config-dialog__reason">
                <Notice state="pending" title="This waits for a second person">
                  Listing a type to everyone lets people learn more than they can now. Someone who manages roles, other
                  than you, approves it before it applies.
                </Notice>
                <label htmlFor="add-type-reason" className="config-dialog__heading">
                  Why — shown to whoever approves it
                </label>
                <TextArea
                  id="add-type-reason"
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
