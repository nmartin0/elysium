import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

vi.mock('@elysium/shell-api/api', () => ({
  query: vi.fn(),
}))
vi.mock('@elysium/shell-api/components/PendingWriteCard', () => ({
  // A simple stub -- PendingWriteCard has its own, thorough, direct
  // test file (packages/shell-api/src/components/PendingWriteCard.
  // test.jsx). This file's own job is only to confirm QueryPanel
  // renders it with the RIGHT pendingWrite data when the backend
  // returns one, not to re-prove PendingWriteCard's own internal
  // approve/reject/error behavior a second time here.
  default: ({ pendingWrite }) => <div data-testid="pending-write-card">{pendingWrite.id}</div>,
}))

import { query } from '@elysium/shell-api/api'
import QueryPanel from './QueryPanel'

beforeEach(() => {
  vi.clearAllMocks()
})

// query() deliberately returns the raw Response, never throwing on a
// non-2xx status -- see api.js's own docstring. Every mock below
// matches that real shape (status + an async json()), not a thrown
// ApiError the way most other api.js callers use.
function fakeResponse(status, body) {
  return { status, json: async () => body }
}

function submit(queryText) {
  fireEvent.change(screen.getByPlaceholderText('Ask a question…'), { target: { value: queryText } })
  fireEvent.click(screen.getByRole('button', { name: /ask/i }))
}

describe('QueryPanel -- rendering', () => {
  it('renders a textarea and an Ask button', () => {
    render(<QueryPanel onSessionExpired={vi.fn()} />)
    expect(screen.getByPlaceholderText('Ask a question…')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Ask' })).toBeInTheDocument()
  })

  it('shows no answer, error, or pending write on first render', () => {
    render(<QueryPanel onSessionExpired={vi.fn()} />)
    expect(screen.queryByTestId('pending-write-card')).not.toBeInTheDocument()
  })
})

describe('QueryPanel -- submitting', () => {
  it('calls query() with exactly what was typed', async () => {
    query.mockResolvedValue(fakeResponse(200, { answer: '42' }))
    render(<QueryPanel onSessionExpired={vi.fn()} />)

    submit('how many customers do we have?')

    await waitFor(() => expect(query).toHaveBeenCalledWith('how many customers do we have?'))
  })

  it('shows "Thinking…" and disables the button while in flight', async () => {
    let resolveQuery
    query.mockReturnValue(new Promise((resolve) => { resolveQuery = resolve }))
    render(<QueryPanel onSessionExpired={vi.fn()} />)

    submit('a question')

    await waitFor(() => expect(screen.getByRole('button', { name: 'Thinking…' })).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Thinking…' })).toBeDisabled()

    resolveQuery(fakeResponse(200, { answer: '42' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Ask' })).toBeInTheDocument())
  })
})

describe('QueryPanel -- a real 200 answer', () => {
  it('shows the answer text', async () => {
    query.mockResolvedValue(fakeResponse(200, { answer: 'There are 42 customers.' }))
    render(<QueryPanel onSessionExpired={vi.fn()} />)

    submit('how many customers?')

    await waitFor(() => expect(screen.getByText('There are 42 customers.')).toBeInTheDocument())
  })
})

describe('QueryPanel -- a 202 proposed write', () => {
  it('renders PendingWriteCard with the real pending_write from the response', async () => {
    query.mockResolvedValue(fakeResponse(202, { pending_write: { id: 'write-77' } }))
    render(<QueryPanel onSessionExpired={vi.fn()} />)

    submit('update the customer name')

    await waitFor(() => expect(screen.getByTestId('pending-write-card')).toHaveTextContent('write-77'))
  })

  it('does not show an answer or error alongside a pending write', async () => {
    query.mockResolvedValue(fakeResponse(202, { pending_write: { id: 'write-77' } }))
    render(<QueryPanel onSessionExpired={vi.fn()} />)

    submit('update the customer name')

    await waitFor(() => expect(screen.getByTestId('pending-write-card')).toBeInTheDocument())
    expect(screen.queryByText(/./, { selector: '.answer' })).not.toBeInTheDocument()
  })
})

describe('QueryPanel -- a 401 mid-query', () => {
  it('calls onSessionExpired and shows no answer, error, or pending write', async () => {
    query.mockResolvedValue(fakeResponse(401, {}))
    const onSessionExpired = vi.fn()
    render(<QueryPanel onSessionExpired={onSessionExpired} />)

    submit('a question')

    await waitFor(() => expect(onSessionExpired).toHaveBeenCalledTimes(1))
    expect(screen.queryByTestId('pending-write-card')).not.toBeInTheDocument()
  })
})

describe('QueryPanel -- other failure statuses', () => {
  it("shows the backend's own detail message for e.g. a 409 (permissions changed mid-query)", async () => {
    query.mockResolvedValue(fakeResponse(409, { detail: 'Permissions changed since this query started.' }))
    render(<QueryPanel onSessionExpired={vi.fn()} />)

    submit('a question')

    await waitFor(() => expect(screen.getByText('Permissions changed since this query started.')).toBeInTheDocument())
  })

  it('falls back to a generic "Request failed (status)" when the body has no detail', async () => {
    query.mockResolvedValue(fakeResponse(500, {}))
    render(<QueryPanel onSessionExpired={vi.fn()} />)

    submit('a question')

    await waitFor(() => expect(screen.getByText('Request failed (500)')).toBeInTheDocument())
  })

  it('shows "Could not reach the server." on a genuine network failure', async () => {
    query.mockRejectedValue(new Error('network down'))
    render(<QueryPanel onSessionExpired={vi.fn()} />)

    submit('a question')

    await waitFor(() => expect(screen.getByText('Could not reach the server.')).toBeInTheDocument())
  })
})

describe('QueryPanel -- a new submit clears stale state from the previous one', () => {
  it('clears a previous answer once a new query is submitted', async () => {
    query.mockResolvedValueOnce(fakeResponse(200, { answer: 'first answer' }))
    render(<QueryPanel onSessionExpired={vi.fn()} />)

    submit('first question')
    await waitFor(() => expect(screen.getByText('first answer')).toBeInTheDocument())

    query.mockReturnValue(new Promise(() => {}))
    submit('second question')

    await waitFor(() => expect(screen.queryByText('first answer')).not.toBeInTheDocument())
  })

  it('clears a previous error once a new query is submitted', async () => {
    query.mockResolvedValueOnce(fakeResponse(500, {}))
    render(<QueryPanel onSessionExpired={vi.fn()} />)

    submit('first question')
    await waitFor(() => expect(screen.getByText('Request failed (500)')).toBeInTheDocument())

    query.mockReturnValue(new Promise(() => {}))
    submit('second question')

    await waitFor(() => expect(screen.queryByText('Request failed (500)')).not.toBeInTheDocument())
  })

  it('clears a previous pending write once a new query is submitted', async () => {
    query.mockResolvedValueOnce(fakeResponse(202, { pending_write: { id: 'write-1' } }))
    render(<QueryPanel onSessionExpired={vi.fn()} />)

    submit('first question')
    await waitFor(() => expect(screen.getByTestId('pending-write-card')).toBeInTheDocument())

    query.mockReturnValue(new Promise(() => {}))
    submit('second question')

    await waitFor(() => expect(screen.queryByTestId('pending-write-card')).not.toBeInTheDocument())
  })
})
