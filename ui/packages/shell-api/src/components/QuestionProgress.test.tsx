import { describe, expect, it, vi, afterEach } from 'vitest'
import { act, fireEvent, render, screen } from '@testing-library/react'

import QuestionProgress, { elapsed } from './QuestionProgress'

afterEach(() => {
  vi.useRealTimers()
})

describe('a question in progress (19 October)', () => {
  it('the steps done so far, in order, announced politely', () => {
    render(
      <QuestionProgress
        progress={{ lines: ['Found 1 Customer', 'Read Email of Ada'], answering: false }}
        startedAt={Date.now()}
        onStop={() => {}}
      />,
    )

    const steps = screen.getAllByRole('listitem').map((item) => item.textContent)
    expect(steps).toEqual(['Found 1 Customer', 'Read Email of Ada'])
    expect(screen.getByRole('list').getAttribute('aria-live')).toBe('polite')
    expect(screen.getByText(/Working on it/)).toBeInTheDocument()
  })

  it('says so before the first step, and when the answer is being written', () => {
    const { rerender } = render(<QuestionProgress progress={null} startedAt={Date.now()} onStop={() => {}} />)
    expect(screen.getByText('Choosing the first step…')).toBeInTheDocument()

    rerender(
      <QuestionProgress
        progress={{ lines: ['Found 1 Customer'], answering: true }}
        startedAt={Date.now()}
        onStop={() => {}}
      />,
    )
    expect(screen.getByText(/Writing the answer/)).toBeInTheDocument()
    expect(screen.queryByText('Choosing the first step…')).toBeNull()
  })

  it('how long it has been, every second', () => {
    vi.useFakeTimers()
    const started = Date.now()
    render(<QuestionProgress progress={null} startedAt={started} onStop={() => {}} />)
    expect(screen.getByText('0:00')).toBeInTheDocument()

    act(() => {
      vi.advanceTimersByTime(72_000)
    })

    expect(screen.getByText('1:12')).toBeInTheDocument()
  })

  it('Stop stops it', () => {
    const onStop = vi.fn()
    render(<QuestionProgress progress={null} startedAt={Date.now()} onStop={onStop} />)

    fireEvent.click(screen.getByRole('button', { name: 'Stop' }))

    expect(onStop).toHaveBeenCalledTimes(1)
  })

  it('elapsed time as minutes and seconds', () => {
    expect([elapsed(0), elapsed(9_999), elapsed(61_000), elapsed(-5)]).toEqual(['0:00', '0:09', '1:01', '0:00'])
  })
})
