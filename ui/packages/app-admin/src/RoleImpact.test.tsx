import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import RoleImpact, { impactLines } from './RoleImpact'

const NONE = {
  role: 'analyst',
  holders: 1,
  removes_role: false,
  types_gained: [],
  types_lost: [],
  fields_gained: [],
  fields_lost: [],
  actions_gained: [],
  actions_lost: [],
  other_gained: [],
  other_lost: [],
}

describe('a role change in access terms', () => {
  it('says each kind of gain and loss as a sentence, gains first', () => {
    const lines = impactLines({
      ...NONE,
      types_gained: [{ type: 'Order', from: null, to: 'read' }],
      types_lost: [{ type: 'Invoice', from: 'read', to: 'discover' }],
      fields_gained: [{ type: 'Customer', field: 'tier', from: null, to: 'discover' }],
      fields_lost: [{ type: 'Customer', field: 'email', from: 'read', to: 'discover' }],
      actions_lost: ['TransferFunds'],
      other_gained: ['manage:roles'],
    })

    expect(lines).toEqual([
      { text: 'Can now read Order', widens: true },
      { text: 'Can now know Customer.tier exists', widens: true },
      { text: 'Gains manage:roles', widens: true },
      { text: 'Can no longer read Invoice (still knows it exists)', widens: false },
      { text: 'Can no longer read Customer.email (still knows it exists)', widens: false },
      { text: 'Can no longer run TransferFunds', widens: false },
    ])
  })

  it('says when a change does nothing to what the role can do', () => {
    render(<RoleImpact impact={NONE} />)

    expect(screen.getByText('No change to what this role can see or do.')).toBeInTheDocument()
    expect(screen.getByText(/1 person holds analyst\./)).toBeInTheDocument()
  })

  it('says who is affected when nobody holds the role, and when it is removed', () => {
    render(<RoleImpact impact={{ ...NONE, holders: 0, removes_role: true }} />)

    expect(screen.getByText(/Nobody holds analyst yet; removing the role takes all of this/)).toBeInTheDocument()
  })
})
