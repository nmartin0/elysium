import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

vi.mock('@elysium/shell-api/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@elysium/shell-api/api')>()),
  getOntologyDescriptions: vi.fn(),
  getNewTypeSources: vi.fn(),
  getSourceTables: vi.fn(),
  getSourceColumns: vi.fn(),
  previewNewType: vi.fn(),
  applyNewType: vi.fn(),
}))

import {
  ApiError,
  applyNewType,
  getNewTypeSources,
  getOntologyDescriptions,
  getSourceColumns,
  getSourceTables,
  type NewTypePreview,
  type OntologyDescriptions,
  previewNewType,
} from '@elysium/shell-api/api'
import AddType from './AddType'

const DESCRIPTIONS: OntologyDescriptions = {
  digest: 'd1',
  label_enforcement: true,
  data_types: ['string', 'integer', 'decimal'],
  types: {},
}

const NOTHING_WIDENS: NewTypePreview = {
  diff: ['--- a', '+++ b', '+  Tickers:'],
  impact: { widens: false, roles: [] },
  needs_approval: false,
  source_has_table: true,
  columns_missing: [],
  columns_checked: true,
}

function renderDialog() {
  const onApplied = vi.fn()
  const onProposed = vi.fn()
  const onClose = vi.fn()
  render(<AddType onClose={onClose} onApplied={onApplied} onProposed={onProposed} onSessionExpired={vi.fn()} />)
  return { onApplied, onProposed, onClose }
}

const choose = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } })

/** Through source and table, to the form with its columns. */
async function openTickers() {
  await screen.findByLabelText('Source')
  choose('Source', 'primary_sql')
  await waitFor(() => expect(screen.getByLabelText('Table')).toBeEnabled())
  await screen.findByRole('option', { name: 'tickers' })
  choose('Table', 'tickers')
  await screen.findByLabelText('Id column')
}

const reviewButton = () => screen.getByRole('button', { name: 'Review' })

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(getOntologyDescriptions).mockResolvedValue(DESCRIPTIONS)
  vi.mocked(getNewTypeSources).mockResolvedValue([
    { silo: 'primary_sql', rule: null },
    { silo: 'ruled_sql', rule: { field: 'region' } },
  ])
  vi.mocked(getSourceTables).mockResolvedValue(['tickers', 'prices'])
  vi.mocked(getSourceColumns).mockResolvedValue(['symbol', 'Company Name', 'sector', 'region'])
  vi.mocked(previewNewType).mockResolvedValue(NOTHING_WIDENS)
  vi.mocked(applyNewType).mockResolvedValue({ status: 'applied', diff: [], to_generation: 12 })
})

describe('choosing what the type is made from', () => {
  it('offers the sources, then that source’s tables', async () => {
    renderDialog()
    await screen.findByLabelText('Source')
    expect(screen.getAllByRole('option').map((option) => option.textContent)).toContain('ruled_sql')

    choose('Source', 'primary_sql')

    await waitFor(() => expect(getSourceTables).toHaveBeenCalledWith('primary_sql'))
    expect(await screen.findByRole('option', { name: 'prices' })).toBeInTheDocument()
  })

  it('starts with every column ticked, and the likely id chosen', async () => {
    renderDialog()
    await openTickers()

    expect(screen.getByLabelText('Id column')).toHaveValue('symbol')
    for (const column of ['Company Name', 'sector', 'region']) {
      expect(screen.getByRole('checkbox', { name: column })).toBeChecked()
    }
    expect(screen.queryByRole('checkbox', { name: 'symbol' })).not.toBeInTheDocument()
  })

  it('takes the table’s own id, not the first column that ends in id', async () => {
    vi.mocked(getSourceTables).mockResolvedValue(['transactions'])
    vi.mocked(getSourceColumns).mockResolvedValue(['amount', 'customer_id', 'transaction_id'])
    renderDialog()
    await screen.findByLabelText('Source')
    choose('Source', 'primary_sql')
    await screen.findByRole('option', { name: 'transactions' })
    choose('Table', 'transactions')
    await screen.findByLabelText('Id column')

    expect(screen.getByLabelText('Id column')).toHaveValue('transaction_id')
  })

  it('names the type from the table, to be changed', async () => {
    renderDialog()
    await openTickers()

    expect(screen.getByLabelText('Name')).toHaveValue('Tickers')
  })

  it('takes the names by hand when the source cannot be asked', async () => {
    vi.mocked(getSourceTables).mockResolvedValue(null)
    vi.mocked(getSourceColumns).mockResolvedValue(null)
    renderDialog()
    await screen.findByLabelText('Source')
    choose('Source', 'primary_sql')
    const table = await screen.findByPlaceholderText(/could not list its tables/)
    fireEvent.change(table, { target: { value: 'tickers' } })

    expect(await screen.findByText(/could not list this table’s columns/)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Id column'), { target: { value: 'symbol' } })
    fireEvent.change(screen.getByLabelText(/Other columns to keep/), { target: { value: 'company, sector' } })
    choose('Rows are seen by', 'field')
    fireEvent.change(screen.getByLabelText('The field'), { target: { value: 'sector' } })
    fireEvent.click(reviewButton())

    await waitFor(() => expect(previewNewType).toHaveBeenCalled())
    expect(vi.mocked(previewNewType).mock.calls[0]![1]).toMatchObject({
      id_column: 'symbol',
      fields: [{ name: 'company' }, { name: 'sector' }],
    })
  })
})

describe('who may see its rows', () => {
  it('is never chosen for the person when the source declares no rule', async () => {
    renderDialog()
    await openTickers()

    expect(screen.queryByRole('option', { name: /^Follow / })).not.toBeInTheDocument()
    expect(screen.getByText(/declares no row rule/)).toBeInTheDocument()
    expect(screen.getByLabelText('Rows are seen by')).toHaveValue('')
    expect(reviewButton()).toBeDisabled()
  })

  it('offers to follow the source when it declares a rule, and still does not choose', async () => {
    renderDialog()
    await screen.findByLabelText('Source')
    choose('Source', 'ruled_sql')
    await screen.findByRole('option', { name: 'tickers' })
    choose('Table', 'tickers')
    await screen.findByLabelText('Id column')

    expect(screen.getByRole('option', { name: 'Follow ruled_sql: rows tagged by region' })).toBeInTheDocument()
    expect(screen.getByLabelText('Rows are seen by')).toHaveValue('')
    expect(reviewButton()).toBeDisabled()
    choose('Rows are seen by', 'inherit')
    expect(reviewButton()).toBeEnabled()
  })

  it('needs the field when the rule is a field', async () => {
    renderDialog()
    await openTickers()
    choose('Rows are seen by', 'field')
    expect(reviewButton()).toBeDisabled()

    choose('The field', 'region')

    expect(reviewButton()).toBeEnabled()
  })
})

describe('what is sent', () => {
  it('sends the kept columns, their types, the title and the rule, and nothing left unticked', async () => {
    renderDialog()
    await openTickers()
    fireEvent.click(screen.getByRole('checkbox', { name: 'region' }))
    choose('Data type of sector', 'decimal')
    choose('Title column', 'Company Name')
    choose('Name', 'Ticker')
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: ' Ticker ' } })
    choose('Rows are seen by', 'unrestricted')
    fireEvent.click(reviewButton())

    await waitFor(() => expect(previewNewType).toHaveBeenCalled())
    expect(previewNewType).toHaveBeenCalledWith('d1', {
      name: 'Ticker',
      silo: 'primary_sql',
      table: 'tickers',
      id_column: 'symbol',
      fields: [
        { name: 'company_name', column: 'Company Name' },
        { name: 'sector', data_type: 'decimal' },
      ],
      title_field: 'company_name',
      security: 'unrestricted',
    })
  })

  it('sends an integer id and the listing only when asked', async () => {
    renderDialog()
    await openTickers()
    choose('The id is', 'integer')
    fireEvent.click(screen.getByLabelText('List this type to everyone by name'))
    choose('Rows are seen by', 'unrestricted')
    fireEvent.click(reviewButton())

    await waitFor(() => expect(previewNewType).toHaveBeenCalled())
    expect(vi.mocked(previewNewType).mock.calls[0]![1]).toMatchObject({ id_type: 'integer', discoverable: true })
  })

  it('does not send a listing or an id type nobody asked for', async () => {
    renderDialog()
    await openTickers()
    choose('Rows are seen by', 'unrestricted')
    fireEvent.click(reviewButton())

    await waitFor(() => expect(previewNewType).toHaveBeenCalled())
    const sent = vi.mocked(previewNewType).mock.calls[0]![1]
    expect(sent).not.toHaveProperty('discoverable')
    expect(sent).not.toHaveProperty('id_type')
  })

  it('cannot be reviewed with every column unticked', async () => {
    renderDialog()
    await openTickers()
    choose('Rows are seen by', 'unrestricted')
    for (const column of ['Company Name', 'sector', 'region'])
      fireEvent.click(screen.getByRole('checkbox', { name: column }))

    expect(reviewButton()).toBeDisabled()
  })
})

describe('what review says besides the lines', () => {
  async function toReview(preview: Partial<NewTypePreview> = {}) {
    vi.mocked(previewNewType).mockResolvedValue({ ...NOTHING_WIDENS, ...preview })
    renderDialog()
    await openTickers()
    choose('Rows are seen by', 'unrestricted')
    fireEvent.click(reviewButton())
    await screen.findByText('What else this does')
  }

  it('says the source has the table, and who can read it', async () => {
    await toReview()

    expect(screen.getByText(/The source has the table tickers/)).toBeInTheDocument()
    expect(screen.getByText(/Nobody can read Tickers until a role is granted it/)).toBeInTheDocument()
    expect(screen.getByText(/manage:escalation/)).toBeInTheDocument()
    expect(screen.getByText(/people who are not granted it will not know it exists/)).toBeInTheDocument()
    expect(screen.getByText(/the lake gets a new table, Tickers/)).toBeInTheDocument()
  })

  it('says which columns the source lacks, and a missing table', async () => {
    await toReview({ source_has_table: false, columns_missing: ['sector'] })

    expect(screen.getByText(/The source has no table tickers/)).toBeInTheDocument()
    expect(screen.getByText(/not in it: sector/)).toBeInTheDocument()
  })

  it('says nothing was checked when the source could not be asked', async () => {
    await toReview({ source_has_table: null, columns_checked: false })

    expect(screen.getByText(/could not be asked, so its table and columns are not checked/)).toBeInTheDocument()
  })
})

describe('applying', () => {
  async function reviewed(preview: Partial<NewTypePreview> = {}) {
    vi.mocked(previewNewType).mockResolvedValue({ ...NOTHING_WIDENS, ...preview })
    const handlers = renderDialog()
    await openTickers()
    choose('Rows are seen by', 'unrestricted')
    fireEvent.click(reviewButton())
    await screen.findByText('What else this does')
    return handlers
  }

  it('applies at once when nothing widens', async () => {
    const { onApplied } = await reviewed()

    fireEvent.click(screen.getByRole('button', { name: 'Apply and reload' }))

    await waitFor(() => expect(onApplied).toHaveBeenCalledWith(12))
    expect(vi.mocked(applyNewType).mock.calls[0]![2]).toBeNull()
  })

  it('waits for a reason and a second person when listing it to everyone', async () => {
    vi.mocked(applyNewType).mockResolvedValue({ status: 'waiting', diff: [] })
    const { onProposed } = await reviewed({ needs_approval: true })
    const propose = screen.getByRole('button', { name: 'Propose for approval' })
    expect(propose).toBeDisabled()

    fireEvent.change(screen.getByLabelText(/Why/), { target: { value: ' Heliograph wants it findable ' } })
    fireEvent.click(propose)

    await waitFor(() => expect(onProposed).toHaveBeenCalled())
    expect(vi.mocked(applyNewType).mock.calls[0]![2]).toBe('Heliograph wants it findable')
  })

  it('keeps what was typed when the file moved underneath', async () => {
    vi.mocked(previewNewType).mockRejectedValue(new ApiError(409, 'The file changed.'))
    renderDialog()
    await openTickers()
    choose('Rows are seen by', 'unrestricted')
    fireEvent.click(reviewButton())

    expect(await screen.findByText(/What you typed is still here/)).toBeInTheDocument()
    expect(screen.getByLabelText('Name')).toHaveValue('Tickers')
    expect(reviewButton()).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Load the file again' }))
    await waitFor(() => expect(reviewButton()).toBeEnabled())
  })
})
