import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'

import TraceSummary from './TraceSummary'

const served = { rbac_allowed: true, mac_allowed: true }
const rbacRefused = { rbac_allowed: false, mac_allowed: true }
const macRefused = { rbac_allowed: true, mac_allowed: false }

describe('counting what happened', () => {
  it('reports how many reads were served', () => {
    render(<TraceSummary entries={[served, served]} />)

    expect(screen.getByText('2 served')).toBeTruthy()
  })

  it('counts an RBAC refusal as refused', () => {
    render(<TraceSummary entries={[served, rbacRefused]} />)

    expect(screen.getByText('1 refused')).toBeTruthy()
    expect(screen.getByText('1 served')).toBeTruthy()
  })

  it('counts a MAC refusal as refused', () => {
    render(<TraceSummary entries={[macRefused]} />)

    expect(screen.getByText('1 refused')).toBeTruthy()
  })

  it('treats an unknown MAC decision as served rather than refused', () => {
    /** `mac_allowed` is null where no compartment applied. Counting
     *  null as a refusal would inflate the figure and teach a reader
     *  to distrust a number that is mostly noise. */
    render(<TraceSummary entries={[{ rbac_allowed: true, mac_allowed: null }]} />)

    expect(screen.getByText('1 served')).toBeTruthy()
    expect(screen.queryByText(/refused/)).toBeNull()
  })
})

describe('what it says about a refusal', () => {
  it('frames one as normal rather than as a failure', () => {
    /** The product's distinctive behaviour arrives as an absence. A
     *  reader who does not know that reads a refusal as a bug. */
    render(<TraceSummary entries={[served, rbacRefused]} />)

    expect(screen.getByText(/A refusal is a normal answer/)).toBeTruthy()
  })

  it('says so plainly when nothing was refused', () => {
    render(<TraceSummary entries={[served]} />)

    expect(screen.getByText(/Every field this answer needed/)).toBeTruthy()
    expect(screen.queryByText(/A refusal is a normal answer/)).toBeNull()
  })
})

describe('nothing to summarise', () => {
  it('renders nothing for an empty trace', () => {
    /** An empty trace is what the route returns for somebody else's
     *  request -- uniform denial rather than a 403. A summary saying
     *  "0 served" would turn that silence into a signal. */
    const { container } = render(<TraceSummary entries={[]} />)

    expect(container.innerHTML).toBe('')
  })
})
