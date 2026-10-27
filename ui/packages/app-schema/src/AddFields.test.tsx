import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'

vi.mock('@elysium/shell-api/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@elysium/shell-api/api')>()),
  getOntologyDescriptions: vi.fn(),
  previewNewFields: vi.fn(),
  applyNewFields: vi.fn(),
}))

import {
  ApiError,
  applyNewFields,
  getOntologyDescriptions,
  type NewFieldsPreview,
  type OntologyDescriptions,
  previewNewFields,
} from '@elysium/shell-api/api'
import AddFields from './AddFields'

const mockedGet = vi.mocked(getOntologyDescriptions)
const mockedPreview = vi.mocked(previewNewFields)
const mockedApply = vi.mocked(applyNewFields)

const DESCRIPTIONS: OntologyDescriptions = {
  digest: 'd1',
  label_enforcement: true,
  data_types: ['string', 'integer', 'decimal'],
  types: {},
}

const NOTHING_WIDENS: NewFieldsPreview = {
  diff: ['--- a', '+++ b', '+      nickname:'],
  impact: { widens: false, roles: [] },
  needs_approval: false,
  fields: [{ object_type: 'Customer', field: 'nickname', column: 'nickname', source_has_column: true }],
}

const WIDENS: NewFieldsPreview = {
  ...NOTHING_WIDENS,
  impact: {
    widens: true,
    roles: [
      {
        role: 'labelled_reader',
        holders: 2,
        removes_role: false,
        types_gained: [],
        types_lost: [],
        fields_gained: [{ type: 'Customer', field: 'nickname', from: 'none' as never, to: 'read' as const }],
        fields_lost: [],
        actions_gained: [],
        actions_lost: [],
        other_gained: [],
        other_lost: [],
      },
    ],
  },
  needs_approval: true,
}

function renderDialog() {
  const onApplied = vi.fn()
  const onProposed = vi.fn()
  const onClose = vi.fn()
  render(
    <AddFields
      objectType="Customer"
      shownAs="Customer"
      onClose={onClose}
      onApplied={onApplied}
      onProposed={onProposed}
      onSessionExpired={vi.fn()}
    />,
  )
  return { onApplied, onProposed, onClose }
}

const typeInto = (label: string, value: string, at = 0) =>
  fireEvent.change(screen.getAllByLabelText(label)[at]!, { target: { value } })

beforeEach(() => {
  vi.clearAllMocks()
  mockedGet.mockResolvedValue(DESCRIPTIONS)
  mockedPreview.mockResolvedValue(NOTHING_WIDENS)
  mockedApply.mockResolvedValue({ status: 'applied', diff: [], to_generation: 12 })
})

describe('adding a field', () => {
  it('offers the data types the server accepts, and nothing else', async () => {
    renderDialog()

    const select = await screen.findByLabelText('Data type')
    expect(
      within(select)
        .getAllByRole('option')
        .map((option) => option.textContent),
    ).toEqual(['string', 'integer', 'decimal'])
  })

  it('cannot be reviewed without a name', async () => {
    renderDialog()
    const review = await screen.findByRole('button', { name: 'Review' })
    expect(review).toBeDisabled()

    typeInto('Name', '  ')
    expect(review).toBeDisabled()
    typeInto('Name', 'nickname')
    expect(review).toBeEnabled()
  })

  it('sends only what was filled in, trimmed, with the labels as a list', async () => {
    renderDialog()
    await screen.findByLabelText('Name')
    typeInto('Name', ' nickname ')
    typeInto('Data type', 'integer')
    typeInto('Description', ' What they go by ')
    typeInto('Access labels', 'pii, contact ,')
    typeInto('Source column', ' nick_name ')
    fireEvent.click(screen.getByRole('button', { name: 'Review' }))

    await waitFor(() =>
      expect(mockedPreview).toHaveBeenCalledWith('d1', [
        {
          object_type: 'Customer',
          name: 'nickname',
          data_type: 'integer',
          description: 'What they go by',
          labels: ['pii', 'contact'],
          column: 'nick_name',
        },
      ]),
    )
  })

  it('leaves out the boxes left empty', async () => {
    renderDialog()
    await screen.findByLabelText('Name')
    typeInto('Name', 'nickname')
    fireEvent.click(screen.getByRole('button', { name: 'Review' }))

    await waitFor(() =>
      expect(mockedPreview).toHaveBeenCalledWith('d1', [
        { object_type: 'Customer', name: 'nickname', data_type: 'string' },
      ]),
    )
  })
})

describe('what review says besides the lines', () => {
  async function review(preview: NewFieldsPreview = NOTHING_WIDENS) {
    mockedPreview.mockResolvedValue(preview)
    renderDialog()
    await screen.findByLabelText('Name')
    typeInto('Name', 'nickname')
    fireEvent.click(screen.getByRole('button', { name: 'Review' }))
    await screen.findByText('What else this does')
  }

  it('says the source has the column', async () => {
    await review()
    expect(screen.getByText(/the source table has it\./)).toBeInTheDocument()
  })

  it('says when the source has no such column, and what to do', async () => {
    await review({ ...NOTHING_WIDENS, fields: [{ ...NOTHING_WIDENS.fields[0]!, source_has_column: false }] })
    expect(screen.getByText(/the source table has no such column\. Add it there first/)).toBeInTheDocument()
  })

  it('says when the source could not be asked, rather than guessing', async () => {
    await review({ ...NOTHING_WIDENS, fields: [{ ...NOTHING_WIDENS.fields[0]!, source_has_column: null }] })
    expect(screen.getByText(/the source could not be asked, so this is not checked\./)).toBeInTheDocument()
    expect(screen.queryByText(/the source table has/)).not.toBeInTheDocument()
  })

  it('names the column it reads, which is not always its own name', async () => {
    await review({ ...NOTHING_WIDENS, fields: [{ ...NOTHING_WIDENS.fields[0]!, column: 'Nick Name' }] })
    expect(screen.getByText('Nick Name')).toBeInTheDocument()
  })

  it('says nobody can read it yet, and that the lake rebuilds the type', async () => {
    await review()
    expect(screen.getByText(/Nobody can read it until a grant names it/)).toBeInTheDocument()
    // WHO CAN MAKE THE FIRST GRANT, said, because nobody holds a new field.
    expect(screen.getByText(/first grant of it has to come from someone holding manage:escalation/)).toBeInTheDocument()
    expect(screen.getByText(/lake’s Customer table is rebuilt to include it/)).toBeInTheDocument()
    expect(screen.getByText(/records no history of changes/)).toBeInTheDocument()
  })

  it('shows the lines that would be added', async () => {
    await review()
    // getByText collapses runs of spaces, so the indent reads as one.
    expect(screen.getByText(/\+ nickname:/)).toBeInTheDocument()
  })

  it('going back keeps what was typed, and changing it asks for a new review', async () => {
    await review()
    fireEvent.click(screen.getByRole('button', { name: 'Back' }))

    expect(screen.getByLabelText('Name')).toHaveValue('nickname')
    expect(screen.queryByText('What else this does')).not.toBeInTheDocument()
  })
})

describe('applying', () => {
  it('a field that widens nothing applies without asking why', async () => {
    const { onApplied } = renderDialog()
    await screen.findByLabelText('Name')
    typeInto('Name', 'nickname')
    fireEvent.click(screen.getByRole('button', { name: 'Review' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Apply and reload' }))

    await waitFor(() => expect(onApplied).toHaveBeenCalledWith(12))
    expect(screen.queryByLabelText(/Why/)).not.toBeInTheDocument()
    expect(mockedApply).toHaveBeenCalledWith(
      'd1',
      [{ object_type: 'Customer', name: 'nickname', data_type: 'string' }],
      null,
    )
  })

  it('one a grant already names waits, and will not propose without a reason', async () => {
    mockedPreview.mockResolvedValue(WIDENS)
    mockedApply.mockResolvedValue({ status: 'waiting', diff: [], proposal_id: 'p1' })
    const { onProposed, onApplied } = renderDialog()
    await screen.findByLabelText('Name')
    typeInto('Name', 'nickname')
    fireEvent.click(screen.getByRole('button', { name: 'Review' }))

    expect(await screen.findByText('This waits for a second person')).toBeInTheDocument()
    expect(screen.getByText('Can now read Customer.nickname')).toBeInTheDocument()
    const propose = screen.getByRole('button', { name: 'Propose for approval' })
    expect(propose).toBeDisabled()

    fireEvent.change(screen.getByLabelText(/Why/), { target: { value: '  We hold nicknames now.  ' } })
    fireEvent.click(propose)

    await waitFor(() => expect(onProposed).toHaveBeenCalled())
    expect(onApplied).not.toHaveBeenCalled()
    expect(mockedApply).toHaveBeenCalledWith(
      'd1',
      [{ object_type: 'Customer', name: 'nickname', data_type: 'string' }],
      'We hold nicknames now.',
    )
  })
})

describe('several fields', () => {
  it('another field adds a form, and each can be removed once there are two', async () => {
    renderDialog()
    await screen.findByLabelText('Name')
    expect(screen.queryByRole('button', { name: 'Remove' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Another field' }))

    expect(screen.getAllByLabelText('Name')).toHaveLength(2)
    typeInto('Name', 'first', 0)
    typeInto('Name', 'second', 1)
    fireEvent.click(screen.getAllByRole('button', { name: 'Remove' })[0]!)

    expect(screen.getAllByLabelText('Name')).toHaveLength(1)
    expect(screen.getByLabelText('Name')).toHaveValue('second')
  })

  it('sends them in order, and says "them" when there are several', async () => {
    mockedPreview.mockResolvedValue({
      ...NOTHING_WIDENS,
      fields: [
        { object_type: 'Customer', field: 'a', column: 'a', source_has_column: true },
        { object_type: 'Customer', field: 'b', column: 'b', source_has_column: true },
      ],
    })
    renderDialog()
    await screen.findByLabelText('Name')
    fireEvent.click(screen.getByRole('button', { name: 'Another field' }))
    typeInto('Name', 'a', 0)
    typeInto('Name', 'b', 1)
    fireEvent.click(screen.getByRole('button', { name: 'Review' }))

    await screen.findByText('What else this does')
    expect(mockedPreview.mock.calls[0]![1].map((field) => field.name)).toEqual(['a', 'b'])
    expect(screen.getByText(/Nobody can read them until a grant names each/)).toBeInTheDocument()
    expect(screen.getByText(/Customer table is rebuilt to include them\./)).toBeInTheDocument()
  })

  it('stops offering another field at eight', async () => {
    renderDialog()
    await screen.findByLabelText('Name')
    for (let count = 1; count < 8; count++) fireEvent.click(screen.getByRole('button', { name: 'Another field' }))

    expect(screen.getAllByLabelText('Name')).toHaveLength(8)
    expect(screen.queryByRole('button', { name: 'Another field' })).not.toBeInTheDocument()
  })

  it('a blank second field stops the review', async () => {
    renderDialog()
    await screen.findByLabelText('Name')
    typeInto('Name', 'a')
    fireEvent.click(screen.getByRole('button', { name: 'Another field' }))

    expect(screen.getByRole('button', { name: 'Review' })).toBeDisabled()
  })
})

describe('when the file moved or the server refuses', () => {
  it('a 409 keeps what was typed and loads the file again on request', async () => {
    mockedPreview.mockRejectedValueOnce(new ApiError(409, 'ontology_schema.yaml has changed since you opened it.'))
    renderDialog()
    await screen.findByLabelText('Name')
    typeInto('Name', 'nickname')
    fireEvent.click(screen.getByRole('button', { name: 'Review' }))

    expect(
      await screen.findByText(/has changed since you opened it\. What you typed is still here/),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Review' })).toBeDisabled()
    expect(screen.getByLabelText('Name')).toHaveValue('nickname')

    mockedGet.mockResolvedValue({ ...DESCRIPTIONS, digest: 'd2' })
    fireEvent.click(screen.getByRole('button', { name: 'Load the file again' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Review' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Review' }))

    await waitFor(() => expect(mockedPreview).toHaveBeenLastCalledWith('d2', expect.any(Array)))
  })

  it('the server’s reason for a refusal is shown, and the form stays', async () => {
    mockedPreview.mockRejectedValueOnce(new ApiError(400, 'Customer.name is already a field of Customer.'))
    renderDialog()
    await screen.findByLabelText('Name')
    typeInto('Name', 'name')
    fireEvent.click(screen.getByRole('button', { name: 'Review' }))

    expect(await screen.findByText('Customer.name is already a field of Customer.')).toBeInTheDocument()
    expect(screen.getByLabelText('Name')).toHaveValue('name')
  })

  it('typing again clears a refusal that no longer applies', async () => {
    mockedPreview.mockRejectedValueOnce(new ApiError(400, 'Customer.name is already a field of Customer.'))
    renderDialog()
    await screen.findByLabelText('Name')
    typeInto('Name', 'name')
    fireEvent.click(screen.getByRole('button', { name: 'Review' }))
    await screen.findByText('Customer.name is already a field of Customer.')

    typeInto('Name', 'nickname')

    expect(screen.queryByText('Customer.name is already a field of Customer.')).not.toBeInTheDocument()
  })

  it('a refusal on applying sends you back to the form with its reason', async () => {
    mockedApply.mockRejectedValueOnce(new ApiError(400, 'Say why.'))
    renderDialog()
    await screen.findByLabelText('Name')
    typeInto('Name', 'nickname')
    fireEvent.click(screen.getByRole('button', { name: 'Review' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Apply and reload' }))

    expect(await screen.findByText('Say why.')).toBeInTheDocument()
    expect(screen.getByLabelText('Name')).toHaveValue('nickname')
    expect(screen.queryByText('What else this does')).not.toBeInTheDocument()
  })

  it('cancel closes without calling anything', async () => {
    const { onClose } = renderDialog()
    await screen.findByLabelText('Name')
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(onClose).toHaveBeenCalled()
    expect(mockedPreview).not.toHaveBeenCalled()
  })
})
