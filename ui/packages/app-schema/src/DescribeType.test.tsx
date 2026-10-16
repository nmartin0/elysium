import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

vi.mock('@elysium/shell-api/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@elysium/shell-api/api')>()),
  getOntologyDescriptions: vi.fn(),
  previewOntologyDescriptions: vi.fn(),
  applyOntologyDescriptions: vi.fn(),
}))

import {
  ApiError,
  applyOntologyDescriptions,
  getOntologyDescriptions,
  type OntologyDescriptions,
  previewOntologyDescriptions,
} from '@elysium/shell-api/api'
import DescribeType from './DescribeType'

const mockedGet = vi.mocked(getOntologyDescriptions)
const mockedPreview = vi.mocked(previewOntologyDescriptions)
const mockedApply = vi.mocked(applyOntologyDescriptions)

/** Shaped as GET /admin/ontology/descriptions returns it. */
const DESCRIPTIONS: OntologyDescriptions = {
  digest: 'd1',
  label_enforcement: false,
  types: {
    Customer: {
      display_name: 'Customer',
      plural_display_name: null,
      description: 'Someone we serve.',
      group: 'People',
      title_field: 'name',
      fields: {
        name: { display_name: null, description: null, kind: 'data', labels: [] },
        email: { display_name: 'Email', description: null, kind: 'data', labels: [] },
        account: { display_name: null, description: null, kind: 'link', labels: [] },
      },
    },
    Account: {
      display_name: null,
      plural_display_name: null,
      description: null,
      group: 'Money',
      title_field: null,
      fields: {},
    },
  },
}

function renderDialog() {
  const onApplied = vi.fn()
  render(
    <DescribeType
      objectType="Customer"
      shownAs="Customer"
      onClose={vi.fn()}
      onApplied={onApplied}
      onSessionExpired={vi.fn()}
    />,
  )
  return { onApplied }
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedGet.mockResolvedValue(DESCRIPTIONS)
  mockedPreview.mockResolvedValue([
    '--- a',
    '+++ b',
    '-    description: Someone we serve.',
    '+    description: A person.',
  ])
  mockedApply.mockResolvedValue({ diff: [], digest: 'd2', to_generation: 9 })
})

describe('describing a type', () => {
  it('starts from what the file declares, and absent as empty', async () => {
    renderDialog()

    expect(await screen.findByLabelText('Description')).toHaveValue('Someone we serve.')
    expect(screen.getByLabelText('Plural')).toHaveValue('')
    expect(screen.getByLabelText('email name')).toHaveValue('Email')
  })

  it('offers only data fields as the title', async () => {
    renderDialog()
    const title = await screen.findByLabelText('Title')

    const options = [...title.querySelectorAll('option')].map((option) => option.getAttribute('value'))
    expect(options).toEqual(['', 'name', 'email'])
  })

  it('sends only what changed, and shows the lines before anything is written', async () => {
    renderDialog()
    fireEvent.change(await screen.findByLabelText('Description'), { target: { value: 'A person.' } })
    fireEvent.change(screen.getByLabelText('name description'), { target: { value: 'What they are called' } })

    fireEvent.click(screen.getByRole('button', { name: 'Review 2 changes' }))

    expect(await screen.findByText('+ description: A person.')).toBeInTheDocument()
    expect(mockedPreview).toHaveBeenCalledWith('d1', [
      { object_type: 'Customer', field: null, key: 'description', value: 'A person.' },
      { object_type: 'Customer', field: 'name', key: 'description', value: 'What they are called' },
    ])
    expect(mockedApply).not.toHaveBeenCalled()
  })

  it('applies with the digest it read, and reports the generation', async () => {
    const { onApplied } = renderDialog()
    fireEvent.change(await screen.findByLabelText('Group'), { target: { value: 'Customers' } })
    fireEvent.click(screen.getByRole('button', { name: 'Review 1 change' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Apply and reload' }))

    await waitFor(() => expect(onApplied).toHaveBeenCalledWith(9))
    expect(mockedApply).toHaveBeenCalledWith('d1', [
      { object_type: 'Customer', field: null, key: 'group', value: 'Customers' },
    ])
  })

  it('an emptied box removes the key rather than sending an empty string', async () => {
    renderDialog()
    fireEvent.change(await screen.findByLabelText('Description'), { target: { value: '   ' } })
    fireEvent.click(screen.getByRole('button', { name: 'Review 1 change' }))

    await waitFor(() =>
      expect(mockedPreview).toHaveBeenCalledWith('d1', [
        { object_type: 'Customer', field: null, key: 'description', value: null },
      ]),
    )
  })

  it('typing back what the file says is no change', async () => {
    renderDialog()
    const description = await screen.findByLabelText('Description')
    fireEvent.change(description, { target: { value: 'Other.' } })
    fireEvent.change(description, { target: { value: ' Someone we serve. ' } })

    expect(screen.getByRole('button', { name: 'Review changes' })).toBeDisabled()
  })

  it('a pasted paragraph becomes one line, as the file holds it', async () => {
    renderDialog()
    fireEvent.change(await screen.findByLabelText('Description'), { target: { value: 'One.\n\n  Two.' } })

    expect(screen.getByLabelText('Description')).toHaveValue('One. Two.')
  })

  it('a file changed underneath keeps what was typed, and loads again on request', async () => {
    mockedPreview.mockRejectedValueOnce(new ApiError(409, 'ontology_schema.yaml has changed since you opened it.'))
    renderDialog()
    fireEvent.change(await screen.findByLabelText('Group'), { target: { value: 'Customers' } })
    fireEvent.click(screen.getByRole('button', { name: 'Review 1 change' }))

    expect(await screen.findByText(/Your changes are still here/)).toBeInTheDocument()
    mockedGet.mockResolvedValue({ ...DESCRIPTIONS, digest: 'd3' })
    fireEvent.click(screen.getByRole('button', { name: 'Load the file again' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Review 1 change' }))

    await waitFor(() =>
      expect(mockedPreview).toHaveBeenLastCalledWith('d3', [
        { object_type: 'Customer', field: null, key: 'group', value: 'Customers' },
      ]),
    )
  })

  it('a refusal is said, not swallowed', async () => {
    mockedPreview.mockRejectedValueOnce(new ApiError(400, "Customer's display_name is at most 80 characters."))
    renderDialog()
    fireEvent.change(await screen.findByLabelText('Name'), { target: { value: 'Client' } })
    fireEvent.click(screen.getByRole('button', { name: 'Review 1 change' }))

    expect(await screen.findByText(/at most 80 characters/)).toBeInTheDocument()
  })
})
