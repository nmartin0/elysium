import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

vi.mock('@elysium/shell-api/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@elysium/shell-api/api')>()),
  getOntologyDescriptions: vi.fn(),
  previewRetype: vi.fn(),
  applyRetype: vi.fn(),
  startMirrorSync: vi.fn(),
}))

import {
  ApiError,
  applyRetype,
  getOntologyDescriptions,
  previewRetype,
  type RetypePreview,
  startMirrorSync,
} from '@elysium/shell-api/api'
import type { VisibleSchema } from '@elysium/shell-api/types'
import RetypeDialog from './Retype'

const SCHEMA: VisibleSchema = {
  Transaction: {
    display_name: 'Transaction',
    status: 'active',
    fields: { amount: { type: 'data', display_name: 'Amount', data_type: 'number' } },
  },
}

const READY: RetypePreview = {
  diff: ['-        data_type: number', '+        data_type: decimal'],
  from_type: 'number',
  to_type: 'decimal',
  tables: ['primary_sql.transactions'],
  stored_data: [
    'Nothing is deleted from your source: Elysium only reads it.',
    'Silver of primary_sql.transactions cannot take the new type in place.',
  ],
  places: [{ kind: 'grant', place: 'role customer_service', says: 'has 1 grant naming it: read:Transaction.amount' }],
  hidden_places: 0,
  not_listed: 'Saved views and notes are not listed here yet.',
}

function renderDialog(onApplied = vi.fn()) {
  render(
    <RetypeDialog
      schema={SCHEMA}
      target={{ objectType: 'Transaction', field: 'amount' }}
      onClose={vi.fn()}
      onApplied={onApplied}
      onSessionExpired={vi.fn()}
    />,
  )
  return onApplied
}

const choose = async (type = 'decimal') =>
  fireEvent.change(await screen.findByLabelText('New data type'), { target: { value: type } })
const changeButton = () => screen.getByRole('button', { name: 'Change the type and reload' })

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(getOntologyDescriptions).mockResolvedValue({
    digest: 'd1',
    types: {},
    data_types: ['string', 'number', 'decimal', 'date'],
    label_enforcement: false,
  })
  vi.mocked(previewRetype).mockResolvedValue(READY)
  vi.mocked(applyRetype).mockResolvedValue({
    status: 'applied',
    diff: [],
    to_generation: 7,
    rebuild: ['primary_sql.transactions'],
  })
  vi.mocked(startMirrorSync).mockResolvedValue({ started: true, detail: 'A sync is running.' })
})

describe('choosing a type', () => {
  it('names the field and its type now, and offers every other type but not that one', async () => {
    renderDialog()

    expect(await screen.findByRole('dialog', { name: 'Change the type of Transaction.Amount' })).toBeInTheDocument()
    const options = (await screen.findAllByRole('option')).map((option) => option.getAttribute('value'))
    expect(options).toEqual(['', 'string', 'decimal', 'date'])
    expect(screen.getByText('number', { selector: 'strong' })).toBeInTheDocument()
  })

  it('previews nothing and cannot apply until a type is chosen', async () => {
    renderDialog()

    await screen.findByLabelText('New data type')
    expect(previewRetype).not.toHaveBeenCalled()
    expect(changeButton()).toBeDisabled()
  })

  it('previews exactly the choice, and says what changes in the words the server gave', async () => {
    renderDialog()

    await choose()

    await waitFor(() =>
      expect(previewRetype).toHaveBeenCalledWith('d1', {
        object_type: 'Transaction',
        field: 'amount',
        data_type: 'decimal',
      }),
    )
    expect(await screen.findByText('Nothing is deleted from your source: Elysium only reads it.')).toBeInTheDocument()
    expect(screen.getByText(/\+\s+data_type: decimal/)).toBeInTheDocument()
    expect(screen.getByText('Saved views and notes are not listed here yet.')).toBeInTheDocument()
  })

  it('lists the places that name it as notes: the change is still allowed', async () => {
    renderDialog()

    await choose()

    expect(await screen.findByText('role customer_service')).toBeInTheDocument()
    expect(screen.getByText(/do not stop the change/)).toBeInTheDocument()
    expect(changeButton()).toBeEnabled()
  })

  it('counts the places it may not describe', async () => {
    vi.mocked(previewRetype).mockResolvedValue({ ...READY, places: [], hidden_places: 2 })
    renderDialog()

    await choose()

    expect(await screen.findByText(/2 more places name something you cannot see in Schema/)).toBeInTheDocument()
  })

  it('shows nothing about places when nothing names the field', async () => {
    vi.mocked(previewRetype).mockResolvedValue({ ...READY, places: [] })
    renderDialog()

    await choose()

    await screen.findByText('Nothing is deleted from your source: Elysium only reads it.')
    expect(screen.queryByText('Places that name it')).not.toBeInTheDocument()
  })

  it('shows the server sentence when the preview is refused and cannot apply', async () => {
    vi.mocked(previewRetype).mockRejectedValue(
      new ApiError(400, 'That configuration would not load: timezone needs timestamptz'),
    )
    renderDialog()

    await choose('date')

    expect(await screen.findByText(/would not load: timezone needs timestamptz/)).toBeInTheDocument()
    expect(changeButton()).toBeDisabled()
  })
})

describe('applying', () => {
  it('applies exactly what was previewed, then shows the tables to rebuild before closing', async () => {
    const onApplied = renderDialog()
    await choose()
    await screen.findByText('role customer_service')

    fireEvent.click(changeButton())

    await screen.findByText('Tables to rebuild')
    expect(applyRetype).toHaveBeenCalledWith('d1', {
      object_type: 'Transaction',
      field: 'amount',
      data_type: 'decimal',
    })
    expect(screen.getByText('primary_sql.transactions')).toBeInTheDocument()
    expect(onApplied).not.toHaveBeenCalled()
  })

  it('starts a sync that names exactly those tables when "Rebuild now" is pressed', async () => {
    renderDialog()
    await choose()
    await screen.findByText('role customer_service')
    fireEvent.click(changeButton())

    fireEvent.click(await screen.findByRole('button', { name: 'Rebuild now' }))

    await waitFor(() => expect(startMirrorSync).toHaveBeenCalledWith(['primary_sql.transactions']))
    expect(await screen.findByText(/A sync is running with the rebuild/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Rebuild now' })).not.toBeInTheDocument()
  })

  it('"Rebuild later" closes and tells the screen which generation it became, without syncing', async () => {
    const onApplied = renderDialog()
    await choose()
    await screen.findByText('role customer_service')
    fireEvent.click(changeButton())

    fireEvent.click(await screen.findByRole('button', { name: 'Rebuild later' }))

    expect(onApplied).toHaveBeenCalledWith(7)
    expect(startMirrorSync).not.toHaveBeenCalled()
  })

  it('says so, and offers no rebuild, when no silver was built', async () => {
    vi.mocked(applyRetype).mockResolvedValue({ status: 'applied', diff: [], to_generation: 8, rebuild: [] })
    const onApplied = renderDialog()
    await choose()
    await screen.findByText('role customer_service')
    fireEvent.click(changeButton())

    expect(await screen.findByText(/No silver table needs rebuilding/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Rebuild now' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Done' }))
    expect(onApplied).toHaveBeenCalledWith(8)
  })

  it('shows the server sentence when the rebuild is refused and offers it again', async () => {
    vi.mocked(startMirrorSync).mockRejectedValue(new ApiError(400, 'primary_sql.transactions does not need a rebuild'))
    renderDialog()
    await choose()
    await screen.findByText('role customer_service')
    fireEvent.click(changeButton())

    fireEvent.click(await screen.findByRole('button', { name: 'Rebuild now' }))

    expect(await screen.findByText(/does not need a rebuild/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Rebuild now' })).toBeEnabled()
  })

  it('a changed file is said so and can be loaded again, and nothing is applied', async () => {
    vi.mocked(applyRetype).mockRejectedValue(
      new ApiError(409, 'ontology_schema.yaml has changed since you opened it. Load it again.'),
    )
    renderDialog()
    await choose()
    await screen.findByText('role customer_service')

    fireEvent.click(changeButton())

    expect(await screen.findByText(/changed since you opened it/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Load the file again' }))
    await waitFor(() => expect(getOntologyDescriptions).toHaveBeenCalledTimes(2))
    expect(changeButton()).toBeDisabled()
  })
})
