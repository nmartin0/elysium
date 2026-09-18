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
      rbac_allowed: true,
      mac_allowed: true,
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

    fireEvent.click(screen.getByRole('button', { name: /How this answer/ }))

    expect(await screen.findByText('Customer')).toBeInTheDocument()
    expect(screen.getByText('c1')).toBeInTheDocument()
  })

  it('marks a REFUSED read rather than hiding it', async () => {
    /**
     * The interesting row. It says the agent tried to look at
     * something and was refused -- which is the authorization working,
     * and exactly what someone auditing wants to see rather than have
     * hidden.
     */
    getRequestTrace.mockResolvedValue([
      {
        object_type: 'Customer',
        object_id: 'c9',
        action: 'read',
        rbac_allowed: false,
        mac_allowed: null,
        timestamp: '2026-09-09T10:00:00Z',
      },
    ])
    render(<AnswerTrace {...props} />)

    fireEvent.click(screen.getByRole('button', { name: /How this answer/ }))

    expect(await screen.findByText('refused')).toBeInTheDocument()
  })

  it('treats a MAC denial as refused too', async () => {
    // rbac_allowed true and mac_allowed false is a real combination:
    // the role permits the field, the security value does not permit
    // the row. Showing it as allowed would be wrong.
    getRequestTrace.mockResolvedValue([
      {
        object_type: 'Customer',
        object_id: 'c9',
        action: 'read',
        rbac_allowed: true,
        mac_allowed: false,
        timestamp: '2026-09-09T10:00:00Z',
      },
    ])
    render(<AnswerTrace {...props} />)

    fireEvent.click(screen.getByRole('button', { name: /How this answer/ }))

    expect(await screen.findByText('refused')).toBeInTheDocument()
  })

  it('does not refetch when closed and reopened', async () => {
    render(<AnswerTrace {...props} />)
    const button = screen.getByRole('button', { name: /How this answer/ })

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

    fireEvent.click(screen.getByRole('button', { name: /How this answer/ }))

    expect(await screen.findByText(/No object reads were recorded/)).toBeInTheDocument()
  })

  it('reports a failure rather than staying blank', async () => {
    getRequestTrace.mockRejectedValue(new Error('trace unavailable'))
    render(<AnswerTrace {...props} />)

    fireEvent.click(screen.getByRole('button', { name: /How this answer/ }))

    expect(await screen.findByText(/trace unavailable/)).toBeInTheDocument()
  })
})
