import { describe, it, expect, vi } from 'vitest'
import { act, render, screen } from '@testing-library/react'

import { REVEAL_DELAY_MS } from '../useSettledSpinner'
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

    expect(container.querySelector('.bp6-spinner')).toBeNull()
    expect(screen.queryByText('content')).not.toBeInTheDocument()
  })

  it('shows a spinner once the wait is long enough to need one', async () => {
    vi.useFakeTimers()
    try {
      const { container } = render(
        <AsyncPanel error={null} data={null}>
          {() => <p>content</p>}
        </AsyncPanel>,
      )

      await act(async () => {
        vi.advanceTimersByTime(REVEAL_DELAY_MS)
      })

      expect(container.querySelector('.bp6-spinner')).not.toBeNull()
    } finally {
      vi.useRealTimers()
    }
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

    expect(container.querySelector('.bp6-spinner')).toBeNull()
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
