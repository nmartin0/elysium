import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'

vi.mock('@elysium/shell-api/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@elysium/shell-api/api')>()),
  getOntologyDescriptions: vi.fn(),
  getTablesToRebuild: vi.fn(),
  previewRetype: vi.fn(),
  applyRetype: vi.fn(),
  startMirrorSync: vi.fn(),
}))

import {
  ApiError,
  applyRetype,
  getOntologyDescriptions,
  getTablesToRebuild,
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
    tables: ['primary_sql.transactions'],
    rebuild: ['primary_sql.transactions'],
    rebuild_unknown: false,
  })
  vi.mocked(getTablesToRebuild).mockResolvedValue({ rebuild: ['primary_sql.transactions'], unknown: false })
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

    await screen.findByText('Tables whose silver is owed a rebuild')
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

  it('says so, and offers no rebuild, when no silver was built or it already has the new type', async () => {
    vi.mocked(applyRetype).mockResolvedValue({
      status: 'applied',
      diff: [],
      to_generation: 8,
      tables: ['primary_sql.transactions'],
      rebuild: [],
      rebuild_unknown: false,
    })
    const onApplied = renderDialog()
    await choose()
    await screen.findByText('role customer_service')
    fireEvent.click(changeButton())

    expect(await screen.findByText(/No silver table needs rebuilding/)).toBeInTheDocument()
    expect(screen.getByText(/not built yet or already has the new type/)).toBeInTheDocument()
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

describe('what it says about the tables', () => {
  const applyIt = async () => {
    renderDialog()
    await choose()
    await screen.findByText('role customer_service')
    fireEvent.click(changeButton())
    // Let the apply settle (its busy flag is cleared after the reply is shown).
    await act(async () => undefined)
  }

  it('does not claim that nothing was touched, nor that history is the only thing a rebuild discards', async () => {
    await applyIt()

    await screen.findByText('Tables whose silver is owed a rebuild')
    expect(document.body.textContent).not.toMatch(/nothing stored has been touched/i)
    expect(document.body.textContent).not.toMatch(/nothing else/)
    expect(
      screen.getByText(/rebuilds\s+gold of every type stored in it and restarts its publication tags/),
    ).toBeInTheDocument()
    expect(screen.getByText(/Bronze and the changelog are kept/)).toBeInTheDocument()
  })

  it('says waiting is not free: a value that cannot convert is handled at each sync as the setting says', async () => {
    await applyIt()

    expect(await screen.findByText(/every sync until then still reads the source/)).toBeInTheDocument()
    expect(screen.getByText(/on_type_mismatch/)).toBeInTheDocument()
  })

  it('labels a table owed from an earlier change as not this one', async () => {
    vi.mocked(applyRetype).mockResolvedValue({
      status: 'applied',
      diff: [],
      to_generation: 7,
      tables: ['primary_sql.transactions'],
      rebuild: ['primary_sql.accounts', 'primary_sql.transactions'],
      rebuild_unknown: false,
    })
    await applyIt()

    expect(await screen.findByText(/owed from an earlier change, not this one/)).toBeInTheDocument()
    expect(screen.getByText(/\(this field\)/)).toBeInTheDocument()
  })

  it('says the mirror could not be read, offers no rebuild and does not claim none is needed', async () => {
    vi.mocked(applyRetype).mockResolvedValue({
      status: 'applied',
      diff: [],
      to_generation: 9,
      tables: ['primary_sql.transactions'],
      rebuild: [],
      rebuild_unknown: true,
    })
    const onApplied = renderDialog()
    await choose()
    await screen.findByText('role customer_service')
    fireEvent.click(changeButton())

    expect(
      await screen.findByText(/could not be read, so this cannot tell which tables need a rebuild/),
    ).toBeInTheDocument()
    expect(screen.queryByText(/No silver table needs rebuilding/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Rebuild now' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Done' }))
    expect(onApplied).toHaveBeenCalledWith(9)
  })

  it('after a refused rebuild asks what is owed now instead of retrying the stale set', async () => {
    vi.mocked(startMirrorSync).mockRejectedValue(new ApiError(400, 'primary_sql.transactions does not need a rebuild'))
    vi.mocked(getTablesToRebuild).mockResolvedValue({ rebuild: [], unknown: false })
    await applyIt()

    fireEvent.click(await screen.findByRole('button', { name: 'Rebuild now' }))

    await waitFor(() => expect(getTablesToRebuild).toHaveBeenCalledTimes(1))
    expect(await screen.findByText(/No silver table needs rebuilding/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Rebuild now' })).not.toBeInTheDocument()
  })
})

describe('previews that arrive out of order', () => {
  const preview = (toType: string): RetypePreview => ({
    ...READY,
    to_type: toType,
    stored_data: [`the sentence for ${toType}`],
    diff: [`+        data_type: ${toType}`],
  })

  it('shows only the reply for the choice now selected, and applies only that', async () => {
    let answerDecimal: (value: RetypePreview) => void = () => undefined
    vi.mocked(previewRetype).mockImplementation((_digest, change) =>
      change.data_type === 'decimal'
        ? new Promise<RetypePreview>((resolve) => {
            answerDecimal = resolve
          })
        : Promise.resolve(preview(change.data_type)),
    )
    renderDialog()
    await choose('decimal')
    await choose('date')
    expect(await screen.findByText('the sentence for date')).toBeInTheDocument()

    await act(async () => answerDecimal(preview('decimal')))

    expect(screen.queryByText('the sentence for decimal')).not.toBeInTheDocument()
    expect(screen.getByText('the sentence for date')).toBeInTheDocument()
    fireEvent.click(changeButton())
    await waitFor(() =>
      expect(applyRetype).toHaveBeenCalledWith('d1', {
        object_type: 'Transaction',
        field: 'amount',
        data_type: 'date',
      }),
    )
  })

  it('keeps apply disabled while the reply for the selected type has not come', async () => {
    vi.mocked(previewRetype).mockImplementation((_digest, change) =>
      change.data_type === 'decimal'
        ? Promise.resolve(preview('decimal'))
        : new Promise<RetypePreview>(() => undefined),
    )
    renderDialog()
    await choose('decimal')
    await screen.findByText('the sentence for decimal')
    expect(changeButton()).toBeEnabled()

    await choose('date')

    expect(screen.queryByText('the sentence for decimal')).not.toBeInTheDocument()
    expect(changeButton()).toBeDisabled()
  })

  it('drops a late failure for a choice no longer selected', async () => {
    let failDecimal: (reason: unknown) => void = () => undefined
    vi.mocked(previewRetype).mockImplementation((_digest, change) =>
      change.data_type === 'decimal'
        ? new Promise<RetypePreview>((_resolve, reject) => {
            failDecimal = reject
          })
        : Promise.resolve(preview(change.data_type)),
    )
    renderDialog()
    await choose('decimal')
    await choose('date')
    await screen.findByText('the sentence for date')

    await act(async () => failDecimal(new ApiError(400, 'decimal is refused')))

    expect(screen.queryByText(/decimal is refused/)).not.toBeInTheDocument()
    expect(changeButton()).toBeEnabled()
  })
})
