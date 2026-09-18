/**
 * One loading treatment, and it announces.
 *
 * THREE EXISTED across six components: `<p>Loading…</p>` in
 * ObjectDetailPanel, ObjectSearchPanel and AdminPanel; `<Spinner />`
 * in AsyncPanel and SchemaPanel; `<Spinner size={20} />` in
 * WriteDetail. ObjectDetailPanel's own comment claimed plain text was
 * "matching every other data-fetching component's own existing
 * convention" -- true when written, and no longer.
 *
 * NEITHER WAS RIGHT, which is why this is a new component rather than
 * a vote between them. A bare Spinner announces nothing: Blueprint
 * renders an svg, and an svg with no accessible name is invisible to
 * assistive technology. Plain text announces and shows no progress --
 * on hardware where a query runs for minutes, a motionless "Loading…"
 * reads as a hung page.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import LoadingState from './LoadingState'

describe('LoadingState', () => {
  it('announces itself to a screen reader', () => {
    // THE PROPERTY THE SPINNER SITES LACKED. Without an accessible
    // name a reader sits in silence, unable to tell a slow request
    // from a finished empty one.
    render(<LoadingState />)

    expect(screen.getByRole('status')).toHaveTextContent('Loading…')
  })

  it('takes a specific label when a page waits on more than one thing', () => {
    render(<LoadingState label="Loading the changes…" />)

    expect(screen.getByRole('status')).toHaveTextContent('Loading the changes…')
  })

  it('keeps the label out of sight but in the layout', () => {
    // display:none and visibility:hidden both remove an element from
    // the accessibility tree, so a label using either would announce
    // nothing -- the exact failure this component exists to avoid.
    render(<LoadingState />)

    const label = screen.getByText('Loading…')
    expect(label).toHaveClass('visually-hidden')
  })

  it('still renders something to look at', () => {
    // THE CONTROL. A component that satisfied the screen reader and
    // showed nothing would pass every test above while looking broken.
    const { container } = render(<LoadingState />)

    expect(container.querySelector('.bp6-spinner')).not.toBeNull()
  })
})
