import { render, screen, waitFor } from '@testing-library/react'
import { fireEvent } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return {
    ...actual,
    getNotifications: vi.fn(),
    markNotificationSeen: vi.fn(),
  }
})

import { getNotifications, markNotificationSeen } from '@elysium/shell-api/api'
import NotificationsPanel from './NotificationsPanel'

const mockedList = vi.mocked(getNotifications)
const mockedSeen = vi.mocked(markNotificationSeen)

function notification(overrides = {}) {
  return {
    notification_id: 'n1',
    created_at: new Date().toISOString(),
    kind: 'mirror_health',
    summary: 'A sync was refused',
    detail: null,
    seen: false,
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('an empty inbox', () => {
  it('says there is nothing to report', async () => {
    /** NOT AN ERROR, AND NOT A SPINNER. Somebody with no
     *  notifications is the normal case, not a failure. */
    mockedList.mockResolvedValue({ notifications: [], unseen: 0 })
    render(<NotificationsPanel onSessionExpired={vi.fn()} />)

    expect(await screen.findByText('Nothing to report')).toBeInTheDocument()
  })
})

describe('showing what arrived', () => {
  it('shows the summary', async () => {
    mockedList.mockResolvedValue({ notifications: [notification()], unseen: 1 })
    render(<NotificationsPanel onSessionExpired={vi.fn()} />)

    expect(await screen.findByText('A sync was refused')).toBeInTheDocument()
  })

  it('shows the detail when there is one', async () => {
    mockedList.mockResolvedValue({
      notifications: [notification({ detail: 'Admin -> Mirror shows each table.' })],
      unseen: 1,
    })
    render(<NotificationsPanel onSessionExpired={vi.fn()} />)

    expect(await screen.findByText(/Admin -> Mirror/)).toBeInTheDocument()
  })

  it('offers to mark an unread one as read', async () => {
    mockedList.mockResolvedValue({ notifications: [notification()], unseen: 1 })
    render(<NotificationsPanel onSessionExpired={vi.fn()} />)

    expect(await screen.findByRole('button', { name: /mark as read/i })).toBeInTheDocument()
  })

  it('does not offer that on one already read', async () => {
    // THE CONTROL. A button on every row would pass the test above
    // while telling somebody to read what they have read.
    mockedList.mockResolvedValue({
      notifications: [notification({ seen: true })],
      unseen: 0,
    })
    render(<NotificationsPanel onSessionExpired={vi.fn()} />)

    await screen.findByText('A sync was refused')
    expect(screen.queryByRole('button', { name: /mark as read/i })).toBeNull()
  })
})

describe('marking one read', () => {
  it('tells the server and re-reads', async () => {
    /** RE-READ RATHER THAN PATCH IN PLACE. The server decides what is
     *  seen, and a local edit that disagreed would show one thing
     *  here and another after a reload. */
    mockedList.mockResolvedValue({ notifications: [notification()], unseen: 1 })
    mockedSeen.mockResolvedValue(undefined)
    render(<NotificationsPanel onSessionExpired={vi.fn()} />)

    fireEvent.click(await screen.findByRole('button', { name: /mark as read/i }))

    await waitFor(() => expect(mockedSeen).toHaveBeenCalledWith('n1'))
    await waitFor(() => expect(mockedList).toHaveBeenCalledTimes(2))
  })
})

describe('when the request fails', () => {
  it('shows the failure rather than an empty page', async () => {
    mockedList.mockRejectedValue(new Error('the server is unreachable'))
    render(<NotificationsPanel onSessionExpired={vi.fn()} />)

    expect(await screen.findByText(/unreachable/)).toBeInTheDocument()
  })
})
