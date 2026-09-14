/**
 * An error announces itself.
 *
 * THE TREATMENT WAS ALREADY CONSISTENT -- ten components rendered
 * `<Callout intent="danger">` and nine were byte-identical, so unlike
 * the loading states there was nothing to reconcile. This exists for
 * the thing none of them did.
 *
 * A DANGER CALLOUT SETS NO ARIA ROLE. Verified against the built
 * Blueprint package, not assumed. So an error appearing after an
 * action was invisible to a screen reader: someone submits a write, it
 * is rejected, and they hear the same silence as success.
 *
 * Worse than a missing label on a spinner, because a spinner resolves
 * and a failure just sits there.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import ErrorState from './ErrorState'

describe('ErrorState', () => {
  it('announces immediately, interrupting what is being read', () => {
    // role="alert" rather than "status". An alert interrupts; a status
    // waits its turn. Errors earn that and progress does not, which is
    // why LoadingState uses "status" and this does not.
    render(<ErrorState>Could not reach the server.</ErrorState>)

    expect(screen.getByRole('alert')).toHaveTextContent('Could not reach the server.')
  })

  it('keeps the wording it was given', () => {
    // The API returns real messages for caller mistakes -- an unknown
    // aggregate names the valid ones -- and the person who most needs
    // that detail is the one who just made the mistake.
    render(<ErrorState>Unknown aggregate 'median' -- valid: count, sum, avg</ErrorState>)

    expect(screen.getByRole('alert')).toHaveTextContent(/valid: count, sum, avg/)
  })

  it('takes a title for a summary of several failures', () => {
    // Silos uses one; a single message should not.
    render(<ErrorState title="Some silos are not answering">two of four</ErrorState>)

    expect(screen.getByText('Some silos are not answering')).toBeInTheDocument()
  })

  it('still looks like an error', () => {
    // THE CONTROL. A component that announced correctly and rendered
    // as ordinary text would pass every test above while removing the
    // visual signal every sighted user relies on.
    const { container } = render(<ErrorState>failed</ErrorState>)

    expect(container.querySelector('.bp6-intent-danger')).not.toBeNull()
  })
})
