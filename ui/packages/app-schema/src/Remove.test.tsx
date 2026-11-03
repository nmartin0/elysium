import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

vi.mock('@elysium/shell-api/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@elysium/shell-api/api')>()),
  getOntologyDescriptions: vi.fn(),
  previewRemoval: vi.fn(),
  applyRemoval: vi.fn(),
}))

import {
  ApiError,
  applyRemoval,
  getOntologyDescriptions,
  previewRemoval,
  type RemovalPreview,
} from '@elysium/shell-api/api'
import type { VisibleSchema } from '@elysium/shell-api/types'
import RemoveDialog, { type RemoveTarget } from './Remove'

const SCHEMA: VisibleSchema = {
  Customer: {
    display_name: 'Customer',
    status: 'active',
    fields: { email: { type: 'data', display_name: 'Email', status: 'deprecated' } },
  },
}

const READY: RemovalPreview = {
  diff: ['-      email:', '-        type: data'],
  impact: { widens: false, roles: [] },
  can_remove: true,
  deprecated: true,
  remove_after: null,
  blockers: [],
  hidden_blockers: 0,
  not_listed: 'Saved views and notes are not listed here yet.',
  stored_data: ['Nothing is deleted from your source: Elysium only reads it.', 'Gold is rebuilt without the column.'],
}

const BLOCKED: RemovalPreview = {
  ...READY,
  can_remove: false,
  impact: null,
  blockers: [
    { kind: 'grant', place: 'role customer_service', says: 'has 1 grant naming it: read:Customer.email' },
    { kind: 'action', place: 'action CreateCustomer', says: 'sets Customer.email' },
  ],
}

const FIELD: RemoveTarget = { objectType: 'Customer', field: 'email' }

function renderDialog(target: RemoveTarget = FIELD, onApplied = vi.fn()) {
  render(
    <RemoveDialog schema={SCHEMA} target={target} onClose={vi.fn()} onApplied={onApplied} onSessionExpired={vi.fn()} />,
  )
  return onApplied
}

const removeButton = () => screen.findByRole('button', { name: 'Remove it and reload' })

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(getOntologyDescriptions).mockResolvedValue({
    digest: 'd1',
    types: {},
    data_types: ['string'],
    label_enforcement: false,
  })
  vi.mocked(previewRemoval).mockResolvedValue(READY)
  vi.mocked(applyRemoval).mockResolvedValue({ status: 'applied', diff: [], to_generation: 7 })
})

describe('a field that can go', () => {
  it('previews as soon as it opens, naming the field and asking for exactly it', async () => {
    renderDialog()

    expect(await screen.findByRole('dialog', { name: 'Remove Customer.Email' })).toBeInTheDocument()
    await waitFor(() =>
      expect(previewRemoval).toHaveBeenCalledWith('d1', { kind: 'field', object_type: 'Customer', field: 'email' }),
    )
  })

  it('says what becomes of the stored data, in the words the server gave, and shows the lines that go', async () => {
    renderDialog()

    expect(await screen.findByText('Nothing is deleted from your source: Elysium only reads it.')).toBeInTheDocument()
    expect(screen.getByText('Gold is rebuilt without the column.')).toBeInTheDocument()
    expect(screen.getByText(/-\s+email:/)).toBeInTheDocument()
    expect(screen.getByText('Saved views and notes are not listed here yet.')).toBeInTheDocument()
  })

  it('applies exactly what was previewed and tells the screen which generation it became', async () => {
    const onApplied = renderDialog()

    fireEvent.click(await removeButton())

    await waitFor(() => expect(onApplied).toHaveBeenCalledWith(7))
    expect(applyRemoval).toHaveBeenCalledWith('d1', { kind: 'field', object_type: 'Customer', field: 'email' })
  })

  it('stays open on the notice when the server could not record what an erasure will need', async () => {
    vi.mocked(applyRemoval).mockResolvedValue({
      status: 'applied',
      diff: [],
      to_generation: 9,
      notice: 'A sync was running, so the tables were not recorded.',
    })
    const onApplied = renderDialog()

    fireEvent.click(await removeButton())

    expect(await screen.findByText(/A sync was running, so the tables were not recorded/)).toBeInTheDocument()
    expect(onApplied).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Done' }))
    expect(onApplied).toHaveBeenCalledWith(9)
  })

  it('warns when the planned date has not come, and still allows it', async () => {
    vi.mocked(previewRemoval).mockResolvedValue({ ...READY, remove_after: '2999-01-01' })
    renderDialog()

    expect(await screen.findByText(/Removal was planned after 2999-01-01, which has not come yet/)).toBeInTheDocument()
    expect(await removeButton()).toBeEnabled()
  })

  it('does not warn once the planned date has passed', async () => {
    vi.mocked(previewRemoval).mockResolvedValue({ ...READY, remove_after: '2000-01-01' })
    renderDialog()

    await removeButton()
    expect(screen.queryByText(/has not come yet/)).not.toBeInTheDocument()
  })
})

describe('a link type', () => {
  it('asks for the link, not a field', async () => {
    renderDialog({ link: 'CustomerTags' })

    expect(await screen.findByRole('dialog', { name: 'Remove link CustomerTags' })).toBeInTheDocument()
    await waitFor(() => expect(previewRemoval).toHaveBeenCalledWith('d1', { kind: 'link', link: 'CustomerTags' }))
  })
})

describe('a name that is not deprecated', () => {
  beforeEach(() => {
    vi.mocked(previewRemoval).mockResolvedValue({ ...READY, deprecated: false, can_remove: false, impact: null })
  })

  it('says to deprecate it first, offers no list of consequences, and cannot be removed', async () => {
    renderDialog()

    expect(await screen.findByText(/is not deprecated\. Removing is the last of three steps/)).toBeInTheDocument()
    expect(screen.queryByText('Gold is rebuilt without the column.')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Remove it and reload' })).toBeDisabled()
  })
})

describe('a name something still names', () => {
  it('lists what names it and cannot be removed', async () => {
    vi.mocked(previewRemoval).mockResolvedValue(BLOCKED)
    renderDialog()

    expect(await screen.findByText('role customer_service')).toBeInTheDocument()
    expect(screen.getByText('sets Customer.email')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Remove it and reload' })).toBeDisabled()
    expect(screen.queryByText('Gold is rebuilt without the column.')).not.toBeInTheDocument()
  })

  it('counts what names something the person cannot see, and says someone else must clear it', async () => {
    vi.mocked(previewRemoval).mockResolvedValue({ ...BLOCKED, hidden_blockers: 2 })
    renderDialog()

    expect(await screen.findByText(/2 more places name something you cannot see in Schema/)).toBeInTheDocument()
  })

  it('is refused when only the places they cannot see name it', async () => {
    vi.mocked(previewRemoval).mockResolvedValue({ ...BLOCKED, blockers: [], hidden_blockers: 1 })
    renderDialog()

    expect(await screen.findByText(/One more place names something you cannot see in Schema/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Remove it and reload' })).toBeDisabled()
  })

  it('shows what names it now when applying finds something the preview did not', async () => {
    vi.mocked(applyRemoval).mockRejectedValue(
      new ApiError(409, 'Something still names Customer.email. Nothing was changed.', {
        detail: 'Something still names Customer.email. Nothing was changed.',
        deprecated: true,
        hidden_blockers: 0,
        blockers: [{ kind: 'grant', place: 'role editor', says: 'has 1 grant naming it: read:Customer.email' }],
      }),
    )
    const onApplied = renderDialog()

    fireEvent.click(await removeButton())

    expect(await screen.findByText('role editor')).toBeInTheDocument()
    expect(screen.getByText(/Something still names Customer\.email\. Nothing was changed\./)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Remove it and reload' })).toBeDisabled()
    expect(onApplied).not.toHaveBeenCalled()
  })
})

describe('when the file has changed or the name is gone', () => {
  it('says a stale file needs loading again, and loading again previews again', async () => {
    vi.mocked(applyRemoval).mockRejectedValue(
      new ApiError(
        409,
        'ontology_schema.yaml has changed since you opened it. Load it again to see the new version before changing it.',
        { detail: 'x' },
      ),
    )
    renderDialog()
    fireEvent.click(await removeButton())

    expect(await screen.findByText(/has changed since you opened it/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Remove it and reload' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Load the file again' }))

    await waitFor(() => expect(previewRemoval).toHaveBeenCalledTimes(2))
    expect(await removeButton()).toBeEnabled()
  })

  it("shows the server's sentence for a widening or an unloadable plan, and does not offer to load again", async () => {
    const sentence =
      'This would let someone read more than they can now, which a removal never should. Nothing was changed.'
    vi.mocked(applyRemoval).mockRejectedValue(new ApiError(409, sentence, { detail: sentence }))
    renderDialog()
    fireEvent.click(await removeButton())

    expect(await screen.findByText(sentence)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Load the file again' })).not.toBeInTheDocument()
  })

  it('says comments stay, when it can go', async () => {
    renderDialog()

    expect(await screen.findByText(/comments in the file stay where they are/)).toBeInTheDocument()
  })

  it('shows "Not found" as it is, and offers no removal', async () => {
    vi.mocked(previewRemoval).mockRejectedValue(new ApiError(404, 'Not found'))
    renderDialog()

    expect(await screen.findByText('Not found')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Remove it and reload' })).toBeDisabled()
  })
})

describe('a whole object type', () => {
  const TYPE: RemoveTarget = { objectType: 'Tag' }
  const SCHEMA_WITH_TAG: VisibleSchema = {
    ...SCHEMA,
    Tag: { display_name: 'Label', status: 'deprecated', fields: {} },
  }
  const LINKED: RemovalPreview = {
    ...READY,
    can_remove: false,
    impact: null,
    blockers: [{ kind: 'link', place: 'link CustomerTags', says: 'joins Customer.tags and Tag.customers' }],
    hidden_blockers: 1,
  }

  const open = (preview: RemovalPreview = READY) => {
    vi.mocked(previewRemoval).mockResolvedValue(preview)
    render(
      <RemoveDialog
        schema={SCHEMA_WITH_TAG}
        target={TYPE}
        onClose={vi.fn()}
        onApplied={vi.fn()}
        onSessionExpired={vi.fn()}
      />,
    )
  }

  it('asks the server about the type by its name alone', async () => {
    open()

    expect(await screen.findByRole('dialog', { name: 'Remove type Label' })).toBeInTheDocument()
    await waitFor(() => expect(previewRemoval).toHaveBeenCalledWith('d1', { kind: 'type', object_type: 'Tag' }))
  })

  it("says the binding goes too, and shows the server's sentences about stored data", async () => {
    open()

    expect(await screen.findByText(/and its entry in source_bindings.yaml/)).toBeInTheDocument()
    expect(screen.getByText(/Nothing is deleted from your source/)).toBeInTheDocument()
    expect(await removeButton()).toBeEnabled()
  })

  it('does not mention bindings when a field goes', async () => {
    renderDialog()

    await screen.findByText(/Nothing in the configuration names/)
    expect(screen.queryByText(/source_bindings/)).not.toBeInTheDocument()
  })

  it('lists the link types that still join it, says some are not shown, and cannot be applied', async () => {
    open(LINKED)

    expect(await screen.findByText('link CustomerTags')).toBeInTheDocument()
    expect(screen.getByText(/One more place names something you cannot see/)).toBeInTheDocument()
    expect(await removeButton()).toBeDisabled()
  })

  it('applies exactly what it previewed', async () => {
    open()
    fireEvent.click(await removeButton())

    await waitFor(() => expect(applyRemoval).toHaveBeenCalledWith('d1', { kind: 'type', object_type: 'Tag' }))
  })
})
