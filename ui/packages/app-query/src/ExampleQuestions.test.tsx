import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

import ExampleQuestions from './ExampleQuestions'

describe('an empty query box', () => {
  it('offers the questions a deployment chose to show', () => {
    render(<ExampleQuestions questions={['Which customers are in us-east?']} onPick={vi.fn()} />)

    expect(screen.getByRole('button', { name: 'Which customers are in us-east?' })).toBeTruthy()
  })

  it('fills the box rather than asking the question', () => {
    /** The person decides when to ask. An example that submitted itself
     *  would spend somebody's model budget on a question they were only
     *  reading. */
    const onPick = vi.fn()
    render(<ExampleQuestions questions={['How many transactions?']} onPick={onPick} />)

    fireEvent.click(screen.getByRole('button', { name: 'How many transactions?' }))

    expect(onPick).toHaveBeenCalledWith('How many transactions?')
  })

  it('renders nothing at all when a deployment shows none', () => {
    /** A panel announcing an empty list is worse than one that stays
     *  quiet -- the feature is optional. */
    const { container } = render(<ExampleQuestions questions={[]} onPick={vi.fn()} />)

    expect(container.innerHTML).toBe('')
  })
})
