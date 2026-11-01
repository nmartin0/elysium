import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

vi.mock('@elysium/shell-api/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@elysium/shell-api/api')>()),
  getOntologyDescriptions: vi.fn(),
  previewStatus: vi.fn(),
  applyStatus: vi.fn(),
}))

import {
  ApiError,
  applyStatus,
  getOntologyDescriptions,
  previewStatus,
  type StatusPreview,
} from '@elysium/shell-api/api'
import type { TypeSchema, VisibleSchema } from '@elysium/shell-api/types'
import DeprecateDialog, { type DeprecateTarget } from './Deprecate'

const CUSTOMER_TYPE: TypeSchema = {
  display_name: 'Customer',
  status: 'active',
  fields: {
    name: { type: 'data', display_name: 'Name', status: 'active' },
    email: { type: 'data', display_name: 'Email', status: 'active' },
    phone: { type: 'data', display_name: 'Phone', status: 'deprecated' },
    transactions: { type: 'link', link_type: 'CustomerTransactions', target: 'Transaction', status: 'active' },
    tags: { type: 'link', link_type: 'CustomerTags', target: 'Tag', status: 'deprecated' },
  },
}

const SCHEMA: VisibleSchema = {
  Customer: CUSTOMER_TYPE,
  Transaction: { display_name: 'Transaction', status: 'active', fields: {} },
  Tag: { display_name: 'Tag', status: 'deprecated', fields: {} },
}

const PREVIEW: StatusPreview = {
  diff: ['+        status: deprecated'],
  impact: { widens: false, roles: [] },
  needs_approval: false,
}

function renderDialog(target: DeprecateTarget, schema: VisibleSchema = SCHEMA, onApplied = vi.fn()) {
  render(
    <DeprecateDialog
      schema={schema}
      target={target}
      onClose={vi.fn()}
      onApplied={onApplied}
      onSessionExpired={vi.fn()}
    />,
  )
  return onApplied
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(getOntologyDescriptions).mockResolvedValue({
    digest: 'd1',
    types: {},
    data_types: ['string'],
    label_enforcement: false,
  })
  vi.mocked(previewStatus).mockResolvedValue(PREVIEW)
  vi.mocked(applyStatus).mockResolvedValue({ status: 'applied', diff: [], to_generation: 7 })
})

const reviewButton = () => screen.findByRole('button', { name: 'Review' })

describe('deprecating a field', () => {
  it('names what is being deprecated and will not review without a reason', async () => {
    renderDialog({ objectType: 'Customer', field: 'email' })

    expect(await screen.findByRole('dialog', { name: 'Deprecate Customer.Email' })).toBeInTheDocument()
    expect(await reviewButton()).toBeDisabled()
    fireEvent.change(screen.getByLabelText(/Why it is deprecated/), { target: { value: 'Replaced by name.' } })
    expect(await reviewButton()).toBeEnabled()
  })

  it('offers only stored, active fields of the same type as the replacement', async () => {
    renderDialog({ objectType: 'Customer', field: 'email' })

    const choices = Array.from(
      (await screen.findByLabelText('What to use instead')).querySelectorAll('option'),
      (option) => option.textContent,
    )
    expect(choices).toEqual(['Nothing in particular', 'Name'])
  })

  it('sends exactly what was entered and shows the consequences and the lines', async () => {
    renderDialog({ objectType: 'Customer', field: 'email' })
    fireEvent.change(await screen.findByLabelText(/Why it is deprecated/), { target: { value: ' Replaced by name. ' } })
    fireEvent.change(screen.getByLabelText('What to use instead'), { target: { value: 'name' } })
    fireEvent.change(screen.getByLabelText('Removal planned after'), { target: { value: '2027-03-31' } })

    fireEvent.click(await reviewButton())

    expect(await screen.findByText('Data is not touched, and no grant changes.')).toBeInTheDocument()
    expect(screen.getByText(/status: deprecated/)).toBeInTheDocument()
    expect(previewStatus).toHaveBeenCalledWith('d1', {
      kind: 'field',
      object_type: 'Customer',
      field: 'email',
      status: 'deprecated',
      reason: 'Replaced by name.',
      replaced_by: 'name',
      remove_after: '2027-03-31',
    })
  })

  it('applies what was reviewed and tells the screen which generation it became', async () => {
    const onApplied = renderDialog({ objectType: 'Customer', field: 'email' })
    fireEvent.change(await screen.findByLabelText(/Why it is deprecated/), { target: { value: 'Gone.' } })
    fireEvent.click(await reviewButton())

    fireEvent.click(await screen.findByRole('button', { name: 'Make it deprecated and reload' }))

    await waitFor(() => expect(onApplied).toHaveBeenCalledWith(7))
    expect(applyStatus).toHaveBeenCalledWith('d1', {
      kind: 'field',
      object_type: 'Customer',
      field: 'email',
      status: 'deprecated',
      reason: 'Gone.',
    })
  })

  it('says a stale file needs loading again and keeps what was typed', async () => {
    vi.mocked(previewStatus).mockRejectedValue(new ApiError(409, 'The file changed since you read it.'))
    renderDialog({ objectType: 'Customer', field: 'email' })
    fireEvent.change(await screen.findByLabelText(/Why it is deprecated/), { target: { value: 'Gone.' } })

    fireEvent.click(await reviewButton())

    expect(
      await screen.findByText(/The file changed since you read it\. What you typed is still here/),
    ).toBeInTheDocument()
    expect(screen.getByLabelText(/Why it is deprecated/)).toHaveValue('Gone.')
    expect(screen.getByRole('button', { name: 'Load the file again' })).toBeInTheDocument()
  })
})

describe('a field that is already deprecated', () => {
  const DEPRECATED: VisibleSchema = {
    ...SCHEMA,
    Customer: {
      ...CUSTOMER_TYPE,
      fields: {
        ...CUSTOMER_TYPE.fields,
        email: {
          type: 'data',
          display_name: 'Email',
          status: 'deprecated',
          deprecation: { reason: 'Replaced by name.', replaced_by: 'name', remove_after: '2027-03-31' },
        },
      },
    },
  }

  it('shows what was said and can put it back', async () => {
    renderDialog({ objectType: 'Customer', field: 'email' }, DEPRECATED)

    expect(await screen.findByRole('dialog', { name: 'Deprecation of Customer.Email' })).toBeInTheDocument()
    expect(screen.getByLabelText(/Why it is deprecated/)).toHaveValue('Replaced by name.')
    expect(screen.getByLabelText('What to use instead')).toHaveValue('name')
    expect(screen.getByLabelText('Removal planned after')).toHaveValue('2027-03-31')

    fireEvent.click(await screen.findByRole('button', { name: 'Make it active again' }))
    await screen.findByText('Customer.Email stops being marked, and its reason is taken out.')
    fireEvent.click(screen.getByRole('button', { name: 'Make it active again and reload' }))

    await waitFor(() =>
      expect(applyStatus).toHaveBeenCalledWith('d1', {
        kind: 'field',
        object_type: 'Customer',
        field: 'email',
        status: 'active',
      }),
    )
  })
})

describe('deprecating a type', () => {
  it('offers the other types that are not deprecated, and says its links follow', async () => {
    renderDialog({ objectType: 'Customer' })
    fireEvent.change(await screen.findByLabelText(/Why it is deprecated/), { target: { value: 'Retiring.' } })
    const choices = Array.from(
      screen.getByLabelText('What to use instead').querySelectorAll('option'),
      (option) => option.textContent,
    )

    fireEvent.click(await reviewButton())

    expect(choices).toEqual(['Nothing in particular', 'Transaction'])
    expect(await screen.findByText('Its links read as deprecated too, until they are taken out.')).toBeInTheDocument()
    expect(previewStatus).toHaveBeenCalledWith('d1', {
      kind: 'type',
      object_type: 'Customer',
      status: 'deprecated',
      reason: 'Retiring.',
    })
  })
})

describe('deprecating a link', () => {
  it('offers the other link types that are not deprecated', async () => {
    renderDialog({ link: 'CustomerTransactions' })

    expect(await screen.findByRole('dialog', { name: 'Deprecate link CustomerTransactions' })).toBeInTheDocument()
    const choices = Array.from(
      screen.getByLabelText('What to use instead').querySelectorAll('option'),
      (option) => option.textContent,
    )
    expect(choices).toEqual(['Nothing in particular'])
  })

  it('says a link that follows its type is not deprecated on its own, and cannot be put back from here', async () => {
    const FOLLOWING: VisibleSchema = {
      ...SCHEMA,
      Customer: {
        ...CUSTOMER_TYPE,
        fields: {
          ...CUSTOMER_TYPE.fields,
          transactions: {
            type: 'link',
            link_type: 'CustomerTransactions',
            target: 'Transaction',
            status: 'deprecated',
            status_inherited_from: 'Customer',
          },
        },
      },
    }
    renderDialog({ link: 'CustomerTransactions' }, FOLLOWING)

    expect(await screen.findByText(/already reads as deprecated because Customer is/)).toBeInTheDocument()
    expect(screen.getByRole('dialog', { name: 'Deprecate link CustomerTransactions' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Make it active again' })).not.toBeInTheDocument()
  })
})
