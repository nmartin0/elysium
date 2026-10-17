/**
 * FilterBar -- what is filtering the results, and how to add or remove
 * one.
 *
 * The filter vocabulary has seven operators. Until now two were
 * reachable, both by clicking a chart bar, so nobody could ask for "a
 * balance over 10,000" or "opened last week" at all -- the questions
 * people actually have.
 *
 * APPLIED FILTERS ARE VISIBLE, which they were not. A chart click
 * narrowed the table and the only sign was a dimmed bar on a tab you
 * might not be looking at. A filter you cannot see is one you cannot
 * remove, and results you cannot explain.
 *
 * THE OPERATORS OFFERED COME FROM THE FIELD'S TYPE, mirroring
 * core/filters.py's own table: range is for numbers, contains for
 * strings, the date operators for strings AND date and timestamp
 * fields, equality for anything. Offering an
 * operator the server will reject is a control that exists to fail.
 */

import { useState } from 'react'
import { Button, HTMLSelect, InputGroup, Tag } from '@blueprintjs/core'

import type { FieldSchema } from '../types'

export interface FieldFilter {
  field: string
  operator: string
  value: unknown
}

/**
 * Which operators a field of this type can take.
 *
 * Mirrors OPERATOR_TYPES in core/filters.py. The duplication is
 * deliberate and small: the alternative is a round trip to ask what a
 * dropdown may contain, and the server still validates -- this only
 * decides what to OFFER.
 */
export const ALL_OPERATORS = ['equals', 'in', 'not_in', 'range', 'contains', 'date_range', 'relative_date']

export function operatorsFor(type: string | undefined): string[] {
  // NO declared type means NO restriction, which is the server's own
  // rule: "a field with no declared data_type accepts anything --
  // declaring the type is how an author opts into this check".
  //
  // A first version returned only `equals` here, which made the UI
  // STRICTER than the server and left every field in the fixture
  // ontology with one operator, because only risk_score declares a
  // type. Being more restrictive than the thing you are a client of is
  // not the safe direction: it hides capability the user has.
  if (type === undefined || type === null) return [...ALL_OPERATORS]

  const numeric = type === 'integer' || type === 'number'
  // THE DATE OPERATORS ON DATE FIELDS TOO (16 October). They were
  // offered on strings only, so a field declared `date` or `timestamp`
  // -- the one kind the server's own comment calls gap-free -- could
  // not be filtered by date at all. core/filters.py allows all four.
  const dateLike = type === 'string' || type === 'date' || type === 'timestamp' || type === 'timestamptz'
  return [
    'equals',
    // `in` and `not_in` APPLY TO ANY TYPE, which is why they sit
    // beside equals rather than in a type branch -- core/filters.py
    // lists both with `None` for allowed types, exactly as equals.
    //
    // They had a line each in describeFilter and no way to build
    // one, so a saved view could carry a set filter and nobody could
    // create one: the vocabulary existed, the server accepted it,
    // and the only way in was somebody else's link.
    'in',
    'not_in',
    ...(numeric ? ['range'] : []),
    ...(type === 'string' ? ['contains'] : []),
    ...(dateLike ? ['date_range', 'relative_date'] : []),
  ]
}

/** How a filter reads once applied. Short, because a pill competes
 *  with every other pill for one line. */
export function describeFilter(filter: FieldFilter): string {
  const { field, operator, value } = filter
  if (operator === 'range' && Array.isArray(value)) return `${field} ${value[0]}–${value[1]}`
  if (operator === 'date_range' && Array.isArray(value)) return `${field} ${value[0]}→${value[1]}`
  if (operator === 'in' && Array.isArray(value)) return `${field} is ${value.join(', ')}`
  if (operator === 'not_in' && Array.isArray(value)) return `${field} is not ${value.join(', ')}`
  if (operator === 'contains') return `${field} contains "${String(value)}"`
  if (operator === 'relative_date') return describeRelative(field, value)
  return `${field} = ${String(value)}`
}

/**
 * A relative date as the server takes it: `since_days_ago` is "in the
 * last N days", `until_days_ago` is "more than N days ago"
 * (core/filters.py, resolve_relative_date -- measured from now, in UTC).
 */
function describeRelative(field: string, value: unknown): string {
  if (value !== null && typeof value === 'object') {
    const { since_days_ago: since, until_days_ago: until } = value as Record<string, unknown>
    if (typeof since === 'number' && typeof until === 'number') {
      return `${field} between ${since} and ${until} days ago`
    }
    if (typeof since === 'number') return `${field} in the last ${daysWord(since)}`
    if (typeof until === 'number') return `${field} more than ${daysWord(until)} ago`
  }
  return `${field} in the last ${String(value)}`
}

function daysWord(days: number): string {
  return days === 1 ? '1 day' : `${days} days`
}

/** Whole days from 1 up, or null. The server refuses fractions and
 *  negatives; refusing them here keeps the Add button honest. */
function wholeDays(text: string): number | null {
  if (!/^\s*\d+\s*$/.test(text)) return null
  const days = Number(text)
  return days >= 1 ? days : null
}

interface FilterBarProps {
  fields: Record<string, FieldSchema>
  filters: FieldFilter[]
  onChange: (filters: FieldFilter[]) => void
}

export default function FilterBar({ fields, filters, onChange }: FilterBarProps) {
  const [field, setField] = useState('')
  const [operator, setOperator] = useState('equals')
  const [value, setValue] = useState('')
  const [upper, setUpper] = useState('')
  // WHICH SIDE OF "N DAYS AGO" a relative date keeps. Both are the one
  // server operator, so this is a choice inside it, not another.
  const [direction, setDirection] = useState<'since' | 'until'>('since')

  // Link fields are excluded: a relationship has no column to compare,
  // and the server would reject a filter on one.
  const filterable = Object.entries(fields).filter(([, f]) => f.type !== 'link')
  const chosen = field ? fields[field] : undefined
  // data_type, not type. `type` says data-or-link; `data_type` is the
  // semantic type the filter vocabulary validates against.
  const operators = operatorsFor(chosen?.data_type)
  const needsTwo = operator === 'range' || operator === 'date_range'
  /**
   * A SET OPERATOR TAKES A LIST, and an EMPTY one is refused by the
   * server for a reason worth honouring here: "an empty set would mean
   * 'match nothing' for `in` and 'match everything' for `not_in` --
   * opposite outcomes from the same mistake". So this splits on commas,
   * drops blanks, and will not add a filter that ends up empty.
   */
  const isSet = operator === 'in' || operator === 'not_in'
  const isRelative = operator === 'relative_date'
  const days = isRelative ? wholeDays(value) : null
  const setValues = value
    .split(',')
    .map((part) => part.trim())
    .filter((part) => part !== '')

  function add() {
    if (!field || value === '') return
    if (isSet && setValues.length === 0) return
    if (isRelative && days === null) return
    onChange([
      ...filters,
      {
        field,
        operator,
        // A two-part operator takes a pair, a SET takes a list, and
        // everything else one value. Sending the wrong shape is what
        // the server rejects, so none of them is constructible here.
        //
        // A RELATIVE DATE IS AN OBJECT. This sent the typed text ("7d"),
        // which the server refuses -- so no view filtered on a recent
        // date could be made here, and no trigger could watch one.
        value: needsTwo
          ? [value, upper]
          : isSet
            ? setValues
            : isRelative
              ? { [direction === 'since' ? 'since_days_ago' : 'until_days_ago']: days }
              : value,
      },
    ])
    setValue('')
    setUpper('')
  }

  return (
    <div className="filter-bar">
      {filters.length > 0 && (
        <div className="filter-bar__pills">
          {filters.map((filter, index) => (
            <Tag
              key={`${filter.field}-${filter.operator}-${index}`}
              minimal
              // Removable, because a filter you cannot remove is one
              // that has to be undone by reloading.
              onRemove={() => onChange(filters.filter((_, i) => i !== index))}
            >
              {describeFilter(filter)}
            </Tag>
          ))}
          <Button minimal small onClick={() => onChange([])}>
            Clear all
          </Button>
        </div>
      )}

      <div className="filter-bar__add">
        <HTMLSelect
          aria-label="Field to filter"
          value={field}
          onChange={(e) => {
            setField(e.currentTarget.value)
            // Reset the operator with the field: one valid for a
            // number is not valid for a string, and leaving a stale
            // choice builds a filter the server refuses.
            const next = operatorsFor(fields[e.currentTarget.value]?.type)
            setOperator(next[0] ?? 'equals')
          }}
        >
          <option value="">Add a filter…</option>
          {filterable.map(([name, f]) => (
            <option key={name} value={name}>
              {f.display_name ?? name}
            </option>
          ))}
        </HTMLSelect>

        {field && (
          <>
            <HTMLSelect aria-label="Operator" value={operator} onChange={(e) => setOperator(e.currentTarget.value)}>
              {operators.map((op) => (
                <option key={op} value={op}>
                  {op.replace(/_/g, ' ')}
                </option>
              ))}
            </HTMLSelect>

            {isRelative && (
              <HTMLSelect
                aria-label="When"
                value={direction}
                onChange={(e) => setDirection(e.currentTarget.value as 'since' | 'until')}
              >
                <option value="since">in the last</option>
                <option value="until">more than</option>
              </HTMLSelect>
            )}

            <InputGroup
              aria-label={needsTwo ? 'From' : isRelative ? 'Days' : 'Value'}
              placeholder={
                isRelative
                  ? direction === 'since'
                    ? 'days, e.g. 30'
                    : 'days ago, e.g. 14'
                  : // A SET NEEDS THE SEPARATOR SAYING SO. Typing one
                    // value into a field marked "Value" and getting a
                    // one-element set is correct but teaches nothing;
                    // the placeholder is where somebody learns that
                    // several are allowed.
                    isSet
                    ? 'us-east, us-west'
                    : needsTwo
                      ? 'From'
                      : 'Value'
              }
              value={value}
              onChange={(e) => setValue(e.currentTarget.value)}
            />
            {needsTwo && (
              <InputGroup
                aria-label="To"
                placeholder="To"
                value={upper}
                onChange={(e) => setUpper(e.currentTarget.value)}
              />
            )}

            <Button icon="add" onClick={add} disabled={value === '' || (isRelative && days === null)}>
              Add
            </Button>
          </>
        )}
      </div>
    </div>
  )
}
