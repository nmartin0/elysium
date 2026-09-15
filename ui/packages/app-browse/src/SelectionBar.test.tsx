/**
 * What an action would apply to, said before it does.
 *
 * FOUNDRY'S RULE SHAPES THIS: an action receives "the current set of
 * selected objects in your exploration (or all objects, if none are
 * selected)". Selecting nothing does not mean acting on nothing -- it
 * means acting on everything the filter matched.
 *
 * THAT IS THE DANGEROUS PART, and the reason this component exists. A
 * person who clears a selection intending to cancel would, on pressing
 * an action, hit the whole result set instead. So the bar states which
 * of the two is in force, always.
 */

import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import SelectionBar from './SelectionBar'

describe('SelectionBar', () => {
  it('counts what is selected', () => {
    // "Selection count appears in the toolbar" in Foundry's own
    // results table, and the reason is that "apply to 3" and "apply to
    // 4,000" are different decisions that otherwise look identical.
    render(<SelectionBar selectedCount={3} matchCount={40} pageCount={40} onClear={vi.fn()} />)

    expect(screen.getByText('3 selected')).toBeInTheDocument()
  })

  it('says that no selection means ALL matches', () => {
    // The whole point. A bar that said "0 selected" would imply an
    // action does nothing, which is the opposite of true.
    render(<SelectionBar selectedCount={0} matchCount={40} pageCount={40} onClear={vi.fn()} />)

    expect(screen.getByText(/actions apply to the 40 shown/i)).toBeInTheDocument()
  })

  it('warns when the selection exceeds the write ceiling', () => {
    // MAX_BULK_OBJECTS is 1000 in the write mediator. A person who has
    // selected 1,200 should learn that before filling in a form, not
    // after submitting one.
    render(<SelectionBar selectedCount={1200} matchCount={5000} pageCount={5000} onClear={vi.fn()} />)

    expect(screen.getByText(/over the 1000 limit/i)).toBeInTheDocument()
  })

  it('warns when NO selection puts the whole PAGE over the ceiling', () => {
    // The easier way to hit it: select nothing, and the action applies
    // to everything shown. A warning that only checked the explicit
    // selection would miss exactly the case nobody is thinking about.
    //
    // Measured against the PAGE rather than the match count -- an
    // action with no selection reaches only what is on screen, so
    // warning on matchCount alone would be a false alarm. The test
    // below with pageCount={20} is the other side of that.
    render(<SelectionBar selectedCount={0} matchCount={5000} pageCount={5000} onClear={vi.fn()} />)

    expect(screen.getByText(/over the 1000 limit/i)).toBeInTheDocument()
  })

  it('does not warn below the ceiling', () => {
    // THE CONTROL. A warning that always appeared would be ignored by
    // the time it mattered.
    render(<SelectionBar selectedCount={3} matchCount={40} pageCount={40} onClear={vi.fn()} />)

    expect(screen.queryByText(/limit/i)).toBeNull()
  })

  it('clears the selection', () => {
    const onClear = vi.fn()
    render(<SelectionBar selectedCount={3} matchCount={40} pageCount={40} onClear={onClear} />)

    fireEvent.click(screen.getByLabelText('Clear selection'))

    expect(onClear).toHaveBeenCalled()
  })

  it('offers no Clear when there is nothing to clear', () => {
    render(<SelectionBar selectedCount={0} matchCount={40} pageCount={40} onClear={vi.fn()} />)

    expect(screen.queryByLabelText('Clear selection')).toBeNull()
  })

  it('renders nothing when nothing matched', () => {
    // THE CONTROL on the other side. With no results there is no set
    // to describe, and a bar saying so would be noise.
    const { container } = render(<SelectionBar selectedCount={0} matchCount={0} pageCount={0} onClear={vi.fn()} />)

    expect(container.querySelector('.selection-bar')).toBeNull()
  })

  it('announces changes without stealing focus', () => {
    // aria-live="polite": the count changes as boxes are ticked, and a
    // screen-reader user needs to hear it without being interrupted
    // mid-word on every click.
    const { container } = render(<SelectionBar selectedCount={1} matchCount={40} pageCount={40} onClear={vi.fn()} />)

    expect(container.querySelector('.selection-bar')).toHaveAttribute('aria-live', 'polite')
  })
})

describe('paging, where the promise could quietly overstate', () => {
  /**
   * FOUND BY A HUMAN RUNNING THE PRODUCT, not by a test.
   *
   * The bar used to say "actions apply to all N matches" while the
   * form sent only the objects on the current PAGE. With everything on
   * one page they agree, which is why every test passed. Load a second
   * page and they diverge: the action touches fewer objects than the
   * person was just told, and nothing looks wrong afterwards.
   *
   * Foundry's select-all "selects all objects matching the applied
   * filters, not just the objects on the current page". We cannot
   * honour that half, so the PROMISE is narrowed rather than the
   * behaviour faked.
   */
  it('promises the page, not every match', () => {
    render(<SelectionBar selectedCount={0} matchCount={500} pageCount={20} onClear={vi.fn()} />)

    expect(screen.getByText(/actions apply to the 20 shown/i)).toBeInTheDocument()
    expect(screen.queryByText(/500 matches/)).toBeNull()
  })

  it('says how many are beyond the page', () => {
    // Invisible otherwise: the count says 20, the filter matched 500,
    // and nothing on screen connects the two.
    render(<SelectionBar selectedCount={0} matchCount={500} pageCount={20} onClear={vi.fn()} />)

    expect(screen.getByText(/480 more match the filter/i)).toBeInTheDocument()
  })

  it('says nothing about paging when everything is shown', () => {
    // THE CONTROL, and the common case. A note that always appeared
    // would be ignored by the time it mattered.
    render(<SelectionBar selectedCount={0} matchCount={4} pageCount={4} onClear={vi.fn()} />)

    expect(screen.queryByText(/more match the filter/i)).toBeNull()
  })

  it('an explicit selection is what it says, regardless of paging', () => {
    // Selected ids are held across pages, so the count is exact and
    // the page is irrelevant.
    render(<SelectionBar selectedCount={7} matchCount={500} pageCount={20} onClear={vi.fn()} />)

    expect(screen.getByText('7 selected')).toBeInTheDocument()
    expect(screen.queryByText(/more match the filter/i)).toBeNull()
  })

  it('the ceiling is measured against the page, not the match count', () => {
    // 5,000 match but 20 are shown: an action with no selection
    // reaches 20, which is nowhere near the limit. Warning here would
    // be a false alarm.
    render(<SelectionBar selectedCount={0} matchCount={5000} pageCount={20} onClear={vi.fn()} />)

    expect(screen.queryByText(/over the 1000 limit/i)).toBeNull()
  })
})
