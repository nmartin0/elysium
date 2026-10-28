import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'

vi.mock('@elysium/shell-api/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@elysium/shell-api/api')>()),
  getUsedBy: vi.fn(),
}))

import { getUsedBy, type UsedBy } from '@elysium/shell-api/api'
import UsedByDialog from './UsedBy'

const NOT_LISTED = 'Saved views, frozen sets, enrichment recipes, proposals and notes are not listed here yet.'

const REPORT: UsedBy = {
  referrers: [
    { kind: 'grant', place: 'role editor', says: 'has 1 grant naming it: read:Customer.region' },
    { kind: 'action', place: 'action CreateCustomer', says: 'sets Customer.region' },
    { kind: 'security', place: 'Account row rule', says: 'borrows its rule through Customer.region' },
    { kind: 'title', place: 'type Customer', says: 'uses it as its title' },
  ],
  not_listed: NOT_LISTED,
}

function renderDialog(
  target: Parameters<typeof UsedByDialog>[0]['target'] = { objectType: 'Customer', field: 'region' },
) {
  render(<UsedByDialog target={target} onClose={vi.fn()} onSessionExpired={vi.fn()} />)
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('what names a field', () => {
  it('asks for the field it was opened on and says what it is', async () => {
    vi.mocked(getUsedBy).mockResolvedValue(REPORT)
    renderDialog()

    expect(await screen.findByRole('dialog', { name: 'Used by: Customer.region' })).toBeInTheDocument()
    expect(getUsedBy).toHaveBeenCalledWith({ objectType: 'Customer', field: 'region' })
  })

  it('groups the rows by who owns them, in plain words', async () => {
    vi.mocked(getUsedBy).mockResolvedValue(REPORT)
    renderDialog()

    const roles = await screen.findByTestId('used-by-Roles')
    expect(within(roles).getByText('role editor')).toBeInTheDocument()
    expect(within(screen.getByTestId('used-by-Actions')).getByText('sets Customer.region')).toBeInTheDocument()
    expect(within(screen.getByTestId('used-by-Row security')).getByText('Account row rule')).toBeInTheDocument()
    // A kind the screen has no heading for lands under the type, not nowhere.
    expect(within(screen.getByTestId('used-by-Inside the type')).getByText('type Customer')).toBeInTheDocument()
  })

  it('lists a deprecated thing that names it as its replacement under its own heading', async () => {
    vi.mocked(getUsedBy).mockResolvedValue({
      referrers: [
        { kind: 'replacement', place: 'type Order, field cost', says: 'is deprecated and names it as its replacement' },
      ],
      not_listed: NOT_LISTED,
    })
    renderDialog()

    const replacements = await screen.findByTestId('used-by-Replacements')
    expect(within(replacements).getByText('type Order, field cost')).toBeInTheDocument()
    expect(screen.queryByTestId('used-by-Inside the type')).not.toBeInTheDocument()
  })

  it('counts the places', async () => {
    vi.mocked(getUsedBy).mockResolvedValue(REPORT)
    renderDialog()

    expect(await screen.findByText(/4 places in the configuration name Customer.region/)).toBeInTheDocument()
  })

  it('says one place in the singular', async () => {
    vi.mocked(getUsedBy).mockResolvedValue({ referrers: REPORT.referrers.slice(0, 1), not_listed: NOT_LISTED })
    renderDialog()

    expect(await screen.findByText(/One place in the configuration names Customer.region/)).toBeInTheDocument()
  })
})

describe('when nothing names it', () => {
  it('says so, and still says what it did not look at', async () => {
    vi.mocked(getUsedBy).mockResolvedValue({ referrers: [], not_listed: NOT_LISTED })
    renderDialog({ objectType: 'Account', field: 'currency' })

    expect(await screen.findByText(/Nothing in the configuration names Account.currency/)).toBeInTheDocument()
    expect(screen.getByText(NOT_LISTED)).toBeInTheDocument()
  })
})

describe('other targets and failures', () => {
  it('asks for a link by its name', async () => {
    vi.mocked(getUsedBy).mockResolvedValue({ referrers: [], not_listed: NOT_LISTED })
    renderDialog({ link: 'CustomerAccounts' })

    expect(await screen.findByRole('dialog', { name: 'Used by: link CustomerAccounts' })).toBeInTheDocument()
    expect(getUsedBy).toHaveBeenCalledWith({ link: 'CustomerAccounts' })
  })

  it('says a type by its name alone', async () => {
    vi.mocked(getUsedBy).mockResolvedValue(REPORT)
    renderDialog({ objectType: 'Customer' })

    expect(await screen.findByRole('dialog', { name: 'Used by: Customer' })).toBeInTheDocument()
  })

  it('shows a failure instead of an empty list', async () => {
    vi.mocked(getUsedBy).mockRejectedValue(new Error('The server is away.'))
    renderDialog()

    expect(await screen.findByText(/The server is away/)).toBeInTheDocument()
    expect(screen.queryByText(/Nothing in the configuration names/)).not.toBeInTheDocument()
  })
})
