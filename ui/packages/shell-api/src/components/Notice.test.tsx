import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'

import Notice from './Notice'

const calloutFor = (text: string) => {
  const element = screen.getByText(text).closest('.bp6-callout')
  if (!element) throw new Error(`no callout around ${text}`)
  return element
}

describe('the house default', () => {
  it('is neutral without being asked, which eleven of eighteen were', () => {
    render(<Notice>Nothing to show yet.</Notice>)
    const callout = calloutFor('Nothing to show yet.')

    for (const intent of ['primary', 'success', 'warning', 'danger']) {
      expect(callout.className).not.toContain(`bp6-intent-${intent}`)
    }
  })
})

describe("states share StatusTag's vocabulary", () => {
  /** Learned once, true everywhere: `pending` means the same thing on
   *  a tag and on a callout. */
  it.each([
    ['pending', 'warning'],
    ['active', 'primary'],
    ['granted', 'success'],
  ] as const)('%s is %s', (state, intent) => {
    render(<Notice state={state}>Message</Notice>)

    expect(calloutFor('Message').className).toContain(`bp6-intent-${intent}`)
  })
})

describe('what it deliberately will not do', () => {
  it('has no danger state, because ErrorState owns that', () => {
    /** A danger callout carries role="alert" and interrupts a screen
     *  reader. A notice must not be able to do that by accident. */
    render(<Notice state="pending">Message</Notice>)

    expect(calloutFor('Message').getAttribute('role')).not.toBe('alert')
  })
})
