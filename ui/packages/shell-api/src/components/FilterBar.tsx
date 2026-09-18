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
 * core/filters.py's own table: range is for numbers, contains and the
 * date operators for strings, equality for anything. Offering an
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
export const ALL_OPERATORS = ['equals', 'range', 'contains', 'date_range', 'relative_date']

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
  return [
    'equals',
    ...(numeric ? ['range'] : []),
    ...(type === 'string' ? ['contains', 'date_range', 'relative_date'] : []),
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
  if (operator === 'relative_date') return `${field} in the last ${String(value)}`
  return `${field} = ${String(value)}`
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

  // Link fields are excluded: a relationship has no column to compare,
  // and the server would reject a filter on one.
  const filterable = Object.entries(fields).filter(([, f]) => f.type !== 'link')
  const chosen = field ? fields[field] : undefined
  // data_type, not type. `type` says data-or-link; `data_type` is the
  // semantic type the filter vocabulary validates against.
  const operators = operatorsFor(chosen?.data_type)
  const needsTwo = operator === 'range' || operator === 'date_range'

  function add() {
    if (!field || value === '') return
    onChange([
      ...filters,
      {
        field,
        operator,
        // A two-part operator takes a pair; everything else takes one
        // value. Sending a bare string for a range is the shape error
        // the server would reject, so it is not constructible here.
        value: needsTwo ? [value, upper] : value,
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

            <InputGroup
              aria-label={needsTwo ? 'From' : 'Value'}
              placeholder={operator === 'relative_date' ? 'e.g. 7d' : needsTwo ? 'From' : 'Value'}
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

            <Button icon="add" onClick={add} disabled={value === ''}>
              Add
            </Button>
          </>
        )}
      </div>
    </div>
  )
}
