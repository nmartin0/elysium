/**
 * View state lives in the URL; preferences do not.
 *
 * A VIEW is what you are looking at -- the object type, the search,
 * the sort, the chart filters, which tab. Someone wants to send it to
 * a colleague or find it again in history. It is a property of the
 * QUESTION rather than of the person asking.
 *
 * A PREFERENCE is how you like things shown. It follows you across
 * every view, and a shared link that changed the recipient's columns
 * would be a surprise rather than a convenience.
 */

import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, useSearchParams } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { useClearUrlKeys, useUrlJson, useUrlValue } from './useUrlState'

function Harness() {
  const [type, setType] = useUrlValue('type', '')
  const [filters, setFilters] = useUrlJson<string[]>('filters', [])
  const clearKeys = useClearUrlKeys()
  const [params] = useSearchParams()

  return (
    <div>
      <span data-testid="type">{type}</span>
      <span data-testid="filters">{JSON.stringify(filters)}</span>
      <span data-testid="query">{params.toString()}</span>
      <button onClick={() => setType('Customer')}>set type</button>
      <button onClick={() => setType('')}>clear type</button>
      <button onClick={() => setFilters(['a'])}>set filters</button>
      <button onClick={() => setFilters((current) => [...current, 'b'])}>append</button>
      <button onClick={() => clearKeys(['type', 'filters'])}>clear both</button>
    </div>
  )
}

function renderAt(initial: string) {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <Harness />
    </MemoryRouter>,
  )
}

describe('useUrlState', () => {
  it('reads a value out of the query string', () => {
    renderAt('/?type=Customer')

    expect(screen.getByTestId('type')).toHaveTextContent('Customer')
  })

  it('writes a value into it', () => {
    renderAt('/')

    fireEvent.click(screen.getByText('set type'))

    expect(screen.getByTestId('query')).toHaveTextContent('type=Customer')
  })

  it('removes the key rather than writing an empty one', () => {
    // `?type=` in a shared link is noise meaning the same as no type
    // at all, and a URL someone pastes into a message should carry
    // only what it needs.
    renderAt('/?type=Customer')

    fireEvent.click(screen.getByText('clear type'))

    expect(screen.getByTestId('query')).not.toHaveTextContent('type')
  })

  it('falls back when the encoded value is malformed', () => {
    // Query strings are edited by hand, truncated by chat clients and
    // mangled by link previewers. A view that refuses to load because
    // someone's mail client ate a bracket is worse than one that opens
    // unfiltered.
    renderAt('/?filters=%7Bnot-json')

    expect(screen.getByTestId('filters')).toHaveTextContent('[]')
  })

  it('supports the updater form, reading the current value', () => {
    // Browse's cross-filter toggles one entry of a list. Closing over
    // a captured array would drop a click made before the previous
    // render committed.
    renderAt('/?filters=%5B%22a%22%5D')

    fireEvent.click(screen.getByText('append'))

    expect(screen.getByTestId('filters')).toHaveTextContent('["a","b"]')
  })

  it('clears several keys in ONE navigation', () => {
    /** THE FLAW THAT NEARLY SHIPPED.
     *
     * Each useUrlValue has its own useSearchParams, and
     * setSearchParams NAVIGATES rather than queueing like setState. So
     * two setters called in one handler issue two navigations from the
     * same starting params, and the second discards the first.
     *
     * Found by an existing test -- Browse's "clear filters" button
     * reset the search text and the chart filters, and after this move
     * only one cleared. The button looked like it half worked.
     */
    renderAt('/?type=Customer&filters=%5B%22a%22%5D')

    fireEvent.click(screen.getByText('clear both'))

    expect(screen.getByTestId('query')).toHaveTextContent('')
    expect(screen.getByTestId('type')).toHaveTextContent('')
    expect(screen.getByTestId('filters')).toHaveTextContent('[]')
  })

  it('leaves other keys alone when clearing', () => {
    // THE CONTROL. A clear that wiped the whole query string would
    // pass the test above while discarding state it was never asked
    // about -- the sort, the tab, anything a future caller adds.
    render(
      <MemoryRouter initialEntries={['/?type=Customer&sort=name&view=charts']}>
        <Harness />
      </MemoryRouter>,
    )

    fireEvent.click(screen.getByText('clear both'))

    expect(screen.getByTestId('query')).toHaveTextContent('sort=name')
    expect(screen.getByTestId('query')).toHaveTextContent('view=charts')
  })
})
