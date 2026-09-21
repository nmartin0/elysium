import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return {
    ...actual,
    getTriggers: vi.fn(),
    setTriggerEnabled: vi.fn(),
    deleteTrigger: vi.fn(),
  }
})

import { deleteTrigger, getTriggers, setTriggerEnabled } from '@elysium/shell-api/api'
import WatchList from './WatchList'

const mockedList = vi.mocked(getTriggers)
const mockedEnabled = vi.mocked(setTriggerEnabled)
const mockedDelete = vi.mocked(deleteTrigger)

function aTrigger(overrides = {}) {
  return {
    trigger_id: 't1',
    name: 'High value',
    view_id: 'v1',
    above: 10,
    gained: null,
    fell: null,
    enabled: true,
    created_at: '2026-01-01T00:00:00+00:00',
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedEnabled.mockResolvedValue(undefined)
  mockedDelete.mockResolvedValue(undefined)
})

describe('watching nothing', () => {
  it('says how to start', async () => {
    /** NOT AN ERROR AND NOT A SPINNER. Somebody watching nothing is
     *  the normal case, and the empty state is the only place to
     *  explain where watching begins. */
    mockedList.mockResolvedValue([])
    render(<WatchList onSessionExpired={vi.fn()} />)

    expect(await screen.findByText('Not watching anything')).toBeInTheDocument()
    expect(screen.getByText(/Save a search in Browse/)).toBeInTheDocument()
  })
})

describe('showing what is watched', () => {
  it('names the view and the condition', async () => {
    mockedList.mockResolvedValue([aTrigger()])
    render(<WatchList onSessionExpired={vi.fn()} />)

    expect(await screen.findByText('High value')).toBeInTheDocument()
    expect(screen.getByText('above 10')).toBeInTheDocument()
  })

  it('describes a gain differently from a threshold', async () => {
    mockedList.mockResolvedValue([aTrigger({ above: null, gained: 3 })])
    render(<WatchList onSessionExpired={vi.fn()} />)

    expect(await screen.findByText('gaining 3 or more')).toBeInTheDocument()
  })

  it('describes a fall differently again', async () => {
    mockedList.mockResolvedValue([aTrigger({ above: null, fell: 5 })])
    render(<WatchList onSessionExpired={vi.fn()} />)

    expect(await screen.findByText('losing 5 or more')).toBeInTheDocument()
  })
})

describe('quieting one', () => {
  it('disables rather than deletes', async () => {
    /** SOMEBODY QUIETING A NOISY TRIGGER usually wants it back, so
     *  the switch comes first and the remove control is separate. */
    mockedList.mockResolvedValue([aTrigger()])
    render(<WatchList onSessionExpired={vi.fn()} />)

    fireEvent.click(await screen.findByRole('checkbox'))

    await waitFor(() => expect(mockedEnabled).toHaveBeenCalledWith('t1', false))
    expect(mockedDelete).not.toHaveBeenCalled()
  })

  it('re-reads afterwards', async () => {
    mockedList.mockResolvedValue([aTrigger()])
    render(<WatchList onSessionExpired={vi.fn()} />)

    fireEvent.click(await screen.findByRole('checkbox'))

    await waitFor(() => expect(mockedList).toHaveBeenCalledTimes(2))
  })

  it('turns a disabled one back on', async () => {
    mockedList.mockResolvedValue([aTrigger({ enabled: false })])
    render(<WatchList onSessionExpired={vi.fn()} />)

    fireEvent.click(await screen.findByRole('checkbox'))

    await waitFor(() => expect(mockedEnabled).toHaveBeenCalledWith('t1', true))
  })
})

describe('removing one', () => {
  it('deletes it', async () => {
    mockedList.mockResolvedValue([aTrigger()])
    render(<WatchList onSessionExpired={vi.fn()} />)

    fireEvent.click(await screen.findByRole('button', { name: /stop watching/i }))

    await waitFor(() => expect(mockedDelete).toHaveBeenCalledWith('t1'))
  })
})

describe('when the request fails', () => {
  it('shows the failure rather than an empty list', async () => {
    mockedList.mockRejectedValue(new Error('the server is unreachable'))
    render(<WatchList onSessionExpired={vi.fn()} />)

    expect(await screen.findByText(/unreachable/)).toBeInTheDocument()
  })
})
