import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

vi.mock('@elysium/shell-api/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@elysium/shell-api/api')>()),
  getConfigProposals: vi.fn(),
  getCurrentUser: vi.fn(),
  approveConfigProposal: vi.fn(),
  rejectConfigProposal: vi.fn(),
}))

import {
  ApiError,
  approveConfigProposal,
  type ConfigProposal,
  getConfigProposals,
  getCurrentUser,
  rejectConfigProposal,
} from '@elysium/shell-api/api'
import ConfigProposals from './ConfigProposals'

const mockedList = vi.mocked(getConfigProposals)
const mockedMe = vi.mocked(getCurrentUser)
const mockedApprove = vi.mocked(approveConfigProposal)
const mockedReject = vi.mocked(rejectConfigProposal)

/** Shaped as GET /admin/config-proposals returns one. */
const PROPOSAL: ConfigProposal = {
  proposal_id: 'p1',
  kind: 'labels',
  summary: 'Customer.email: pii → none',
  reason: 'Not personal in this business.',
  proposed_by: 'ops',
  proposed_at: '2026-10-16T12:00:00+00:00',
  diff: ['--- a', '+++ b', '-        classification: pii'],
  impact: {
    widens: true,
    roles: [
      {
        role: 'customer_service',
        holders: 3,
        removes_role: false,
        types_gained: [],
        types_lost: [],
        fields_gained: [{ type: 'Customer', field: 'email', from: 'discover', to: 'read' }],
        fields_lost: [],
        actions_gained: [],
        actions_lost: [],
        other_gained: [],
        other_lost: [],
      },
    ],
  },
  stale: false,
  problem: null,
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedList.mockResolvedValue([PROPOSAL])
  mockedMe.mockResolvedValue({ username: 'rita' })
  mockedApprove.mockResolvedValue({ to_generation: 70 })
  mockedReject.mockResolvedValue({ status: 'rejected' })
})

describe('configuration changes waiting', () => {
  it('shows the approver what, who, why and what it does', async () => {
    render(<ConfigProposals onSessionExpired={vi.fn()} />)

    expect(await screen.findByText('Customer.email: pii → none')).toBeInTheDocument()
    expect(screen.getByText('proposed by ops')).toBeInTheDocument()
    expect(screen.getByText('Not personal in this business.')).toBeInTheDocument()
    expect(screen.getByText('Can now read Customer.email')).toBeInTheDocument()
    expect(screen.getByText('- classification: pii')).toBeInTheDocument()
  })

  it('approves, and says the generation', async () => {
    render(<ConfigProposals onSessionExpired={vi.fn()} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Approve' }))

    expect(await screen.findByText(/reloaded as generation 70/)).toBeInTheDocument()
    expect(mockedApprove).toHaveBeenCalledWith('p1')
  })

  it('its proposer cannot approve it, and withdraws rather than rejects', async () => {
    mockedMe.mockResolvedValue({ username: 'ops' })
    render(<ConfigProposals onSessionExpired={vi.fn()} />)

    expect(await screen.findByRole('button', { name: 'Approve' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Withdraw' })).toBeInTheDocument()
  })

  it('a stale one says so and cannot be approved', async () => {
    mockedList.mockResolvedValue([{ ...PROPOSAL, stale: true }])
    render(<ConfigProposals onSessionExpired={vi.fn()} />)

    expect(await screen.findByText('The configuration has changed since')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Approve' })).toBeDisabled()
  })

  it('a refusal is said, not swallowed', async () => {
    mockedApprove.mockRejectedValue(new ApiError(409, 'The configuration has changed since this was proposed.'))
    render(<ConfigProposals onSessionExpired={vi.fn()} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Approve' }))

    expect(await screen.findByText(/changed since this was proposed/)).toBeInTheDocument()
  })

  it('renders nothing for someone the server refuses, or when nothing waits', async () => {
    mockedList.mockRejectedValue(new ApiError(403, 'Needs manage:roles or manage:deployment'))
    const { container, unmount } = render(<ConfigProposals onSessionExpired={vi.fn()} />)
    await waitFor(() => expect(mockedList).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
    unmount()

    mockedList.mockResolvedValue([])
    render(<ConfigProposals onSessionExpired={vi.fn()} showEmpty />)
    expect(await screen.findByText('Nothing is waiting.')).toBeInTheDocument()
  })
})
