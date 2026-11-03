import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

const getRequestTrace = vi.fn()

vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return { ...actual, getRequestTrace: () => getRequestTrace() }
})

const { default: AnswerTrace } = await import('./AnswerTrace')

const props = { requestId: 'req-1', onSessionExpired: () => {} }

beforeEach(() => {
  vi.clearAllMocks()
  getRequestTrace.mockResolvedValue([
    {
      object_type: 'Customer',
      object_id: 'c1',
      action: 'read',
      timestamp: '2026-09-09T10:00:00Z',
    },
  ])
})

describe('AnswerTrace', () => {
  it('fetches nothing until asked', () => {
    /**
     * A trace is read rarely and costs a log scan. Fetching one for
     * every answer would make the common case pay for the uncommon
     * one.
     */
    render(<AnswerTrace {...props} />)

    expect(getRequestTrace).not.toHaveBeenCalled()
  })

  it('shows what was read on opening', async () => {
    render(<AnswerTrace {...props} />)

    fireEvent.click(screen.getByRole('button', { name: /Every field it read/ }))

    expect(await screen.findByText('Customer')).toBeInTheDocument()
    expect(screen.getByText('c1')).toBeInTheDocument()
  })

  it('has no column for a refusal, because the trace holds none', async () => {
    /**
     * The route returns what was GRANTED and nothing else: a refusal in
     * any form would show a caller which of their guesses touched
     * something hidden from them. So there is no "Allowed" column and
     * no "refused" tag to render.
     */
    render(<AnswerTrace {...props} />)

    fireEvent.click(screen.getByRole('button', { name: /Every field it read/ }))

    await screen.findByText('Customer')
    expect(screen.queryByText('Allowed')).toBeNull()
    expect(screen.queryByText('refused')).toBeNull()
  })

  it('does not refetch when closed and reopened', async () => {
    render(<AnswerTrace {...props} />)
    const button = screen.getByRole('button', { name: /Every field it read/ })

    fireEvent.click(button)
    await screen.findByText('Customer')
    fireEvent.click(button)
    fireEvent.click(button)

    expect(getRequestTrace).toHaveBeenCalledTimes(1)
  })

  it('says so when a trace is empty', async () => {
    // Legitimately possible: an answer needing no object read, or one
    // whose entries fell outside the log scan's window.
    getRequestTrace.mockResolvedValue([])
    render(<AnswerTrace {...props} />)

    fireEvent.click(screen.getByRole('button', { name: /Every field it read/ }))

    expect(await screen.findByText(/No object reads were recorded/)).toBeInTheDocument()
  })

  it('reports a failure rather than staying blank', async () => {
    getRequestTrace.mockRejectedValue(new Error('trace unavailable'))
    render(<AnswerTrace {...props} />)

    fireEvent.click(screen.getByRole('button', { name: /Every field it read/ }))

    expect(await screen.findByText(/trace unavailable/)).toBeInTheDocument()
  })
})
