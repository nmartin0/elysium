import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ApiError } from '@elysium/shell-api/api'

const getObjectMemories = vi.fn()
const rememberAboutObject = vi.fn()
const forgetMemory = vi.fn()

vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return {
    ...actual,
    getObjectMemories: () => getObjectMemories(),
    rememberAboutObject: (...args: unknown[]) => rememberAboutObject(...args),
    forgetMemory: (...args: unknown[]) => forgetMemory(...args),
  }
})

const { default: ObjectMemories } = await import('./ObjectMemories')

const props = { objectType: 'Customer', objectId: 'c1', onSessionExpired: () => {} }

function memory(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: 'm1',
    text: 'Disputed two charges in March.',
    author: 'alice',
    created_at: '2026-10-14T09:00:00+00:00',
    stale: false,
    may_forget: false,
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  getObjectMemories.mockResolvedValue([])
})

describe('ObjectMemories', () => {
  it('shows what is remembered, with who wrote it', async () => {
    getObjectMemories.mockResolvedValue([memory()])

    render(<ObjectMemories {...props} />)

    expect(await screen.findByText('Disputed two charges in March.')).toBeInTheDocument()
    expect(screen.getByText(/alice/)).toBeInTheDocument()
    expect(screen.queryByText('stale')).not.toBeInTheDocument()
  })

  it('marks a stale memory, and only that one', async () => {
    getObjectMemories.mockResolvedValue([memory(), memory({ id: 'm2', text: 'Goes by Ada.', stale: true })])

    render(<ObjectMemories {...props} />)

    await screen.findByText('Goes by Ada.')
    expect(screen.getAllByText('stale')).toHaveLength(1)
    expect(screen.getByText('Goes by Ada.').closest('.object-memories__memory')).toHaveClass(
      'object-memories__memory--stale',
    )
  })

  it('offers Forget only where the server says it may', async () => {
    getObjectMemories.mockResolvedValue([memory(), memory({ id: 'm2', text: 'Mine.', may_forget: true })])

    render(<ObjectMemories {...props} />)

    await screen.findByText('Mine.')
    expect(screen.getAllByRole('button', { name: /Forget/ })).toHaveLength(1)
    expect(screen.getByRole('button', { name: 'Forget "Mine."' })).toBeInTheDocument()
  })

  it('forgets one and removes it from the list', async () => {
    getObjectMemories.mockResolvedValue([memory({ may_forget: true })])
    forgetMemory.mockResolvedValue(undefined)

    render(<ObjectMemories {...props} />)
    fireEvent.click(await screen.findByRole('button', { name: /Forget/ }))

    await waitFor(() => expect(screen.queryByText('Disputed two charges in March.')).not.toBeInTheDocument())
    expect(forgetMemory).toHaveBeenCalledWith('m1')
    expect(screen.getByText(/Nothing is remembered/)).toBeInTheDocument()
  })

  it('remembers a new fact and shows it without refetching', async () => {
    rememberAboutObject.mockResolvedValue(memory({ id: 'm3', text: 'Prefers email.', may_forget: true }))

    render(<ObjectMemories {...props} />)
    await screen.findByText(/Nothing is remembered/)
    fireEvent.change(screen.getByLabelText('Something to remember'), { target: { value: 'Prefers email.' } })
    fireEvent.click(screen.getByRole('button', { name: /Remember/ }))

    expect(await screen.findByText('Prefers email.')).toBeInTheDocument()
    expect(rememberAboutObject).toHaveBeenCalledWith('Customer', 'c1', 'Prefers email.')
    expect(getObjectMemories).toHaveBeenCalledTimes(1)
  })

  it('says why the server refused', async () => {
    rememberAboutObject.mockRejectedValue(new ApiError(400, 'A memory needs some text.'))

    render(<ObjectMemories {...props} />)
    await screen.findByText(/Nothing is remembered/)
    fireEvent.change(screen.getByLabelText('Something to remember'), { target: { value: 'x' } })
    fireEvent.click(screen.getByRole('button', { name: /Remember/ }))

    expect(await screen.findByText(/A memory needs some text/)).toBeInTheDocument()
  })

  it('cannot submit whitespace', async () => {
    render(<ObjectMemories {...props} />)
    await screen.findByText(/Nothing is remembered/)

    fireEvent.change(screen.getByLabelText('Something to remember'), { target: { value: '   ' } })

    expect(screen.getByRole('button', { name: /Remember/ })).toBeDisabled()
  })
})
