import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'

import TraceSummary from './TraceSummary'

describe('counting what happened', () => {
  it('reports how many reads were served', () => {
    render(<TraceSummary count={2} />)

    expect(screen.getByText('2 served')).toBeTruthy()
  })

  it('says only granted reads are listed, and says nothing about refusals', () => {
    /** The trace no longer carries a refusal in any form: listing one
     *  would show a caller which of their guesses touched something
     *  hidden from them. The summary must not hint at a number either. */
    render(<TraceSummary count={1} />)

    expect(screen.getByText(/Only the reads you were granted are listed/)).toBeTruthy()
    expect(screen.queryByText(/refused/)).toBeNull()
  })
})

describe('nothing to summarise', () => {
  it('renders nothing for an empty trace', () => {
    /** An empty trace is what the route returns for somebody else's
     *  request -- uniform denial rather than a 403. A summary saying
     *  "0 served" would turn that silence into a signal. */
    const { container } = render(<TraceSummary count={0} />)

    expect(container.innerHTML).toBe('')
  })
})
