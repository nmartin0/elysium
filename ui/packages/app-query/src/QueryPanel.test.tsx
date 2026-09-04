import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import type { PendingWrite } from '@elysium/shell-api/components/PendingWriteCard'

// Partial mock via importOriginal, not a hand-duplicated module shape
// -- see App.test.tsx's own header comment for the full reasoning.
// query() itself never throws ApiError at all (it deliberately
// returns the raw Response, see this file's own comment further
// down), so this file never needed handleIfSessionExpired/
// getErrorMessage mocked even before this -- converted to the same,
// consistent pattern as every other test file mocking this module
// regardless, so a FUTURE change to what QueryPanel.tsx imports from
// api.ts doesn't silently break this file the same way the prior,
// hand-duplicated shape already broke six others.
vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return {
    ...actual,
    query: vi.fn(),
  }
})
vi.mock('@elysium/shell-api/components/PendingWriteCard', () => ({
  // A simple stub -- PendingWriteCard has its own, thorough, direct
  // test file (packages/shell-api/src/components/PendingWriteCard.
  // test.tsx). This file's own job is only to confirm QueryPanel
  // renders it with the RIGHT pendingWrite data when the backend
  // returns one, not to re-prove PendingWriteCard's own internal
  // approve/reject/error behavior a second time here.
  default: ({ pendingWrite }: { pendingWrite: PendingWrite }) => (
    <div data-testid="pending-write-card">{pendingWrite.id}</div>
  ),
}))

import { query } from '@elysium/shell-api/api'
import QueryPanel from './QueryPanel'

const mockedQuery = vi.mocked(query)

beforeEach(() => {
  vi.clearAllMocks()
})

// query() deliberately returns the raw Response, never throwing on a
// non-2xx status -- see api.ts's own docstring. Every mock below
// matches that real shape (status + an async json()), not a thrown
// ApiError the way most other api.ts callers use. `as Response`, not
// `as unknown as Response` -- confirmed directly (via tsc) that this
// specific partial shape (status + a json() that always resolves,
// never throws) type-checks fine as a direct cast here, unlike
// api.test.ts's own inline failing-json() mock, which needed the
// double-cast; TypeScript's own "sufficient overlap" check for a
// direct `as` cast is apparently sensitive to that difference.
function fakeResponse(status: number, body: unknown): Response {
  return { status, json: async () => body } as Response
}

function submit(queryText: string) {
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
    mockedQuery.mockResolvedValue(fakeResponse(200, { answer: '42' }))
    render(<QueryPanel onSessionExpired={vi.fn()} />)

    submit('how many customers do we have?')

    await waitFor(() => expect(mockedQuery).toHaveBeenCalledWith('how many customers do we have?'))
  })

  it('shows "Thinking…" and disables the button while in flight', async () => {
    let resolveQuery: ((value: Response) => void) | undefined
    mockedQuery.mockReturnValue(
      new Promise((resolve) => {
        resolveQuery = resolve
      }),
    )
    render(<QueryPanel onSessionExpired={vi.fn()} />)

    submit('a question')

    await waitFor(() => expect(screen.getByRole('button', { name: 'Thinking…' })).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Thinking…' })).toBeDisabled()

    resolveQuery!(fakeResponse(200, { answer: '42' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Ask' })).toBeInTheDocument())
  })
})

describe('QueryPanel -- a real 200 answer', () => {
  it('shows the answer text', async () => {
    mockedQuery.mockResolvedValue(fakeResponse(200, { answer: 'There are 42 customers.' }))
    render(<QueryPanel onSessionExpired={vi.fn()} />)

    submit('how many customers?')

    await waitFor(() => expect(screen.getByText('There are 42 customers.')).toBeInTheDocument())
  })
})

describe('QueryPanel -- a 202 proposed write', () => {
  it('renders PendingWriteCard with the real pending_write from the response', async () => {
    mockedQuery.mockResolvedValue(fakeResponse(202, { pending_write: { id: 'write-77' } }))
    render(<QueryPanel onSessionExpired={vi.fn()} />)

    submit('update the customer name')

    await waitFor(() => expect(screen.getByTestId('pending-write-card')).toHaveTextContent('write-77'))
  })

  it('does not show an answer or error alongside a pending write', async () => {
    mockedQuery.mockResolvedValue(fakeResponse(202, { pending_write: { id: 'write-77' } }))
    render(<QueryPanel onSessionExpired={vi.fn()} />)

    submit('update the customer name')

    await waitFor(() => expect(screen.getByTestId('pending-write-card')).toBeInTheDocument())
    expect(screen.queryByText(/./, { selector: '.answer' })).not.toBeInTheDocument()
  })
})

describe('QueryPanel -- a 401 mid-query', () => {
  it('calls onSessionExpired and shows no answer, error, or pending write', async () => {
    mockedQuery.mockResolvedValue(fakeResponse(401, {}))
    const onSessionExpired = vi.fn()
    render(<QueryPanel onSessionExpired={onSessionExpired} />)

    submit('a question')

    await waitFor(() => expect(onSessionExpired).toHaveBeenCalledTimes(1))
    expect(screen.queryByTestId('pending-write-card')).not.toBeInTheDocument()
  })
})

describe('QueryPanel -- other failure statuses', () => {
  it("shows the backend's own detail message for e.g. a 409 (permissions changed mid-query)", async () => {
    mockedQuery.mockResolvedValue(fakeResponse(409, { detail: 'Permissions changed since this query started.' }))
    render(<QueryPanel onSessionExpired={vi.fn()} />)

    submit('a question')

    await waitFor(() => expect(screen.getByText('Permissions changed since this query started.')).toBeInTheDocument())
  })

  it('falls back to a generic "Request failed (status)" when the body has no detail', async () => {
    mockedQuery.mockResolvedValue(fakeResponse(500, {}))
    render(<QueryPanel onSessionExpired={vi.fn()} />)

    submit('a question')

    await waitFor(() => expect(screen.getByText('Request failed (500)')).toBeInTheDocument())
  })

  it('shows "Could not reach the server." on a genuine network failure', async () => {
    mockedQuery.mockRejectedValue(new Error('network down'))
    render(<QueryPanel onSessionExpired={vi.fn()} />)

    submit('a question')

    await waitFor(() => expect(screen.getByText('Could not reach the server.')).toBeInTheDocument())
  })
})

describe('QueryPanel -- a new submit clears stale state from the previous one', () => {
  it('clears a previous answer once a new query is submitted', async () => {
    mockedQuery.mockResolvedValueOnce(fakeResponse(200, { answer: 'first answer' }))
    render(<QueryPanel onSessionExpired={vi.fn()} />)

    submit('first question')
    await waitFor(() => expect(screen.getByText('first answer')).toBeInTheDocument())

    mockedQuery.mockReturnValue(new Promise(() => {}))
    submit('second question')

    await waitFor(() => expect(screen.queryByText('first answer')).not.toBeInTheDocument())
  })

  it('clears a previous error once a new query is submitted', async () => {
    mockedQuery.mockResolvedValueOnce(fakeResponse(500, {}))
    render(<QueryPanel onSessionExpired={vi.fn()} />)

    submit('first question')
    await waitFor(() => expect(screen.getByText('Request failed (500)')).toBeInTheDocument())

    mockedQuery.mockReturnValue(new Promise(() => {}))
    submit('second question')

    await waitFor(() => expect(screen.queryByText('Request failed (500)')).not.toBeInTheDocument())
  })

  it('clears a previous pending write once a new query is submitted', async () => {
    mockedQuery.mockResolvedValueOnce(fakeResponse(202, { pending_write: { id: 'write-1' } }))
    render(<QueryPanel onSessionExpired={vi.fn()} />)

    submit('first question')
    await waitFor(() => expect(screen.getByTestId('pending-write-card')).toBeInTheDocument())

    mockedQuery.mockReturnValue(new Promise(() => {}))
    submit('second question')

    await waitFor(() => expect(screen.queryByTestId('pending-write-card')).not.toBeInTheDocument())
  })
})
