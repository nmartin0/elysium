import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { useState } from 'react'

import FilterBox, { RECENT_SENT, rememberSent } from './FilterBox'

/**
 * Stands in for the URL: a parent whose value updates one render
 * LATE, which is what a router navigation does. Typing into a box
 * driven directly by that parent loses characters, because React
 * re-renders with the previous value and overwrites the one just
 * typed.
 */
function LaggingParent({ onValue }: { onValue: (value: string) => void }) {
  const [committed, setCommitted] = useState('')
  const [pending, setPending] = useState<string | null>(null)

  // Applies the PREVIOUS keystroke, never the current one -- the lag a
  // navigation introduces.
  function receive(next: string) {
    if (pending !== null) setCommitted(pending)
    setPending(next)
    onValue(next)
  }

  return <FilterBox value={committed} onChange={receive} placeholder="Filter..." />
}

describe('FilterBox', () => {
  it('keeps every character when the parent lags behind', () => {
    // THE bug: typing "Cust" quickly produced "Cut" or "Cst", because
    // each character triggered a router navigation and React
    // re-rendered with the stale URL value in between.
    const seen: string[] = []
    render(<LaggingParent onValue={(value) => seen.push(value)} />)
    const box = screen.getByPlaceholderText('Filter...')

    fireEvent.change(box, { target: { value: 'C' } })
    fireEvent.change(box, { target: { value: 'Cu' } })
    fireEvent.change(box, { target: { value: 'Cus' } })
    fireEvent.change(box, { target: { value: 'Cust' } })

    expect(box).toHaveValue('Cust')
    expect(seen[seen.length - 1]).toBe('Cust')
  })

  it('adopts a value that arrives from real navigation', () => {
    // The other direction, and why local state alone is not enough:
    // pressing Back or following a cross-reference sets the filter
    // from outside, and the box must show it.
    const { rerender } = render(
      <FilterBox value="" onChange={() => {}} placeholder="Filter..." />,
    )

    rerender(<FilterBox value="CustomerTransactions" onChange={() => {}} placeholder="Filter..." />)

    expect(screen.getByPlaceholderText('Filter...')).toHaveValue('CustomerTransactions')
  })

  it('reports every keystroke upward', () => {
    // The URL still updates per character -- that is what makes a view
    // shareable and reloadable. Local state changes what the box
    // SHOWS, not what it reports.
    const onChange = vi.fn()
    render(<FilterBox value="" onChange={onChange} placeholder="Filter..." />)

    fireEvent.change(screen.getByPlaceholderText('Filter...'), { target: { value: 'Cu' } })

    expect(onChange).toHaveBeenCalledWith('Cu')
  })

  it('shows the clear button only when there is text', () => {
    render(<FilterBox value="" onChange={() => {}} placeholder="Filter..." />)

    expect(screen.queryByLabelText('Clear filter')).not.toBeInTheDocument()

    fireEvent.change(screen.getByPlaceholderText('Filter...'), { target: { value: 'C' } })

    expect(screen.getByLabelText('Clear filter')).toBeInTheDocument()
  })

  it('clears both the box and the parent', () => {
    const onChange = vi.fn()
    render(<FilterBox value="C" onChange={onChange} placeholder="Filter..." />)

    fireEvent.click(screen.getByLabelText('Clear filter'))

    expect(screen.getByPlaceholderText('Filter...')).toHaveValue('')
    expect(onChange).toHaveBeenCalledWith('')
  })
})

describe('rememberSent', () => {
  it('never grows past the bound', () => {
    // Found in a memory-leak audit: the echo record was an unbounded
    // Set, so a long session of typing without navigating accumulated
    // every prefix ever entered.
    //
    // Tested on the FUNCTION, not through the component. A first
    // version typed 500 characters into the box and asserted the box
    // looked right, which passed against a deliberately unbounded
    // version -- the bound is invisible from rendered output.
    let record: string[] = []
    for (let index = 0; index < 500; index += 1) {
      record = rememberSent(record, `query-${index}`)
    }

    expect(record).toHaveLength(RECENT_SENT)
  })

  it('keeps the NEWEST values, since an echo is always recent', () => {
    // Dropping the oldest is only safe because a lagging parent is at
    // most a render or two behind. Dropping the newest would break the
    // thing the record exists for.
    let record: string[] = []
    for (const value of ['a', 'b', 'c']) record = rememberSent(record, value)

    expect(record[record.length - 1]).toBe('c')
  })
})

describe('FilterBox -- bounded memory', () => {
  it('still keeps every character when the parent lags', () => {
    // The bound must not reintroduce the bug it sits beside. An echo
    // arrives at most a render or two late, so dropping older entries
    // is safe -- but that is the claim, and this is what checks it.
    const seen: string[] = []
    render(<LaggingParent onValue={(value) => seen.push(value)} />)
    const box = screen.getByPlaceholderText('Filter...')

    for (const value of ['C', 'Cu', 'Cus', 'Cust', 'Custo', 'Custom', 'Customer']) {
      fireEvent.change(box, { target: { value } })
    }

    expect(box).toHaveValue('Customer')
    expect(seen[seen.length - 1]).toBe('Customer')
  })
})
