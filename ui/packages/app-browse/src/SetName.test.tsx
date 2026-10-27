import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import SetName from './SetName'

/**
 * DEV_UI.md 11.1: "everything on screen IS a set, named by how it was
 * built (`Customer · 3 filters · 1,284`), so the interface always has a
 * subject and saving is a PROMOTION rather than a creation."
 */

describe('the set is named by how it was built', () => {
  it('says the type, the narrowing and the size', () => {
    const { container } = render(
      <MemoryRouter>
        <SetName objectType="Customer" filterCount={3} total={1284} />
      </MemoryRouter>,
    )

    expect(container.textContent).toContain('Customer')
    expect(container.textContent).toContain('3 filters')
    expect(container.textContent).toContain('1,284')
  })

  it('says nothing about filters when there are none', () => {
    /** An unfiltered set is "Customer · 1,284", not "Customer · 0
     *  filters · 1,284". Zero of something is noise. */
    const { container } = render(
      <MemoryRouter>
        <SetName objectType="Customer" filterCount={0} total={1284} />
      </MemoryRouter>,
    )

    expect(container.textContent).not.toContain('filter')
  })

  it('counts one filter in the singular', () => {
    render(
      <MemoryRouter>
        <SetName objectType="Customer" filterCount={1} total={9} />
      </MemoryRouter>,
    )

    expect(screen.getByText('1 filter')).toBeInTheDocument()
  })

  it('groups thousands, because the number is read not parsed', () => {
    const { container } = render(
      <MemoryRouter>
        <SetName objectType="Transaction" filterCount={0} total={1284} />
      </MemoryRouter>,
    )

    expect(container.textContent).toContain('1,284')
  })
})

describe('what it does while a search is in flight', () => {
  it('drops the count rather than showing a stale one', () => {
    /** The previous total is a lie the moment the filters change. The
     *  name keeps its shape and loses the number, which is honest and
     *  does not reflow the line. */
    const { container } = render(
      <MemoryRouter>
        <SetName objectType="Customer" filterCount={2} total={1284} loading />
      </MemoryRouter>,
    )

    expect(container.textContent).toContain('Customer')
    expect(container.textContent).toContain('2 filters')
    expect(container.textContent).not.toContain('1,284')
  })
})

describe('live sets say so', () => {
  it('names its kind on its face', () => {
    /** 11.3: every mature product ships live and frozen sets, and
     *  "whichever a person is looking at must say so on its face" --
     *  both failure modes are FAQ entries. Elysium has only live sets
     *  today; saying so leaves room for the other. */
    render(
      <MemoryRouter>
        <SetName objectType="Customer" filterCount={0} total={4} />
      </MemoryRouter>,
    )

    expect(screen.getByText('Live')).toBeInTheDocument()
  })
})

describe('before a type is chosen', () => {
  it('renders nothing rather than naming an empty set', () => {
    const { container } = render(
      <MemoryRouter>
        <SetName objectType={null} filterCount={0} total={0} />
      </MemoryRouter>,
    )

    expect(container.innerHTML).toBe('')
  })
})

describe('a frozen set is not "pending", and is not orange', () => {
  it('shows neutral with a snowflake: orange now means a type you can only see', () => {
    render(
      <MemoryRouter>
        <SetName objectType="Customer" filterCount={0} total={40} frozen="Bulk zero" />
      </MemoryRouter>,
    )
    const badge = screen.getByText('Frozen').closest('.bp6-tag') as HTMLElement

    expect(badge.className).not.toMatch(/bp6-intent-warning/)
    expect(badge.className).not.toMatch(/bp6-intent-primary/)
    expect(badge.querySelector('[data-icon="snowflake"]')).not.toBeNull()
  })
})

describe('a type that can be seen and not searched has no set to name', () => {
  it('says View only, in place of a count, a Live badge and the verbs that act on a set', () => {
    const { container } = render(
      <MemoryRouter>
        <SetName objectType="Account" filterCount={0} total={0} viewOnly actions={<button>Export</button>} />
      </MemoryRouter>,
    )

    expect(screen.getByText('View only')).toBeInTheDocument()
    // "0" would say the set is empty; the truth is that they may not see it.
    expect(container.textContent).not.toMatch(/0/)
    expect(screen.queryByText('Live')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Export' })).toBeNull()
    expect(screen.queryByText(/Ask about this set/)).toBeNull()
  })
})
