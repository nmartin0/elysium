import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import Workspace, { WorkspaceFilter } from './Workspace'

/**
 * The two-pane layout, as a component rather than three CSS class
 * names nested by hand.
 *
 * Browse built it from `workspace`, `workspace__config` and
 * `workspace__content` directly, which meant the structure was
 * remembered rather than enforced -- get the nesting wrong and the
 * panes silently stop filling the shell and stop scrolling, with
 * nothing to say so.
 */

describe('Workspace', () => {
  it('puts configuration beside content, in that order', () => {
    // Order is the F-shaped hierarchy: scan the top, then down the
    // left. Content first would invert it.
    render(<Workspace config={<p>filters</p>}><p>results</p></Workspace>)

    const wrapper = document.querySelector('.workspace')
    const [first, second] = [...(wrapper?.children ?? [])]

    expect(first?.className).toContain('workspace__config')
    expect(second?.className).toContain('workspace__content')
  })

  it('labels the configuration pane so it can be skipped', () => {
    // aside, named: it is complementary to the content, and a screen
    // reader user should be able to jump past it.
    render(<Workspace config={<p>filters</p>}><p>results</p></Workspace>)

    expect(screen.getByRole('complementary', { name: 'Filters and options' }))
      .toBeInTheDocument()
  })

  it('renders a single pane when there is nothing to configure', () => {
    /**
     * Not every sub-app wants two panes, and none is forced to. Query
     * is a prompt and an answer; a configuration column would be an
     * empty box.
     */
    render(<Workspace><p>results</p></Workspace>)

    expect(document.querySelector('.workspace__config')).toBeNull()
    expect(document.querySelector('.workspace--single')).not.toBeNull()
  })

  it('still claims the canvas when single-paned', () => {
    // The stylesheet keys `main`'s padding off a workspace being
    // present. A single-pane variant that did not announce itself
    // would get the canvas padding AND its own, doubling it.
    render(<Workspace><p>results</p></Workspace>)

    const single = document.querySelector('.workspace--single')

    expect(single?.className).toContain('workspace__content')
  })
})

describe('WorkspaceFilter', () => {
  it('ties the label to its control', () => {
    render(
      <WorkspaceFilter label="Region" htmlFor="region">
        <select id="region"><option>us-west</option></select>
      </WorkspaceFilter>,
    )

    expect(screen.getByLabelText('Region')).toBeInTheDocument()
  })

  it('works without an id, for controls that are not form fields', () => {
    // A column picker is a group of checkboxes, not one input -- there
    // is nothing for htmlFor to point at.
    render(<WorkspaceFilter label="Columns"><p>boxes</p></WorkspaceFilter>)

    expect(screen.getByText('Columns')).toBeInTheDocument()
  })
})
