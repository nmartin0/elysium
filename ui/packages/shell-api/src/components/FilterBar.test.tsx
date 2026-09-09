import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

import FilterBar, { describeFilter, operatorsFor } from './FilterBar'
import type { FieldSchema } from '../types'

const FIELDS: Record<string, FieldSchema> = {
  name: { type: 'string' },
  balance: { type: 'number' },
  opened: { type: 'string' },
  owner: { type: 'link', target: 'Customer' },
}

describe('which operators a field offers', () => {
  it('offers range only for numbers', () => {
    // Offering an operator the server will reject is a control that
    // exists to fail. core/filters.py restricts range to integer and
    // number; this mirrors that table.
    expect(operatorsFor('number')).toContain('range')
    expect(operatorsFor('string')).not.toContain('range')
  })

  it('offers the text and date operators only for strings', () => {
    expect(operatorsFor('string')).toEqual(
      expect.arrayContaining(['contains', 'date_range', 'relative_date']),
    )
    expect(operatorsFor('number')).not.toContain('contains')
  })

  it('always offers equality', () => {
    // The one operator with no type restriction.
    for (const type of ['string', 'number', 'boolean', undefined]) {
      expect(operatorsFor(type)).toContain('equals')
    }
  })
})

describe('how an applied filter reads', () => {
  it('says what a range covers', () => {
    expect(describeFilter({ field: 'balance', operator: 'range', value: [10, 20] }))
      .toContain('10')
  })

  it('distinguishes keep from exclude', () => {
    expect(describeFilter({ field: 'r', operator: 'in', value: ['a'] })).toContain('is a')
    expect(describeFilter({ field: 'r', operator: 'not_in', value: ['a'] })).toContain('is not a')
  })
})

describe('FilterBar', () => {
  it('never offers a link field', () => {
    // A relationship has no column to compare, and the server would
    // reject a filter on one.
    render(<FilterBar fields={FIELDS} filters={[]} onChange={vi.fn()} />)

    const picker = screen.getByLabelText('Field to filter')
    expect(picker.textContent).not.toContain('owner')
  })

  it('builds a filter from the three controls', () => {
    const onChange = vi.fn()
    render(<FilterBar fields={FIELDS} filters={[]} onChange={onChange} />)

    fireEvent.change(screen.getByLabelText('Field to filter'), { target: { value: 'name' } })
    fireEvent.change(screen.getByLabelText('Value'), { target: { value: 'Ada' } })
    fireEvent.click(screen.getByRole('button', { name: /Add/ }))

    expect(onChange).toHaveBeenCalledWith([
      { field: 'name', operator: 'equals', value: 'Ada' },
    ])
  })

  it('sends a PAIR for a two-part operator', () => {
    /**
     * A bare string for a range is the shape the server rejects, so it
     * is not constructible here -- the second box appears with the
     * operator that needs it.
     */
    const onChange = vi.fn()
    render(<FilterBar fields={FIELDS} filters={[]} onChange={onChange} />)

    fireEvent.change(screen.getByLabelText('Field to filter'), { target: { value: 'balance' } })
    fireEvent.change(screen.getByLabelText('Operator'), { target: { value: 'range' } })
    fireEvent.change(screen.getByLabelText('From'), { target: { value: '10' } })
    fireEvent.change(screen.getByLabelText('To'), { target: { value: '20' } })
    fireEvent.click(screen.getByRole('button', { name: /Add/ }))

    expect(onChange).toHaveBeenCalledWith([
      { field: 'balance', operator: 'range', value: ['10', '20'] },
    ])
  })

  it('resets the operator when the field changes', () => {
    /**
     * One valid for a number is not valid for a string. Leaving a
     * stale choice builds a filter the server refuses, and the user
     * sees an error for a control they never touched.
     */
    render(<FilterBar fields={FIELDS} filters={[]} onChange={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('Field to filter'), { target: { value: 'balance' } })
    fireEvent.change(screen.getByLabelText('Operator'), { target: { value: 'range' } })

    fireEvent.change(screen.getByLabelText('Field to filter'), { target: { value: 'name' } })

    expect(screen.getByLabelText('Operator')).toHaveValue('equals')
  })

  it('shows what is applied, and lets it be removed', () => {
    // A filter you cannot see is one you cannot remove, and results
    // you cannot explain.
    const onChange = vi.fn()
    render(
      <FilterBar
        fields={FIELDS}
        filters={[{ field: 'name', operator: 'contains', value: 'Ada' }]}
        onChange={onChange}
      />,
    )
    expect(screen.getByText(/name contains/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Clear all/ }))

    expect(onChange).toHaveBeenCalledWith([])
  })

  it('refuses to add an empty value', () => {
    // `equals ""` is a real filter that matches nothing, and reaching
    // it by pressing Add on a blank box is never what someone meant.
    render(<FilterBar fields={FIELDS} filters={[]} onChange={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('Field to filter'), { target: { value: 'name' } })

    expect(screen.getByRole('button', { name: /Add/ })).toBeDisabled()
  })
})
