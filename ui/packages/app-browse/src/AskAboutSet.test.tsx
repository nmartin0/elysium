import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import AskAboutSet from './AskAboutSet'

/**
 * DEV_UI.md section 4's symptom: "the agent lives in its own app, so a
 * question about what you are looking at means starting again in
 * another tab, describing in words what was already on screen."
 */

const show = (props: Parameters<typeof AskAboutSet>[0]) =>
  render(
    <MemoryRouter>
      <AskAboutSet {...props} />
    </MemoryRouter>,
  )

describe('handing the agent what is on screen', () => {
  it('links to the agent with the set described', () => {
    show({ objectType: 'Customer', filterCount: 3, total: 1284 })

    const link = screen.getByRole('link', { name: 'Ask about this set' })

    expect(link.getAttribute('href')).toContain('/query?q=')
    expect(decodeURIComponent(link.getAttribute('href') ?? '')).toContain('1,284 Customer objects matching 3 filters')
  })

  it('says nothing about filters when the set has none', () => {
    show({ objectType: 'Customer', filterCount: 0, total: 4 })

    const href = decodeURIComponent(screen.getByRole('link').getAttribute('href') ?? '')

    expect(href).toContain('4 Customer objects')
    expect(href).not.toContain('filter')
  })

  it('seeds a subject and not a question', () => {
    /** The person knows what they want to ask and the interface does
     *  not. A guessed question that reads plausibly is worse than an
     *  empty box, because somebody presses Ask on it. */
    show({ objectType: 'Customer', filterCount: 0, total: 4 })

    const href = decodeURIComponent(screen.getByRole('link').getAttribute('href') ?? '')

    const seed = href.slice(href.indexOf('q=') + 2)

    expect(seed).not.toContain('?')
    expect(seed.endsWith(': ')).toBe(true)
  })

  it('encodes the subject, so a set description cannot break the link', () => {
    show({ objectType: 'Customer & Co', filterCount: 1, total: 2 })

    const href = screen.getByRole('link').getAttribute('href') ?? ''

    expect(href).not.toContain('&amp;')
    expect(href).toContain('%26')
  })

  it('renders nothing before a type is chosen', () => {
    const { container } = show({ objectType: null, filterCount: 0, total: 0 })

    expect(container.innerHTML).toBe('')
  })
})
