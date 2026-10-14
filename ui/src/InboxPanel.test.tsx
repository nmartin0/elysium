import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

const getInboxCounts = vi.fn()

vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return { ...actual, getInboxCounts: () => getInboxCounts() }
})
vi.mock('@elysium/app-approvals/ApprovalsPanel', () => ({ default: () => <p>approvals panel</p> }))
vi.mock('@elysium/app-notifications/NotificationsPanel', () => ({ default: () => <p>notifications panel</p> }))
vi.mock('@elysium/app-identity/IdentityPanel', () => ({ default: () => <p>identity panel</p> }))

const { default: InboxPanel } = await import('./InboxPanel')

function show(url: string, counts = { approvals: 0, notifications: 0, identity: 0 }) {
  getInboxCounts.mockResolvedValue(counts)
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/inbox" element={<InboxPanel onSessionExpired={vi.fn()} />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('the Inbox (DEV_UI 12, 15)', () => {
  it('holds the three queues as tabs, approvals first', async () => {
    show('/inbox')

    expect(await screen.findByText('approvals panel')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /Approvals/ })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /Notifications/ })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /Identity/ })).toBeInTheDocument()
  })

  it('opens the tab the URL names, so a link to a tab is a link', async () => {
    show('/inbox?tab=identity')

    expect(await screen.findByText('identity panel')).toBeInTheDocument()
    expect(screen.queryByText('approvals panel')).toBeNull()
  })

  it('an unknown tab is approvals, not an empty page', async () => {
    show('/inbox?tab=nonsense')

    expect(await screen.findByText('approvals panel')).toBeInTheDocument()
  })

  it('each tab says how much is waiting in it', async () => {
    show('/inbox', { approvals: 3, notifications: 0, identity: 1 })

    const approvals = await screen.findByRole('tab', { name: /Approvals/ })
    await screen.findByText('3')

    expect(approvals).toHaveTextContent('3')
    expect(screen.getByRole('tab', { name: /Identity/ })).toHaveTextContent('1')
    // Nothing waiting says nothing -- not a zero.
    expect(screen.getByRole('tab', { name: /Notifications/ })).not.toHaveTextContent('0')
  })
})
