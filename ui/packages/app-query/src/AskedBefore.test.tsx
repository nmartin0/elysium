import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

import AskedBefore from './AskedBefore'

describe('what was asked before', () => {
  it("lists this session's questions", () => {
    render(<AskedBefore questions={['first', 'second']} onPick={vi.fn()} />)

    expect(screen.getByRole('button', { name: 'first' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'second' })).toBeTruthy()
  })

  it('puts a question back in the box to edit or re-run', () => {
    const onPick = vi.fn()
    render(<AskedBefore questions={['what changed?']} onPick={onPick} />)

    fireEvent.click(screen.getByRole('button', { name: 'what changed?' }))

    expect(onPick).toHaveBeenCalledWith('what changed?')
  })

  it('shows nothing before anything has been asked', () => {
    const { container } = render(<AskedBefore questions={[]} onPick={vi.fn()} />)

    expect(container.innerHTML).toBe('')
  })

  it('is an ordered list, because the order is the point', () => {
    /** Newest first. A set of questions with no order tells you what
     *  you asked but not what you asked last. */
    const { container } = render(<AskedBefore questions={['a', 'b']} onPick={vi.fn()} />)

    expect(container.querySelector('ol')).toBeTruthy()
  })
})
