/**
 * Describing a type and its fields (DEV_UI 13.7): what they are CALLED
 * and what they MEAN, written to ontology_schema.yaml.
 *
 * THE FILE STAYS THE SOURCE OF TRUTH, as with the settings editor: the
 * server changes only the lines these keys sit on, keeps every comment,
 * runs the loader on the result before writing, and reloads. So the new
 * names reach every reader and the agent, and an operator's editor
 * reads the same file.
 *
 * PRESENTATION, NOT SHAPE. Names, descriptions, a group and which field
 * heads an object -- nothing here adds a field, moves data or opens
 * access, which is why it applies at once with no second person
 * (decided 16 October). The server holds the allowlist; this form only
 * offers what is on it.
 *
 * EMPTY MEANS NOT SET. A cleared box removes the key, and the reader
 * falls back to a name made from the type's own: the server refuses an
 * empty string, because an empty display name renders as a blank.
 *
 * REVIEW, THEN APPLY: the exact lines that will change, before anything
 * is written (DEV_UI 13.5).
 */

import { Button, Dialog, DialogBody, DialogFooter, HTMLSelect, InputGroup, TextArea } from '@blueprintjs/core'
import {
  ApiError,
  applyOntologyDescriptions,
  type DescribedType,
  type DescriptionChange,
  getErrorMessage,
  getOntologyDescriptions,
  handleIfSessionExpired,
  type OntologyDescriptions,
  previewOntologyDescriptions,
} from '@elysium/shell-api/api'
import ErrorState from '@elysium/shell-api/components/ErrorState'
import FileDiff from '@elysium/shell-api/components/FileDiff'
import LoadingState from '@elysium/shell-api/components/LoadingState'
import { useEffect, useRef, useState } from 'react'

const TYPE_KEYS = ['display_name', 'plural_display_name', 'description', 'group', 'title_field'] as const
const FIELD_KEYS = ['display_name', 'description'] as const
/** The server's limits (core/config_editing.py), so a reader is stopped
 *  while typing rather than told after Review. */
const LONGEST: Record<string, number> = {
  display_name: 80,
  plural_display_name: 80,
  description: 1000,
  group: 60,
  title_field: 100,
}

/** One draft per key: the type's own under '', each field's under its name. */
type Drafts = Record<string, Record<string, string>>

function draftsOf(type: DescribedType): Drafts {
  const drafts: Drafts = { '': Object.fromEntries(TYPE_KEYS.map((key) => [key, type[key] ?? ''])) }
  for (const [name, field] of Object.entries(type.fields)) {
    drafts[name] = Object.fromEntries(FIELD_KEYS.map((key) => [key, field[key] ?? '']))
  }
  return drafts
}

/** What differs from the file, as the server's changes. Whitespace at the
 *  ends is not a change: the server would strip it anyway. */
function changesFrom(objectType: string, type: DescribedType, drafts: Drafts): DescriptionChange[] {
  const changes: DescriptionChange[] = []
  const compare = (field: string | null, key: string, was: string | null, draft: string) => {
    const now = draft.trim() === '' ? null : draft.trim()
    if (now !== was) changes.push({ object_type: objectType, field, key, value: now })
  }
  for (const key of TYPE_KEYS) compare(null, key, type[key], drafts['']![key]!)
  for (const [name, field] of Object.entries(type.fields)) {
    // A field added to the file since the drafts were made has none:
    // untouched, it is no change.
    for (const key of FIELD_KEYS) compare(name, key, field[key], drafts[name]?.[key] ?? field[key] ?? '')
  }
  return changes
}

/** A description is one line in the file; a pasted paragraph becomes one. */
function oneLine(text: string): string {
  return text.replace(/\s*[\r\n]+\s*/g, ' ')
}

export default function DescribeType({
  objectType,
  shownAs,
  onClose,
  onApplied,
  onSessionExpired,
}: {
  objectType: string
  /** What readers are shown for the type now -- the fallback, when its
   *  display name is not set. */
  shownAs: string
  onClose: () => void
  onApplied: (generation: number) => void
  onSessionExpired: () => void
}) {
  const [loaded, setLoaded] = useState<OntologyDescriptions | null>(null)
  const [drafts, setDrafts] = useState<Drafts | null>(null)
  const [preview, setPreview] = useState<string[] | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const [stale, setStale] = useState(false)
  const [busy, setBusy] = useState(false)
  const latestSessionExpired = useRef(onSessionExpired)
  useEffect(() => {
    latestSessionExpired.current = onSessionExpired
  })

  const load = (keepDrafts: boolean) => {
    getOntologyDescriptions()
      .then((body) => {
        setLoaded(body)
        setStale(false)
        setProblem(null)
        const type = body.types[objectType]
        // A RELOAD AFTER A 409 KEEPS WHAT WAS TYPED: the file moved under
        // the reader, and their edits are still what they meant.
        // A field new in the file starts as the file has it.
        if (type) setDrafts((current) => (keepDrafts && current ? { ...draftsOf(type), ...current } : draftsOf(type)))
      })
      .catch((caught: unknown) => {
        if (handleIfSessionExpired(caught, latestSessionExpired.current)) return
        setProblem(getErrorMessage(caught))
      })
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => load(false), [])

  const type = loaded?.types[objectType]
  const changes = type && drafts ? changesFrom(objectType, type, drafts) : []

  const edit = (field: string, key: string, value: string) => {
    setPreview(null)
    setProblem(null)
    setDrafts((current) => (current ? { ...current, [field]: { ...current[field], [key]: value } } : current))
  }

  const failed = (caught: unknown) => {
    if (handleIfSessionExpired(caught, latestSessionExpired.current)) return
    const conflict = caught instanceof ApiError && caught.status === 409
    setStale(conflict)
    setProblem(
      conflict
        ? `${caught.message} Your changes are still here; load the file again to apply them to it.`
        : getErrorMessage(caught),
    )
  }

  const review = () => {
    if (!loaded) return
    setBusy(true)
    previewOntologyDescriptions(loaded.digest, changes)
      .then(setPreview)
      .catch(failed)
      .finally(() => setBusy(false))
  }

  const apply = () => {
    if (!loaded) return
    setBusy(true)
    applyOntologyDescriptions(loaded.digest, changes)
      .then((result) => onApplied(result.to_generation))
      .catch((caught: unknown) => {
        setPreview(null)
        failed(caught)
      })
      .finally(() => setBusy(false))
  }

  const text = (field: string, key: string, id: string, label: string, placeholder: string, long = false) => {
    const value = drafts?.[field]?.[key] ?? ''
    const common = {
      id,
      value,
      placeholder,
      maxLength: LONGEST[key],
      'aria-label': label,
    }
    return long ? (
      <TextArea {...common} fill autoResize onChange={(event) => edit(field, key, oneLine(event.target.value))} />
    ) : (
      <InputGroup {...common} onChange={(event) => edit(field, key, event.target.value)} />
    )
  }

  const groups = loaded
    ? [...new Set(Object.values(loaded.types).flatMap((t) => (t.group ? [t.group] : [])))].sort((a, b) =>
        a.localeCompare(b),
      )
    : []
  const dataFields = type ? Object.entries(type.fields).filter(([, field]) => field.kind === 'data') : []

  return (
    <Dialog isOpen onClose={onClose} title={`Describe ${shownAs}`} className="describe-type">
      <DialogBody>
        {loaded === null && problem === null && <LoadingState />}
        {loaded !== null && !type && <ErrorState>{objectType} is no longer in ontology_schema.yaml.</ErrorState>}
        {type && drafts && !preview && (
          <>
            <p className="describe-type__lede">
              What {shownAs} and its fields are called and what they mean. Written to ontology_schema.yaml, keeping its
              comments; nothing about its data or who can see it changes. A box left empty is not set.
            </p>
            <div className="describe-type__grid">
              <label htmlFor="describe-display_name">Name</label>
              {text('', 'display_name', 'describe-display_name', 'Name', `Not set: shown as ${objectType}`)}
              <label htmlFor="describe-plural_display_name">Plural</label>
              {text('', 'plural_display_name', 'describe-plural_display_name', 'Plural', 'Not set: the name with an s')}
              <label htmlFor="describe-description">Description</label>
              {text('', 'description', 'describe-description', 'Description', 'Not set', true)}
              <label htmlFor="describe-group">Group</label>
              <div>
                <InputGroup
                  id="describe-group"
                  aria-label="Group"
                  value={drafts['']!.group ?? ''}
                  placeholder="Not set"
                  maxLength={LONGEST.group}
                  list="describe-groups"
                  onChange={(event) => edit('', 'group', event.target.value)}
                />
                <datalist id="describe-groups">
                  {groups.map((group) => (
                    <option key={group} value={group} />
                  ))}
                </datalist>
              </div>
              <label htmlFor="describe-title_field">Title</label>
              <HTMLSelect
                id="describe-title_field"
                value={drafts['']!.title_field ?? ''}
                onChange={(event) => edit('', 'title_field', event.target.value)}
              >
                <option value="">Not set: objects are titled by their id</option>
                {dataFields.map(([name, field]) => (
                  <option key={name} value={name}>
                    {field.display_name ?? name}
                  </option>
                ))}
              </HTMLSelect>
            </div>

            <h4 className="describe-type__fields-heading">Fields</h4>
            <table className="describe-type__fields">
              <thead>
                <tr>
                  <th scope="col">Field</th>
                  <th scope="col">Name</th>
                  <th scope="col">Description</th>
                </tr>
              </thead>
              <tbody>
                {Object.keys(type.fields).map((name) => (
                  <tr key={name}>
                    <th scope="row" className="describe-type__field-name">
                      {name}
                    </th>
                    <td>{text(name, 'display_name', `describe-${name}-name`, `${name} name`, 'Not set')}</td>
                    <td>
                      {text(
                        name,
                        'description',
                        `describe-${name}-description`,
                        `${name} description`,
                        'Not set',
                        true,
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
        {preview && (
          <>
            <p className="describe-type__lede">These lines of ontology_schema.yaml will change:</p>
            <FileDiff lines={preview} label="Changes to ontology_schema.yaml" />
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
                Apply and reload
              </Button>
            </>
          ) : (
            <>
              {stale && (
                <Button minimal onClick={() => load(true)}>
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
