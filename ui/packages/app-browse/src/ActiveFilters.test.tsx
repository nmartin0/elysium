/**
 * What is narrowing this view, said out loud.
 *
 * THE DEFECT THIS FIXES. A cross-filter was applied and rendered
 * nowhere in table view. Arriving from a link, the panel said "Showing
 * 2 of 2 matches" with no indication a filter was in force -- which
 * reads as "there are 2 transactions in the system". A UI stating
 * something false is worse than one stating nothing.
 *
 * FOUNDRY TREATS THIS AS FIRST-CLASS: Object Views ships a dedicated
 * "Active Filters" widget for a summary of all filters currently
 * applied, and Workshop ships "Exploration Filter Pills". A pill row
 * is the established idiom rather than an invention.
 */

import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import ActiveFilters from './ActiveFilters'

describe('ActiveFilters', () => {
  it('says which field is filtering and to what', () => {
    render(
      <ActiveFilters filters={[{ field: 'customer_id', values: ['cust_001'], mode: 'keep' }]} onRemove={vi.fn()} />,
    )

    expect(screen.getByText(/Customer id/)).toBeInTheDocument()
    expect(screen.getByText(/cust_001/)).toBeInTheDocument()
  })

  it('distinguishes exclude from keep', () => {
    // A pill reading "Customer: Ada" for an EXCLUDE filter would
    // describe the exact opposite of the rows on screen.
    render(<ActiveFilters filters={[{ field: 'category', values: ['refund'], mode: 'exclude' }]} onRemove={vi.fn()} />)

    expect(screen.getByText(/is not/)).toBeInTheDocument()
  })

  it('removes one filter by field', () => {
    // REMOVAL IS THE WAY BACK, which is Foundry's answer to "how did I
    // get here" too -- their Exploration Search Bar has explicit
    // remove-only modes, and Object Explorer offers no breadcrumb
    // trail for search-around.
    const onRemove = vi.fn()
    render(
      <ActiveFilters filters={[{ field: 'customer_id', values: ['cust_001'], mode: 'keep' }]} onRemove={onRemove} />,
    )

    fireEvent.click(screen.getByRole('button'))

    expect(onRemove).toHaveBeenCalledWith('customer_id')
  })

  it('counts rather than listing when there are many values', () => {
    // Beyond two, a pill grows past what a glance can take in.
    render(
      <ActiveFilters
        filters={[{ field: 'category', values: ['a', 'b', 'c', 'd'], mode: 'keep' }]}
        onRemove={vi.fn()}
      />,
    )

    expect(screen.getByText(/4 values/)).toBeInTheDocument()
  })

  it('renders nothing at all when nothing is filtering', () => {
    // THE CONTROL. An empty row would occupy space to say "no", and
    // the absence already says it -- but a component that rendered
    // nothing ALWAYS would pass every test above.
    const { container } = render(<ActiveFilters filters={[]} onRemove={vi.fn()} />)

    expect(container.querySelector('.active-filters')).toBeNull()
  })
})
