import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

vi.mock('@elysium/shell-api/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@elysium/shell-api/api')>()),
  getOntologyDescriptions: vi.fn(),
  getLinkableTypes: vi.fn(),
  getLinkableTypeColumns: vi.fn(),
  getSourceTables: vi.fn(),
  getSourceColumns: vi.fn(),
  previewNewLink: vi.fn(),
  applyNewLink: vi.fn(),
}))

import {
  ApiError,
  applyNewLink,
  getLinkableTypeColumns,
  getLinkableTypes,
  getOntologyDescriptions,
  getSourceColumns,
  getSourceTables,
  type NewLinkPreview,
  type OntologyDescriptions,
  previewNewLink,
} from '@elysium/shell-api/api'
import AddLink from './AddLink'

const DESCRIPTIONS: OntologyDescriptions = {
  digest: 'd1',
  label_enforcement: true,
  data_types: ['string'],
  types: {},
}

const NOTHING_WIDENS: NewLinkPreview = {
  diff: ['--- a', '+++ b', '+  CustomerPurchase:'],
  impact: { widens: false, roles: [] },
  needs_approval: false,
  problems: [],
  checked: true,
}

function renderDialog() {
  const onApplied = vi.fn()
  const onProposed = vi.fn()
  render(<AddLink onClose={vi.fn()} onApplied={onApplied} onProposed={onProposed} onSessionExpired={vi.fn()} />)
  return { onApplied, onProposed }
}

const choose = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } })
const reviewButton = () => screen.getByRole('button', { name: 'Review' })

/** Customer → Transaction, one to many, up to the column choice. */
async function chooseCustomerTransactions() {
  await screen.findAllByRole('option', { name: 'Customer' })
  choose('From', 'Customer')
  choose('To', 'Transaction')
  choose('How many', 'one_to_many')
  await screen.findByLabelText(/Column of the Transaction table/)
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(getOntologyDescriptions).mockResolvedValue(DESCRIPTIONS)
  vi.mocked(getLinkableTypes).mockResolvedValue([
    { name: 'Customer', display_name: 'Customer', silo: 'primary_sql' },
    { name: 'Transaction', display_name: 'Transaction', silo: 'primary_sql' },
    { name: 'SupportTicket', display_name: null, silo: 'support_crm' },
  ])
  vi.mocked(getLinkableTypeColumns).mockResolvedValue(['amount', 'customer_id', 'transaction_id'])
  vi.mocked(getSourceTables).mockResolvedValue(['customer_tags', 'customers'])
  vi.mocked(getSourceColumns).mockResolvedValue(['customer_id', 'tag_id'])
  vi.mocked(previewNewLink).mockResolvedValue(NOTHING_WIDENS)
  vi.mocked(applyNewLink).mockResolvedValue({ status: 'applied', diff: [], to_generation: 12 })
})

describe('choosing what to join', () => {
  it('offers the types, and does not choose how many for the person', async () => {
    renderDialog()
    await screen.findAllByRole('option', { name: 'Customer' })

    expect(screen.getByLabelText('How many')).toHaveValue('')
    expect(screen.getByLabelText('How many')).toBeDisabled()
    expect(reviewButton()).toBeDisabled()
  })

  it('says each relationship in the types’ own names', async () => {
    renderDialog()
    await screen.findAllByRole('option', { name: 'Customer' })
    choose('From', 'Customer')
    choose('To', 'Transaction')

    expect(screen.getByRole('option', { name: 'Each Customer has many Transactions' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Customer and Transaction have many of each other' })).toBeInTheDocument()
  })

  it('offers the columns of the TARGET’s table, and guesses only the exact id column', async () => {
    renderDialog()
    await chooseCustomerTransactions()

    expect(getLinkableTypeColumns).toHaveBeenCalledWith('Transaction')
    expect(screen.getByLabelText(/Column of the Transaction table/)).toHaveValue('customer_id')
  })

  it('does not guess a column that is merely similar', async () => {
    vi.mocked(getLinkableTypeColumns).mockResolvedValue(['amount', 'cust_ref', 'transaction_id'])
    renderDialog()
    await chooseCustomerTransactions()

    expect(screen.getByLabelText(/Column of the Transaction table/)).toHaveValue('')
    expect(reviewButton()).toBeDisabled()
  })

  it('takes the column by hand when the source cannot be asked', async () => {
    vi.mocked(getLinkableTypeColumns).mockResolvedValue(null)
    renderDialog()
    await chooseCustomerTransactions()

    const column = screen.getByPlaceholderText(/could not list its columns/)
    fireEvent.change(column, { target: { value: 'customer_ref' } })
    expect(reviewButton()).toBeEnabled()
  })

  it('names the two ends and the link from the types, until they are changed', async () => {
    renderDialog()
    await chooseCustomerTransactions()

    expect(screen.getByLabelText('On Customer')).toHaveValue('transactions')
    expect(screen.getByLabelText('On Transaction')).toHaveValue('customer')
    expect(screen.getByLabelText('Link name')).toHaveValue('CustomerTransaction')

    fireEvent.change(screen.getByLabelText('On Customer'), { target: { value: 'purchases' } })
    choose('To', 'SupportTicket')
    await screen.findByRole('option', { name: 'Choose a column…' })

    expect(screen.getByLabelText('On Customer')).toHaveValue('purchases')
    expect(screen.getByLabelText('On SupportTicket')).toHaveValue('customer')
  })

  it('names a one-to-one link in the singular on both ends', async () => {
    renderDialog()
    await screen.findAllByRole('option', { name: 'Customer' })
    choose('From', 'Customer')
    choose('To', 'Transaction')
    choose('How many', 'one_to_one')
    await screen.findByRole('option', { name: 'Choose a column…' })

    expect(screen.getByLabelText('On Customer')).toHaveValue('transaction')
    expect(screen.getByLabelText('On Transaction')).toHaveValue('customer')
  })

  it('asks for a join table and its two columns for many to many', async () => {
    renderDialog()
    await screen.findAllByRole('option', { name: 'Customer' })
    choose('From', 'Customer')
    choose('To', 'Transaction')
    choose('How many', 'many_to_many')
    await screen.findByRole('option', { name: 'customer_tags' })
    choose('Join table', 'customer_tags')
    await screen.findByLabelText('Column naming the Customer')
    expect(reviewButton()).toBeDisabled()
    choose('Column naming the Customer', 'customer_id')
    choose('Column naming the Transaction', 'tag_id')

    expect(getSourceTables).toHaveBeenCalledWith('primary_sql')
    expect(getSourceColumns).toHaveBeenCalledWith('primary_sql', 'customer_tags')
    expect(screen.getByLabelText('On Customer')).toHaveValue('transactions')
    expect(screen.getByLabelText('On Transaction')).toHaveValue('customers')
    expect(reviewButton()).toBeEnabled()
  })
})

describe('what is sent', () => {
  it('sends a foreign-key link with its column, trimmed, and nothing left empty', async () => {
    renderDialog()
    await chooseCustomerTransactions()
    fireEvent.change(screen.getByLabelText('On Customer'), { target: { value: ' purchases ' } })
    fireEvent.click(reviewButton())

    await waitFor(() => expect(previewNewLink).toHaveBeenCalled())
    expect(previewNewLink).toHaveBeenCalledWith('d1', {
      name: 'CustomerTransaction',
      source: { object_type: 'Customer', api_name: 'purchases' },
      target: { object_type: 'Transaction', api_name: 'customer' },
      cardinality: 'one_to_many',
      foreign_key_column: 'customer_id',
    })
  })

  it('sends a join table link without a foreign key', async () => {
    renderDialog()
    await screen.findAllByRole('option', { name: 'Customer' })
    choose('From', 'Customer')
    choose('To', 'Transaction')
    choose('How many', 'many_to_many')
    await screen.findByRole('option', { name: 'customer_tags' })
    choose('Join table', 'customer_tags')
    await screen.findByLabelText('Column naming the Customer')
    choose('Column naming the Customer', 'customer_id')
    choose('Column naming the Transaction', 'tag_id')
    fireEvent.click(reviewButton())

    await waitFor(() => expect(previewNewLink).toHaveBeenCalled())
    const sent = vi.mocked(previewNewLink).mock.calls[0]![1]
    expect(sent.join_table).toEqual({ table: 'customer_tags', source_column: 'customer_id', target_column: 'tag_id' })
    expect(sent).not.toHaveProperty('foreign_key_column')
  })

  it('sends the display name and description only when given', async () => {
    renderDialog()
    await chooseCustomerTransactions()
    fireEvent.change(screen.getByLabelText('Display name'), { target: { value: ' Purchases ' } })
    fireEvent.click(reviewButton())

    await waitFor(() => expect(previewNewLink).toHaveBeenCalled())
    const sent = vi.mocked(previewNewLink).mock.calls[0]![1]
    expect(sent.display_name).toBe('Purchases')
    expect(sent).not.toHaveProperty('description')
  })
})

describe('what review says besides the lines', () => {
  async function toReview(preview: Partial<NewLinkPreview> = {}) {
    vi.mocked(previewNewLink).mockResolvedValue({ ...NOTHING_WIDENS, ...preview })
    renderDialog()
    await chooseCustomerTransactions()
    fireEvent.click(reviewButton())
    await screen.findByText('What else this does')
  }

  it('says the source has the column, how the two ends are reached, and who can read them', async () => {
    await toReview()

    expect(screen.getByText('The source has the column customer_id.')).toBeInTheDocument()
    expect(
      screen.getByText(/Customer reaches Transaction as transactions, and Transaction reaches Customer as customer/),
    ).toBeInTheDocument()
    expect(screen.getByText(/manage:escalation/)).toBeInTheDocument()
    expect(screen.getByText(/The lake needs no new table/)).toBeInTheDocument()
  })

  it('says what the source lacks', async () => {
    await toReview({ problems: ['The table transactions has no column customer_id.'] })

    expect(screen.getByText('The table transactions has no column customer_id.')).toBeInTheDocument()
  })

  it('says nothing was checked when the source could not be asked', async () => {
    await toReview({ checked: false })

    expect(screen.getByText(/could not be asked, so its table and columns are not checked/)).toBeInTheDocument()
  })
})

describe('applying', () => {
  it('applies at once when nothing widens', async () => {
    const { onApplied } = renderDialog()
    await chooseCustomerTransactions()
    fireEvent.click(reviewButton())
    fireEvent.click(await screen.findByRole('button', { name: 'Apply and reload' }))

    await waitFor(() => expect(onApplied).toHaveBeenCalledWith(12))
    expect(vi.mocked(applyNewLink).mock.calls[0]![2]).toBeNull()
  })

  it('waits for a reason when it would widen access', async () => {
    vi.mocked(previewNewLink).mockResolvedValue({ ...NOTHING_WIDENS, needs_approval: true })
    vi.mocked(applyNewLink).mockResolvedValue({ status: 'waiting', diff: [] })
    const { onProposed } = renderDialog()
    await chooseCustomerTransactions()
    fireEvent.click(reviewButton())
    const propose = await screen.findByRole('button', { name: 'Propose for approval' })
    expect(propose).toBeDisabled()
    fireEvent.change(screen.getByLabelText(/Why/), { target: { value: ' because ' } })
    fireEvent.click(propose)

    await waitFor(() => expect(onProposed).toHaveBeenCalled())
    expect(vi.mocked(applyNewLink).mock.calls[0]![2]).toBe('because')
  })

  it('keeps what was typed when the file moved underneath', async () => {
    vi.mocked(previewNewLink).mockRejectedValue(new ApiError(409, 'The file changed.'))
    renderDialog()
    await chooseCustomerTransactions()
    fireEvent.click(reviewButton())

    expect(await screen.findByText(/What you typed is still here/)).toBeInTheDocument()
    expect(screen.getByLabelText('Link name')).toHaveValue('CustomerTransaction')
    expect(reviewButton()).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Load the file again' }))
    await waitFor(() => expect(reviewButton()).toBeEnabled())
  })
})
