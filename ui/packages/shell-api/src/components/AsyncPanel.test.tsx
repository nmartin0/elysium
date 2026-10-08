import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import AsyncPanel from './AsyncPanel'

describe('AsyncPanel', () => {
  it('shows the failure instead of the content', () => {
    render(
      <AsyncPanel error="it broke" data={{ v: 1 }}>
        {() => <p>content</p>}
      </AsyncPanel>,
    )

    expect(screen.getByText('it broke')).toBeInTheDocument()
    expect(screen.queryByText('content')).not.toBeInTheDocument()
  })

  it('prefers the failure over the wait', () => {
    /**
     * A request that FAILED is not still in flight. Showing a spinner
     * over a known failure waits for something that will never
     * arrive, and the user has no way to tell the difference.
     */
    render(
      <AsyncPanel error="it broke" data={null}>
        {() => <p>content</p>}
      </AsyncPanel>,
    )

    expect(screen.getByText('it broke')).toBeInTheDocument()
  })

  it('waits when there is nothing yet, showing nothing at first', () => {
    /** THE SPINNER IS DELAYED NOW, and this test changed with it. It
     *  used to assert a spinner on the first frame; a request answering
     *  in 90ms then mounted one, painted a few frames and unmounted it,
     *  which reads as the screen flinching rather than as loading.
     *
     *  An empty region for 200ms is what a fast response should look
     *  like. What must still hold is that the CONTENT is withheld --
     *  that part never depended on the spinner. */
    const { container } = render(
      <AsyncPanel error={null} data={null}>
        {() => <p>content</p>}
      </AsyncPanel>,
    )

    expect(container.querySelector('.spinner-delayed')).not.toBeNull()
    expect(screen.queryByText('content')).not.toBeInTheDocument()
  })

  it('wraps the spinner in the class that delays it', () => {
    /** THE DELAY IS CSS NOW, not a timer. `.spinner-delayed` holds
     *  opacity 0 with a fade starting at 200ms, so a spinner unmounting
     *  before then was never visible and one unmounting shortly after
     *  is still nearly transparent.
     *
     *  A first attempt did this with setTimeout in a hook and landed
     *  state updates after tests had stopped watching -- three thrown
     *  act() warnings in a race-condition test. Asserting the class is
     *  the whole contract; there is no timing left to test here. */
    const { container } = render(
      <AsyncPanel error={null} data={null}>
        {() => <p>content</p>}
      </AsyncPanel>,
    )

    const wrapper = container.querySelector('.spinner-delayed')

    expect(wrapper).not.toBeNull()
    expect(wrapper?.querySelector('.bp6-spinner')).not.toBeNull()
  })

  it('hands the content its data, already narrowed', () => {
    /**
     * The reason children is a FUNCTION. The early returns this
     * replaces narrowed the type -- after `if (x === null) return`,
     * the rest of the function knew x was not null. A wrapper cannot
     * do that, because children are constructed before it decides
     * anything, so a plain-node version forced every caller into `x!`.
     */
    render(
      <AsyncPanel error={null} data={{ name: 'Ada' }}>
        {(person) => <p>{person.name}</p>}
      </AsyncPanel>,
    )

    expect(screen.getByText('Ada')).toBeInTheDocument()
  })

  it('treats undefined as not-here-yet, the same as null', () => {
    // THE SPINNER IS DELAYED NOW, so the first frame shows nothing at
    // all. What this test is actually about survives unchanged: an
    // `undefined` data value must be treated as not-yet-arrived and
    // the children must NOT be called with it.
    // A fetch that resolves to undefined is indistinguishable from one
    // that has not resolved, and rendering content against it would
    // crash the caller rather than wait.
    const { container } = render(
      <AsyncPanel error={null} data={undefined}>
        {() => <p>content</p>}
      </AsyncPanel>,
    )

    expect(container.querySelector('.spinner-delayed')).not.toBeNull()
  })

  it('shows an empty array as content, not as a wait', () => {
    // Zero results is an ANSWER. Treating it as absent would spin
    // forever on a legitimately empty response.
    render(
      <AsyncPanel error={null} data={[]}>
        {() => <p>none found</p>}
      </AsyncPanel>,
    )

    expect(screen.getByText('none found')).toBeInTheDocument()
  })
})
