import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

vi.mock('@elysium/shell-api/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@elysium/shell-api/api')>()),
  getOntologyDescriptions: vi.fn(),
  previewLabels: vi.fn(),
  applyLabels: vi.fn(),
}))

import {
  applyLabels,
  getOntologyDescriptions,
  type LabelPreview,
  type OntologyDescriptions,
  previewLabels,
} from '@elysium/shell-api/api'
import LabelFields from './LabelFields'

const mockedGet = vi.mocked(getOntologyDescriptions)
const mockedPreview = vi.mocked(previewLabels)
const mockedApply = vi.mocked(applyLabels)

const field = (labels: string[]) => ({ display_name: null, description: null, kind: 'data', labels })

/** Shaped as GET /admin/ontology/descriptions returns it. */
const DESCRIPTIONS: OntologyDescriptions = {
  digest: 'd1',
  label_enforcement: true,
  data_types: ['string', 'integer'],
  types: {
    Customer: {
      display_name: 'Customer',
      plural_display_name: null,
      description: null,
      group: null,
      title_field: null,
      fields: { name: field([]), email: field(['pii']) },
    },
    Account: {
      display_name: null,
      plural_display_name: null,
      description: null,
      group: null,
      title_field: null,
      fields: { balance: field(['financial']) },
    },
  },
}

const ROLE = {
  role: 'customer_service',
  holders: 3,
  removes_role: false,
  types_gained: [],
  types_lost: [],
  fields_gained: [{ type: 'Customer', field: 'email', from: 'discover' as const, to: 'read' as const }],
  fields_lost: [],
  actions_gained: [],
  actions_lost: [],
  other_gained: [],
  other_lost: [],
}

const WIDENS: LabelPreview = {
  diff: ['--- a', '+++ b', '-        classification: pii'],
  impact: { widens: true, roles: [ROLE] },
  needs_approval: true,
  label_enforcement: true,
}

function renderDialog() {
  const onApplied = vi.fn()
  const onProposed = vi.fn()
  render(
    <LabelFields
      objectType="Customer"
      shownAs="Customer"
      onClose={vi.fn()}
      onApplied={onApplied}
      onProposed={onProposed}
      onSessionExpired={vi.fn()}
    />,
  )
  return { onApplied, onProposed }
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedGet.mockResolvedValue(DESCRIPTIONS)
  mockedPreview.mockResolvedValue(WIDENS)
  mockedApply.mockResolvedValue({ status: 'waiting', diff: [], proposal_id: 'p1' })
})

describe('access labels', () => {
  it('says whether labels decide access here, and which labels are in use', async () => {
    renderDialog()

    expect(await screen.findByText('Labels decide access here')).toBeInTheDocument()
    expect(screen.getByText(/In use: financial, pii\./)).toBeInTheDocument()
    expect(screen.getByLabelText('email labels')).toHaveValue('pii')
  })

  it('when labels only describe, it says changes apply at once', async () => {
    mockedGet.mockResolvedValue({ ...DESCRIPTIONS, label_enforcement: false })
    renderDialog()

    expect(await screen.findByText('Labels describe, here')).toBeInTheDocument()
  })

  it('sends each changed field as its whole list, an emptied one as none', async () => {
    renderDialog()
    fireEvent.change(await screen.findByLabelText('email labels'), { target: { value: '' } })
    fireEvent.change(screen.getByLabelText('name labels'), { target: { value: 'pii, contact ,' } })
    fireEvent.click(screen.getByRole('button', { name: 'Review 2 changes' }))

    await waitFor(() =>
      expect(mockedPreview).toHaveBeenCalledWith('d1', [
        { object_type: 'Customer', field: 'name', labels: ['pii', 'contact'] },
        { object_type: 'Customer', field: 'email', labels: [] },
      ]),
    )
  })

  it('a widening shows who gains what, and will not propose without a reason', async () => {
    const { onProposed } = renderDialog()
    fireEvent.change(await screen.findByLabelText('email labels'), { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: 'Review 1 change' }))

    expect(await screen.findByText('Can now read Customer.email')).toBeInTheDocument()
    expect(screen.getByText('This waits for a second person')).toBeInTheDocument()
    const propose = screen.getByRole('button', { name: 'Propose for approval' })
    expect(propose).toBeDisabled()

    fireEvent.change(screen.getByLabelText(/Why/), { target: { value: 'Not personal in this business.' } })
    fireEvent.click(propose)

    await waitFor(() => expect(onProposed).toHaveBeenCalled())
    expect(mockedApply).toHaveBeenCalledWith(
      'd1',
      [{ object_type: 'Customer', field: 'email', labels: [] }],
      'Not personal in this business.',
    )
  })

  it('a change that widens nothing applies, without asking why', async () => {
    mockedPreview.mockResolvedValue({ ...WIDENS, impact: { widens: false, roles: [] }, needs_approval: false })
    mockedApply.mockResolvedValue({ status: 'applied', diff: [], to_generation: 12 })
    const { onApplied } = renderDialog()
    fireEvent.change(await screen.findByLabelText('name labels'), { target: { value: 'pii' } })
    fireEvent.click(screen.getByRole('button', { name: 'Review 1 change' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Apply and reload' }))

    await waitFor(() => expect(onApplied).toHaveBeenCalledWith(12))
    expect(screen.queryByLabelText(/Why/)).not.toBeInTheDocument()
    expect(mockedApply).toHaveBeenCalledWith('d1', [{ object_type: 'Customer', field: 'name', labels: ['pii'] }], null)
  })
})
