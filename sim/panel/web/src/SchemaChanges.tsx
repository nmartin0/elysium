/**
 * SCHEMA CHANGES FROM THE PANEL (BLOCKING.md item 11, the owner's
 * approval of 26 October): change a running world's structure -- a
 * column added, dropped, renamed, retyped or rescaled, a table added,
 * dropped or renamed -- and see what has changed so far.
 *
 * LAID OUT AS A FAULT-INJECTION TOOL LAYS OUT AN EXPERIMENT. Gremlin's:
 * "Select the type of target ... click on the experiment name ... Click
 * Run Experiment", and "view reports of historical experiments". Here:
 * a database and a table, the change, its details, Apply; and the list
 * of what has changed.
 *
 * ONLY WHAT EXISTS CAN BE PICKED: the tables and columns come from the
 * running world (the panel server's /schema, the world's `schema`
 * command), read again after every change. A source's replica is not
 * offered: the change reaches it, as a real one's would.
 *
 * A BREAKING CHANGE ASKS TWICE, as Discard does. Which changes break is
 * the world's word (`operations`, from each change's own class), not
 * this page's: a rescale breaks, though nothing downstream raises,
 * because every value now means something else. None can be undone --
 * the business carries on with the change -- and only discarding the
 * world goes back.
 */
import { useCallback, useEffect, useState } from 'react'
import { Button, FormGroup, HTMLSelect, HTMLTable, InputGroup, NumericInput } from '@blueprintjs/core'
import { addonRequest, getErrorMessage, handleIfSessionExpired } from '@elysium/shell-api/api'
import StatusTag from '@elysium/shell-api/components/StatusTag'

const MODULE = 'simulator'
/** Scheduled changes land on the world's own clock; read again this often. */
const REREAD_MS = 30_000

interface SchemaColumn {
  name: string
  type: string
  nullable: boolean
  primary_key: boolean
}

interface SchemaChange {
  at: string
  operation: string
  detail: string
  breaking: boolean
}

export interface WorldSchema {
  silos: Record<string, { kind: string; tables: Record<string, SchemaColumn[]>; history: SchemaChange[] }>
  /** Each change on offer, and whether the world calls it breaking. */
  operations: Record<string, boolean>
}

const LABELS: Record<string, string> = {
  add_column: 'Add a column',
  drop_column: 'Drop a column',
  rename_column: 'Rename a column',
  change_column_type: "Change a column's type",
  rescale_column: 'Rescale a column',
  add_table: 'Add a table',
  drop_table: 'Drop a table',
  rename_table: 'Rename a table',
}

const TYPES = ['text', 'integer', 'bigint', 'decimal', 'boolean', 'date', 'timestamp']
const NUMERIC = new Set(['integer', 'bigint', 'decimal'])

/** A change named for an existing column picks it; these name a new one. */
const PICKS_A_COLUMN = new Set(['drop_column', 'rename_column', 'change_column_type', 'rescale_column'])

type Act = (path: string, body?: unknown) => void

/** The world's time a change was made at, as the history table holds it. */
function when(at: string): string {
  const parsed = new Date(at.includes('T') ? at : at.replace(' ', 'T') + 'Z')
  return Number.isNaN(parsed.getTime())
    ? at
    : parsed.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

export default function SchemaChanges({
  mayOperate,
  acting,
  act,
  onSessionExpired,
}: {
  mayOperate: boolean
  acting: boolean
  act: Act
  onSessionExpired: () => void
}) {
  const [schema, setSchema] = useState<WorldSchema | null>(null)
  const [error, setError] = useState<string | null>(null)

  const read = useCallback(
    () =>
      addonRequest<WorldSchema>(MODULE, 'schema').then(
        (got) => {
          setSchema(got)
          setError(null)
        },
        (err: unknown) => {
          handleIfSessionExpired(err, onSessionExpired)
          setError(getErrorMessage(err))
        },
      ),
    [onSessionExpired],
  )

  // Again when a change has been answered, and on the world's clock.
  useEffect(() => {
    if (acting) return undefined
    void read()
    const timer = window.setInterval(() => void read(), REREAD_MS)
    return () => window.clearInterval(timer)
  }, [acting, read])

  return (
    <section aria-label="Schema changes">
      <h2 className="simulator-panel__heading">Schema changes</h2>
      {error !== null ? (
        <p role="alert">Could not read its tables: {error}</p>
      ) : schema === null ? (
        <p>Reading its tables…</p>
      ) : (
        <>
          {mayOperate ? <ChangeForm schema={schema} acting={acting} act={act} /> : null}
          <History schema={schema} />
        </>
      )}
    </section>
  )
}

function ChangeForm({ schema, acting, act }: { schema: WorldSchema; acting: boolean; act: Act }) {
  const silos = Object.keys(schema.silos)
  const [silo, setSilo] = useState(silos[0] ?? '')
  const tables = Object.keys(schema.silos[silo]?.tables ?? {})
  const [table, setTable] = useState(tables[0] ?? '')
  const [operation, setOperation] = useState('add_column')
  const [column, setColumn] = useState('')
  const [to, setTo] = useState('')
  const [type, setType] = useState('text')
  const [length, setLength] = useState(64)
  const [precision, setPrecision] = useState(12)
  const [scale, setScale] = useState(2)
  const [factor, setFactor] = useState('100')
  const [newTable, setNewTable] = useState('')
  const [keyName, setKeyName] = useState('id')
  /** The change the first click was for. Any other choice is not armed,
   *  so the second click confirms exactly what the first one said. */
  const [armedFor, setArmedFor] = useState<string | null>(null)

  // A table renamed or dropped, here or by the pack's own timeline, is no
  // longer offered: fall back to one that is.
  const shownTable = tables.includes(table) ? table : (tables[0] ?? '')
  const columns = schema.silos[silo]?.tables[shownTable] ?? []
  const choosable = operation === 'rescale_column' ? columns.filter((c) => NUMERIC.has(c.type)) : columns
  const picked = choosable.some((c) => c.name === column) ? column : (choosable[0]?.name ?? '')
  const breaking = schema.operations[operation] ?? true

  const typed = () => ({
    type,
    ...(type === 'text' ? { length } : {}),
    ...(type === 'decimal' ? { precision, scale } : {}),
  })

  const body = (): Record<string, unknown> | null => {
    const base = { command: 'drift', operation, table: `${silo}.${shownTable}` }
    switch (operation) {
      case 'add_column':
        return column.trim() ? { ...base, column: column.trim(), ...typed() } : null
      case 'drop_column':
        return picked ? { ...base, column: picked } : null
      case 'rename_column':
        return picked && to.trim() ? { ...base, column: picked, to: to.trim() } : null
      case 'change_column_type':
        return picked ? { ...base, column: picked, ...typed() } : null
      case 'rescale_column':
        return picked && factor.trim() ? { ...base, column: picked, factor: factor.trim() } : null
      case 'add_table':
        return newTable.trim() && keyName.trim()
          ? {
              command: 'drift',
              operation,
              table: `${silo}.${newTable.trim()}`,
              columns: { [keyName.trim()]: { type: 'text', length: 64, primary_key: true, nullable: false } },
            }
          : null
      case 'drop_table':
        return shownTable ? base : null
      case 'rename_table':
        return shownTable && to.trim() ? { ...base, to: to.trim() } : null
      default:
        return null
    }
  }

  const ready = body()
  const asked = ready === null ? null : JSON.stringify(ready)
  const armed = breaking && asked !== null && armedFor === asked
  const apply = () => {
    if (ready === null) return
    if (breaking && !armed) {
      setArmedFor(asked)
      return
    }
    setArmedFor(null)
    act('command', ready)
  }

  const onTable = operation !== 'add_table'
  return (
    <div className="simulator-panel__change">
      <div className="simulator-panel__row">
        <FormGroup label="Database" labelFor="simulator-drift-silo">
          <HTMLSelect
            id="simulator-drift-silo"
            value={silo}
            onChange={(event) => setSilo(event.currentTarget.value)}
            options={silos}
          />
        </FormGroup>
        <FormGroup label="Change" labelFor="simulator-drift-operation">
          <HTMLSelect
            id="simulator-drift-operation"
            value={operation}
            onChange={(event) => setOperation(event.currentTarget.value)}
            options={Object.keys(schema.operations).map((name) => ({ value: name, label: LABELS[name] ?? name }))}
          />
        </FormGroup>
        {onTable ? (
          <FormGroup label="Table" labelFor="simulator-drift-table">
            <HTMLSelect
              id="simulator-drift-table"
              value={shownTable}
              onChange={(event) => setTable(event.currentTarget.value)}
              options={tables}
            />
          </FormGroup>
        ) : (
          <>
            <FormGroup label="New table" labelFor="simulator-drift-new-table">
              <InputGroup id="simulator-drift-new-table" value={newTable} onValueChange={setNewTable} />
            </FormGroup>
            <FormGroup label="Its key column" labelFor="simulator-drift-key" helperText="Text, the primary key.">
              <InputGroup id="simulator-drift-key" value={keyName} onValueChange={setKeyName} />
            </FormGroup>
          </>
        )}
        {operation === 'add_column' ? (
          <FormGroup label="New column" labelFor="simulator-drift-new-column">
            <InputGroup id="simulator-drift-new-column" value={column} onValueChange={setColumn} />
          </FormGroup>
        ) : null}
        {PICKS_A_COLUMN.has(operation) ? (
          <FormGroup label="Column" labelFor="simulator-drift-column">
            <HTMLSelect
              id="simulator-drift-column"
              value={picked}
              onChange={(event) => setColumn(event.currentTarget.value)}
              options={choosable.map((c) => ({ value: c.name, label: `${c.name} (${c.type})` }))}
            />
          </FormGroup>
        ) : null}
        {operation === 'rename_column' || operation === 'rename_table' ? (
          <FormGroup label="New name" labelFor="simulator-drift-to">
            <InputGroup id="simulator-drift-to" value={to} onValueChange={setTo} />
          </FormGroup>
        ) : null}
        {operation === 'add_column' || operation === 'change_column_type' ? (
          <>
            <FormGroup label="Type" labelFor="simulator-drift-type">
              <HTMLSelect
                id="simulator-drift-type"
                value={type}
                onChange={(event) => setType(event.currentTarget.value)}
                options={TYPES}
              />
            </FormGroup>
            {type === 'text' ? (
              <FormGroup label="Length" labelFor="simulator-drift-length">
                <NumericInput id="simulator-drift-length" min={1} value={length} onValueChange={setLength} />
              </FormGroup>
            ) : null}
            {type === 'decimal' ? (
              <>
                <FormGroup label="Precision" labelFor="simulator-drift-precision">
                  <NumericInput
                    id="simulator-drift-precision"
                    min={1}
                    max={38}
                    value={precision}
                    onValueChange={setPrecision}
                  />
                </FormGroup>
                <FormGroup label="Scale" labelFor="simulator-drift-scale">
                  <NumericInput id="simulator-drift-scale" min={0} value={scale} onValueChange={setScale} />
                </FormGroup>
              </>
            ) : null}
          </>
        ) : null}
        {operation === 'rescale_column' ? (
          <FormGroup label="Multiply by" labelFor="simulator-drift-factor">
            <InputGroup id="simulator-drift-factor" value={factor} onValueChange={setFactor} />
          </FormGroup>
        ) : null}
      </div>
      <div className="simulator-panel__row simulator-panel__row--centred">
        <Button intent={armed ? 'danger' : 'primary'} disabled={acting || ready === null} onClick={apply}>
          {armed ? 'Apply it: this cannot be undone' : 'Apply'}
        </Button>
        {breaking ? (
          <span className="simulator-panel__note">
            {armed
              ? 'A reader holding the old shape breaks, and the world carries on with the change. Only discarding the world goes back.'
              : 'Breaking: asks again before it applies.'}
          </span>
        ) : null}
      </div>
    </div>
  )
}

function History({ schema }: { schema: WorldSchema }) {
  const changes = Object.entries(schema.silos)
    .flatMap(([silo, held]) => held.history.map((change) => ({ silo, ...change })))
    .sort((a, b) => a.at.localeCompare(b.at))
  if (changes.length === 0) return <p>No schema has changed in this world yet.</p>
  return (
    <HTMLTable compact aria-label="Schema changes so far">
      <thead>
        <tr>
          <th>When, in the world</th>
          <th>Database</th>
          <th>Change</th>
          <th aria-label="Breaking" />
        </tr>
      </thead>
      <tbody>
        {changes.map((change, index) => (
          <tr key={`${change.silo}-${change.at}-${index}`}>
            <td>{when(change.at)}</td>
            <td>{change.silo}</td>
            <td>{change.detail}</td>
            <td>
              <StatusTag state={change.breaking ? 'refused' : 'neutral'}>
                {change.breaking ? 'breaking' : 'additive'}
              </StatusTag>
            </td>
          </tr>
        ))}
      </tbody>
    </HTMLTable>
  )
}
