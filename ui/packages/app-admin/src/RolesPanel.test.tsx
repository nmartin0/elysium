/**
 * The Roles view: waiting changes, and proposing one.
 *
 * A CHANGE IS A PROPOSAL, and the screen says so at the moment of
 * proposing -- nobody should believe a role changed when it was only
 * asked for.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return {
    ...actual,
    getRoles: vi.fn(),
    getRoleChanges: vi.fn(),
    getCurrentUser: vi.fn(),
    proposeRoleChange: vi.fn(),
    approveRoleChange: vi.fn(),
    rejectRoleChange: vi.fn(),
  }
})

import { approveRoleChange, getCurrentUser, getRoleChanges, getRoles, proposeRoleChange } from '@elysium/shell-api/api'
import RolesPanel from './RolesPanel'

const mockedPropose = vi.mocked(proposeRoleChange)
const mockedApprove = vi.mocked(approveRoleChange)

function change(overrides = {}) {
  return {
    change_id: 'c1',
    role_name: 'reader',
    before: ['read:A', 'read:B'],
    after: ['read:B', 'read:C'],
    proposed_by: 'bob',
    proposed_at: '2026-01-01T00:00:00+00:00',
    status: 'pending',
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(getRoles).mockResolvedValue({
    source: 'policy.yaml',
    roles: { reader: ['read:A', 'read:B'], admin: ['manage:users'] },
    grantable: ['manage:users', 'manage:roles', 'read:A', 'read:B', 'read:C'],
  })
  vi.mocked(getRoleChanges).mockResolvedValue([])
  vi.mocked(getCurrentUser).mockResolvedValue({ username: 'alice' })
  mockedPropose.mockResolvedValue('c2')
  mockedApprove.mockResolvedValue(undefined)
})

function open() {
  return render(<RolesPanel onSessionExpired={vi.fn()} />)
}

describe('where the roles come from', () => {
  it('says policy.yaml until the first approved change', async () => {
    open()

    expect(await screen.findByText(/come from policy.yaml/)).toBeInTheDocument()
  })

  it('says that editing policy.yaml stops working once the store governs', async () => {
    /** HOW AN ADMINISTRATOR LEARNS IT -- otherwise a policy.yaml edit
     *  silently does nothing. */
    vi.mocked(getRoles).mockResolvedValue({ source: 'role store', roles: {}, grantable: [] })
    open()

    expect(await screen.findByText(/has no effect/)).toBeInTheDocument()
  })
})

describe('a waiting change', () => {
  it('reads as its difference', async () => {
    vi.mocked(getRoleChanges).mockResolvedValue([change()])
    open()

    expect(await screen.findByText('+ read:C')).toBeInTheDocument()
    expect(screen.getByText('− read:A')).toBeInTheDocument()
    expect(screen.queryByText(/read:B/)).toBeNull()
  })

  it('may be approved by somebody else', async () => {
    vi.mocked(getRoleChanges).mockResolvedValue([change()])
    open()

    fireEvent.click(await screen.findByRole('button', { name: 'Approve' }))

    await waitFor(() => expect(mockedApprove).toHaveBeenCalledWith('c1'))
  })

  it('may not be approved by its author', async () => {
    /** "OTHER THAN THE CHANGE REQUEST AUTHOR." The server refuses it
     *  too; disabling says so before the round trip. */
    vi.mocked(getRoleChanges).mockResolvedValue([change({ proposed_by: 'alice' })])
    open()

    await waitFor(() => expect(screen.getByRole('button', { name: 'Approve' })).toBeDisabled())
    expect(screen.getByRole('button', { name: 'Withdraw' })).toBeInTheDocument()
  })
})

describe('proposing', () => {
  it('sends the COMPLETE grants, starting from what the role holds', async () => {
    open()
    fireEvent.change(await screen.findByLabelText('Role to change'), {
      target: { value: 'reader' },
    })
    fireEvent.click(await screen.findByLabelText('read:C'))
    fireEvent.click(screen.getByRole('button', { name: 'Propose' }))

    await waitFor(() => expect(mockedPropose).toHaveBeenCalledWith('reader', ['read:A', 'read:B', 'read:C']))
  })

  it('says a proposal is not yet a change', async () => {
    open()
    fireEvent.change(await screen.findByLabelText('Role to change'), {
      target: { value: 'reader' },
    })
    fireEvent.click(await screen.findByLabelText('read:C'))
    fireEvent.click(screen.getByRole('button', { name: 'Propose' }))

    expect(await screen.findByText(/Somebody else must approve/)).toBeInTheDocument()
  })

  it('offers nothing to propose when nothing changed', async () => {
    open()
    fireEvent.change(await screen.findByLabelText('Role to change'), {
      target: { value: 'reader' },
    })

    expect(await screen.findByRole('button', { name: 'Propose' })).toBeDisabled()
  })

  it('proposes deleting with no grants at all', async () => {
    open()
    fireEvent.change(await screen.findByLabelText('Role to change'), {
      target: { value: 'reader' },
    })
    fireEvent.click(await screen.findByRole('button', { name: 'Propose deleting' }))

    await waitFor(() => expect(mockedPropose).toHaveBeenCalledWith('reader', null))
  })
})

describe('a refusal', () => {
  it('is shown, and announced', async () => {
    mockedPropose.mockRejectedValue(new Error('This would remove manage:roles from your own role.'))
    open()
    fireEvent.change(await screen.findByLabelText('Role to change'), {
      target: { value: 'reader' },
    })
    fireEvent.click(await screen.findByLabelText('read:C'))
    fireEvent.click(screen.getByRole('button', { name: 'Propose' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/your own role/)
  })
})

describe('the draft when the selection or the server state changes', () => {
  /**
   * WHAT THE SYNCHRONOUS RESET WAS FOR. The draft starts as what the
   * role holds NOW, so an edit is a change to something visible rather
   * than a list typed from memory. Two ways that can go wrong, neither
   * of which had a test:
   *
   *   an edit to one role carried over to another -- proposing grants
   *   nobody asked for, under a name nobody checked
   *
   *   an edit surviving a reload -- so the draft describes a version
   *   of the role the server no longer has
   */
  it('does not carry an edit from one role to another', async () => {
    open()
    const picker = await screen.findByLabelText('Role to change')

    fireEvent.change(picker, { target: { value: 'reader' } })
    fireEvent.click(await screen.findByLabelText('read:C'))
    // Switch away and back is not the test -- switching to a DIFFERENT
    // role must show that role's own grants.
    fireEvent.change(picker, { target: { value: 'admin' } })

    expect((screen.getByLabelText('manage:users') as HTMLInputElement).checked).toBe(true)
    expect((screen.getByLabelText('read:C') as HTMLInputElement).checked).toBe(false)
    expect((screen.getByLabelText('read:A') as HTMLInputElement).checked).toBe(false)
  })

  it('proposes the other role from ITS OWN grants, not the edited one', async () => {
    // The consequence, asserted at the boundary rather than on a
    // checkbox: what actually reaches the server.
    open()
    const picker = await screen.findByLabelText('Role to change')

    fireEvent.change(picker, { target: { value: 'reader' } })
    fireEvent.click(await screen.findByLabelText('read:C'))
    fireEvent.change(picker, { target: { value: 'admin' } })
    fireEvent.click(screen.getByLabelText('read:A'))
    fireEvent.click(screen.getByRole('button', { name: 'Propose' }))

    await waitFor(() => expect(mockedPropose).toHaveBeenCalledWith('admin', ['manage:users', 'read:A']))
  })

  it('starts again from the server state after a change is approved', async () => {
    // Approving reloads the roles; the draft must follow the new
    // server state rather than keeping an edit made against the old.
    vi.mocked(getRoleChanges).mockResolvedValueOnce([change({ role_name: 'reader', proposed_by: 'bob' })])
    open()
    fireEvent.change(await screen.findByLabelText('Role to change'), { target: { value: 'reader' } })
    fireEvent.click(await screen.findByLabelText('read:C'))
    expect((screen.getByLabelText('read:C') as HTMLInputElement).checked).toBe(true)

    // The reload returns a role that now holds read:C already and has
    // lost read:A -- a different set from the draft on screen.
    vi.mocked(getRoles).mockResolvedValue({
      source: 'the store',
      roles: { reader: ['read:B', 'read:C'], admin: ['manage:users'] },
      grantable: ['manage:users', 'manage:roles', 'read:A', 'read:B', 'read:C'],
    })
    vi.mocked(getRoleChanges).mockResolvedValue([])
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))

    await waitFor(() => expect((screen.getByLabelText('read:A') as HTMLInputElement).checked).toBe(false))
    expect((screen.getByLabelText('read:B') as HTMLInputElement).checked).toBe(true)
    expect((screen.getByLabelText('read:C') as HTMLInputElement).checked).toBe(true)
  })
})
