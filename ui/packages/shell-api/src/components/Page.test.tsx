import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'

import Page from './Page'

describe('every screen opens the same way', () => {
  /**
   * Measured before writing this: of ten panels, three open with a
   * heading and seven with nothing, four have no wrapping element, and
   * the three with titles use an h2, an h3 and a div. That is why the
   * application reads as islands behind one rail.
   */

  it('gives the screen exactly one top-level heading', () => {
    render(
      <Page title="Identity review">
        <p>content</p>
      </Page>,
    )

    const headings = screen.getAllByRole('heading', { level: 1 })

    expect(headings).toHaveLength(1)
    expect(screen.getByRole('heading', { level: 1, name: 'Identity review' })).toBeInTheDocument()
  })

  it('carries a description when a screen needs to explain itself', () => {
    render(
      <Page title="Identity review" description="Pairs that may be one thing.">
        <p>content</p>
      </Page>,
    )

    expect(screen.getByText('Pairs that may be one thing.')).toBeInTheDocument()
  })

  it('omits the description entirely rather than leaving an empty line', () => {
    /** A screen with nothing useful to say should say nothing. An empty
     *  paragraph still takes its margin and reads as a loading fault. */
    const { container } = render(
      <Page title="Approvals">
        <p>content</p>
      </Page>,
    )

    expect(container.querySelector('.page__description')).toBeNull()
  })

  it('renders its content', () => {
    render(
      <Page title="Approvals">
        <p>the body</p>
      </Page>,
    )

    expect(screen.getByText('the body')).toBeInTheDocument()
  })
})

describe('one primary action, in one place', () => {
  /**
   * "If you have a primary action button, place it in the same
   * location on every screen." The slot is singular on purpose: a page
   * wanting two primary actions has not decided which one it is for.
   */

  it('puts the action in the header, beside the title', () => {
    const { container } = render(
      <Page title="Approvals" action={<button type="button">Approve all</button>}>
        <p>content</p>
      </Page>,
    )

    const head = container.querySelector('.page__head')
    expect(head?.contains(screen.getByRole('button', { name: 'Approve all' }))).toBe(true)
  })

  it('leaves no empty slot when a screen has no primary action', () => {
    const { container } = render(
      <Page title="Notifications">
        <p>content</p>
      </Page>,
    )

    expect(container.querySelector('.page__action')).toBeNull()
  })
})
