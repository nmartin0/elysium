import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import AskAboutObject from './AskAboutObject'

/**
 * DEV_UI.md section 5 item 4, "THE AGENT EVERYWHERE", on the half that
 * did not have it. Item 3 is why this page in particular: a hub you
 * have to leave in order to ask a question about what is in it is not
 * one.
 */

const show = (props: Parameters<typeof AskAboutObject>[0]) =>
  render(
    <MemoryRouter>
      <AskAboutObject {...props} />
    </MemoryRouter>,
  )

const href = () => decodeURIComponent(screen.getByRole('link').getAttribute('href') ?? '')

/** The seeded text alone. Reading the whole href instead made "not a
 *  question" pass on the `?` in `/query?` -- the test asserted about
 *  the URL's own punctuation, not the sentence. */
const subject = () => new URLSearchParams(screen.getByRole('link').getAttribute('href')?.split('?')[1] ?? '').get('q')

describe('handing the agent the object on screen', () => {
  it('links to the agent with the object named', () => {
    show({ objectType: 'Customer', objectId: 'cust_001' })

    const link = screen.getByRole('link', { name: 'Ask about this object' })

    expect(link.getAttribute('href')).toContain('/query?q=')
    expect(href()).toContain('Customer object cust_001')
  })

  it('seeds a subject and not a question', () => {
    /** A guessed question that reads plausibly is worse than an empty
     *  box, because somebody presses Ask on it. The phrase ends where
     *  the person starts typing. */
    show({ objectType: 'Customer', objectId: 'cust_001' })

    expect(subject()).toMatch(/: $/)
    expect(subject()).not.toContain('?')
  })

  it('escapes an id that would otherwise break the link', () => {
    show({ objectType: 'Customer', objectId: 'a&b=c' })

    // Read raw, not decoded: the point is what is in the attribute.
    expect(screen.getByRole('link').getAttribute('href')).not.toContain('&b=')
  })
})

describe('what the subject must not carry', () => {
  /**
   * THE ONE REAL DECISION IN THIS COMPONENT. The natural sentence names
   * the object the way the page does -- "the Customer cust_001 (Ada
   * Okafor)" -- and that phrase travels in a URL somebody can paste
   * into a chat. A reader without the grant would learn from the link
   * alone that cust_001 is Ada Okafor, which is precisely the
   * inference the field table refuses when it renders "Not permitted"
   * rather than a value.
   *
   * `AskAboutSet` already follows the same rule for the same reason:
   * it carries the COUNT of filters, never the filter values.
   *
   * The component is not given a title at all, so this is enforced by
   * its signature rather than by its body -- and that is the point. A
   * test that a value cannot appear is weak when the value was never
   * in scope; what this one actually guards is somebody later ADDING
   * the title prop, with this comment in front of them.
   */
  it('takes only a type and an id, so a field value cannot reach the URL', () => {
    show({ objectType: 'Customer', objectId: 'cust_001' })

    expect(href()).toBe('/query?q=About the Customer object cust_001: ')
  })
})
