import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

const getObjectNotes = vi.fn()
const createObjectNote = vi.fn()

vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return {
    ...actual,
    getObjectNotes: () => getObjectNotes(),
    createObjectNote: (...args: unknown[]) => createObjectNote(...args),
  }
})

const { default: ObjectNotes } = await import('./ObjectNotes')

const props = { objectType: 'Customer', objectId: 'c1', onSessionExpired: () => {} }

beforeEach(() => {
  vi.clearAllMocks()
  getObjectNotes.mockResolvedValue([])
})

describe('ObjectNotes', () => {
  it('shows what has been written, with who and when', async () => {
    getObjectNotes.mockResolvedValue([
      { id: 'n1', text: 'Fee waived after the flood.', author: 'alice', created_at: '2026-03-01' },
    ])

    render(<ObjectNotes {...props} />)

    expect(await screen.findByText('Fee waived after the flood.')).toBeInTheDocument()
    expect(screen.getByText(/alice/)).toBeInTheDocument()
  })

  it('says so when nothing has been written', async () => {
    render(<ObjectNotes {...props} />)

    expect(await screen.findByText(/Nothing has been written/)).toBeInTheDocument()
  })

  it('adds a note and shows it without refetching', async () => {
    /**
     * useFetchOnce does not refetch, deliberately. A new note is
     * appended locally rather than re-reading the whole list -- the
     * server is still the authority, this only avoids a round trip to
     * display something it just confirmed.
     */
    createObjectNote.mockResolvedValue({
      id: 'n2',
      text: 'New thought',
      author: 'bob',
      created_at: '2026-09-07',
    })
    render(<ObjectNotes {...props} />)
    await screen.findByText(/Nothing has been written/)

    fireEvent.change(screen.getByLabelText('New note'), { target: { value: 'New thought' } })
    fireEvent.click(screen.getByRole('button', { name: /Add note/ }))

    expect(await screen.findByText('New thought')).toBeInTheDocument()
    expect(getObjectNotes).toHaveBeenCalledTimes(1)
  })

  it('refuses whitespace, matching the server', async () => {
    // A control that submits something the server refuses teaches the
    // user nothing.
    render(<ObjectNotes {...props} />)
    await screen.findByText(/Nothing has been written/)

    fireEvent.change(screen.getByLabelText('New note'), { target: { value: '   ' } })

    expect(screen.getByRole('button', { name: /Add note/ })).toBeDisabled()
  })

  it('reports a failed save without losing what was typed', async () => {
    // Losing the text on a failed save means retyping it, which is the
    // moment someone gives up and puts it in email instead.
    createObjectNote.mockRejectedValue(new Error('could not save'))
    render(<ObjectNotes {...props} />)
    await screen.findByText(/Nothing has been written/)

    fireEvent.change(screen.getByLabelText('New note'), { target: { value: 'Worth keeping' } })
    fireEvent.click(screen.getByRole('button', { name: /Add note/ }))

    await waitFor(() => expect(screen.getByText(/could not save/)).toBeInTheDocument())
    expect(screen.getByLabelText('New note')).toHaveValue('Worth keeping')
  })
})
