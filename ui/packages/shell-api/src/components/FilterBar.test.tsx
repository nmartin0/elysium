import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

import FilterBar, { ALL_OPERATORS, describeFilter, operatorsFor } from './FilterBar'
import type { FieldSchema } from '../types'

// `type` is data-or-link; `data_type` is the semantic type. A first
// version of this fixture put 'string' in `type`, which is not a value
// the ontology ever produces -- so every test here passed while the
// real screen offered one operator for everything.
const FIELDS: Record<string, FieldSchema> = {
  name: { type: 'data', data_type: 'string' },
  balance: { type: 'data', data_type: 'number' },
  untyped: { type: 'data' },
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
    expect(operatorsFor('string')).toEqual(expect.arrayContaining(['contains', 'date_range', 'relative_date']))
    expect(operatorsFor('number')).not.toContain('contains')
  })

  it('always offers equality', () => {
    // The one operator with no type restriction.
    for (const type of ['string', 'number', 'boolean', undefined]) {
      expect(operatorsFor(type)).toContain('equals')
    }
  })

  it('restricts NOTHING when the author declared no type', () => {
    /**
     * The server's own rule: "a field with no declared data_type
     * accepts anything -- declaring the type is how an author opts
     * into this check".
     *
     * A first version returned only `equals` here, which made the UI
     * stricter than the server and left every field in the fixture
     * ontology with one operator, since only risk_score declares a
     * type. Being more restrictive than the thing you are a client of
     * hides capability the user actually has.
     */
    expect(operatorsFor(undefined)).toEqual(expect.arrayContaining(ALL_OPERATORS))
  })
})

describe('how an applied filter reads', () => {
  it('says what a range covers', () => {
    expect(describeFilter({ field: 'balance', operator: 'range', value: [10, 20] })).toContain('10')
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

    expect(onChange).toHaveBeenCalledWith([{ field: 'name', operator: 'equals', value: 'Ada' }])
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

    expect(onChange).toHaveBeenCalledWith([{ field: 'balance', operator: 'range', value: ['10', '20'] }])
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

describe('the set operators, which were formatted but never offerable', () => {
  /**
   * `in` and `not_in` had a line each in describeFilter and no way to
   * build one. A saved view could carry a set filter and nobody could
   * create one -- the worse half of a missing control: the vocabulary
   * exists, the server accepts it, and the only way in was somebody
   * else's link.
   */

  it('offers them on every type, as core/filters.py does', () => {
    /** Both are listed there with `None` for allowed types, the same as
     *  equals -- so they are not in a type branch. */
    for (const type of ['string', 'number', 'integer', undefined]) {
      expect(operatorsFor(type)).toEqual(expect.arrayContaining(['in', 'not_in']))
    }
  })

  it('sends a LIST, not a comma string', () => {
    const onChange = vi.fn()
    render(<FilterBar fields={FIELDS} filters={[]} onChange={onChange} />)

    fireEvent.change(screen.getByLabelText('Field to filter'), {
      target: { value: 'name' },
    })
    fireEvent.change(screen.getByLabelText('Operator'), { target: { value: 'in' } })
    fireEvent.change(screen.getByLabelText('Value'), {
      target: { value: 'us-east, us-west' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Add/ }))

    expect(onChange).toHaveBeenCalledWith([{ field: 'name', operator: 'in', value: ['us-east', 'us-west'] }])
  })

  it('drops blanks rather than sending an empty member', () => {
    const onChange = vi.fn()
    render(<FilterBar fields={FIELDS} filters={[]} onChange={onChange} />)

    fireEvent.change(screen.getByLabelText('Field to filter'), {
      target: { value: 'name' },
    })
    fireEvent.change(screen.getByLabelText('Operator'), { target: { value: 'in' } })
    fireEvent.change(screen.getByLabelText('Value'), {
      target: { value: 'us-east, , us-west,' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Add/ }))

    expect(onChange).toHaveBeenCalledWith([{ field: 'name', operator: 'in', value: ['us-east', 'us-west'] }])
  })

  it('refuses to add a set that would end up empty', () => {
    /** The server refuses one for a reason worth honouring here: "an
     *  empty set would mean 'match nothing' for `in` and 'match
     *  everything' for `not_in` -- opposite outcomes from the same
     *  mistake". */
    const onChange = vi.fn()
    render(<FilterBar fields={FIELDS} filters={[]} onChange={onChange} />)

    fireEvent.change(screen.getByLabelText('Field to filter'), {
      target: { value: 'name' },
    })
    fireEvent.change(screen.getByLabelText('Operator'), { target: { value: 'in' } })
    fireEvent.change(screen.getByLabelText('Value'), { target: { value: ' , , ' } })
    fireEvent.click(screen.getByRole('button', { name: /Add/ }))

    expect(onChange).not.toHaveBeenCalled()
  })

  it('every operator it offers can be described', () => {
    /** An operator that renders as a raw key in the applied-filter list
     *  is one somebody added here and nowhere else. */
    for (const operator of ALL_OPERATORS) {
      const value =
        operator === 'range' || operator === 'date_range'
          ? ['1', '2']
          : operator === 'in' || operator === 'not_in'
            ? ['a', 'b']
            : 'x'
      const described = describeFilter({ field: 'name', operator, value })

      // AN UNDERSCORE IS THE TELL, not the operator word itself: "name
      // contains \"x\"" legitimately contains "contains", while
      // "name not_in [...]" would mean describeFilter had no case for
      // it and fell through to printing the raw key.
      expect(described).not.toContain('_')
      expect(described.length).toBeGreaterThan(0)
    }
  })
})
