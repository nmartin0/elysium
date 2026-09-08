import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { useState } from 'react'

import FilterBox from './FilterBox'

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

/* The `rememberSent` bound and its tests are gone with the design they
 * belonged to. It kept the last sixteen values sent so any of them
 * could be recognised as an echo -- which is exactly what made
 * navigating BACK to a previously-typed value indistinguishable from
 * one. Waiting for a single outstanding send needs no bound at all. */


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

describe('FilterBox -- navigating back to a value it once sent', () => {
  /**
   * THE bug that blocked Schema's configuration pane, and the reason
   * the old design could not be patched.
   *
   * It remembered every recent value and ignored any incoming one
   * among them. Pressing Back sets the value to "" -- which the box
   * also sent, at mount -- so it was taken for its own echo and the
   * box kept showing the old search against an empty URL.
   *
   * Three patches failed before a probe showed the real sequence:
   * a location key (changes on `replace` too, so it reset on every
   * keystroke), a navigation-type guard, and a missing effect
   * dependency. The distinction needed was not "have I sent this
   * before" but "am I still waiting for my own last send".
   */
  function Parent({ initial }: { initial: string }) {
    const [value, setValue] = useState(initial)
    return (
      <>
        <FilterBox value={value} onChange={setValue} placeholder="Filter..." />
        <button onClick={() => setValue('')}>back</button>
      </>
    )
  }

  it('adopts a value the parent sets, even one it typed before', () => {
    render(<Parent initial="" />)
    const box = screen.getByPlaceholderText('Filter...')
    fireEvent.change(box, { target: { value: 'Cus' } })
    expect(box).toHaveValue('Cus')

    // The parent navigates back to "", which this box sent at mount.
    fireEvent.click(screen.getByText('back'))

    expect(box).toHaveValue('')
  })

  it('waits for its own echo before adopting anything else', () => {
    /**
     * The property the whole design rests on, and the KNOWN LIMIT that
     * comes with it: while a send is outstanding, everything else is
     * treated as a lagging echo.
     *
     * A probe proved no cheaper rule works. An echo CHANGES the value
     * -- typing "C", "Cu", "Cus" makes the parent render "", "C", "Cu"
     * -- so "did the value change" cannot tell an echo from a
     * navigation. Only "is this the value I am waiting for" can.
     *
     * So a parent that never echoes a send leaves the box waiting.
     * Every real parent here echoes through the URL, and the escape
     * hatch tried for the hypothetical case broke fast typing, which
     * is a real one.
     */
    const seen: string[] = []
    render(<LaggingParent onValue={(value) => seen.push(value)} />)
    const box = screen.getByPlaceholderText('Filter...')

    fireEvent.change(box, { target: { value: 'Cust' } })

    // Still showing what was typed, not the parent's lagging value.
    expect(box).toHaveValue('Cust')
    expect(seen).toEqual(['Cust'])
  })
})
