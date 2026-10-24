import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

vi.mock('@elysium/shell-api/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@elysium/shell-api/api')>()),
  getConfigSettings: vi.fn(),
  previewConfigSettings: vi.fn(),
  applyConfigSettings: vi.fn(),
}))

import {
  ApiError,
  applyConfigSettings,
  getConfigSettings,
  previewConfigSettings,
  type ConfigSettings,
} from '@elysium/shell-api/api'
import ConfigSettingsEditor from './ConfigSettingsEditor'

const mockedGet = vi.mocked(getConfigSettings)
const mockedPreview = vi.mocked(previewConfigSettings)
const mockedApply = vi.mocked(applyConfigSettings)

const SETTINGS: ConfigSettings = {
  digest: 'd1',
  settings: [
    {
      key: 'agent.max_hops',
      label: 'Most steps per question',
      kind: 'int',
      description: 'How many steps.',
      when_absent: 'Required.',
      choices: [],
      minimum: 1,
      present: true,
      value: 8,
    },
    {
      key: 'agent.filter_operators',
      label: 'Filter operators',
      kind: 'bool',
      description: 'Ranges and lists.',
      when_absent: 'Off.',
      choices: [],
      present: false,
      value: null,
    },
    {
      key: 'on_type_mismatch',
      label: 'A value of the wrong type',
      kind: 'choice',
      description: 'What a sync does.',
      when_absent: 'The loader decides.',
      choices: ['refuse', 'quarantine'],
      present: true,
      value: 'quarantine',
    },
  ],
}

function renderEditor() {
  const onApplied = vi.fn()
  render(<ConfigSettingsEditor onApplied={onApplied} onSessionExpired={vi.fn()} />)
  return { onApplied }
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedGet.mockResolvedValue(SETTINGS)
  mockedPreview.mockResolvedValue([
    '--- config.yaml (now)',
    '+++ config.yaml (after)',
    '-  max_hops: 8',
    '+  max_hops: 9',
  ])
  mockedApply.mockResolvedValue({ diff: [], digest: 'd2', to_generation: 7 })
})

describe('changing config.yaml from the UI', () => {
  it('renders nothing for someone the server refuses -- not an error over the panel', async () => {
    mockedGet.mockRejectedValue(new ApiError(403, 'Needs manage:deployment'))
    const { container } = render(<ConfigSettingsEditor onApplied={vi.fn()} onSessionExpired={vi.fn()} />)
    await waitFor(() => expect(mockedGet).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
  })

  it('says what an unset setting means, rather than showing a default as if it were set', async () => {
    renderEditor()
    expect(await screen.findByText('Not set: Off.')).toBeInTheDocument()
  })

  it('reviews before writing: the lines that will change, and nothing applied yet', async () => {
    renderEditor()
    const hops = await screen.findByLabelText('Most steps per question')
    fireEvent.change(hops, { target: { value: '9' } })
    fireEvent.click(screen.getByRole('button', { name: 'Review 1 change' }))

    const diff = await screen.findByLabelText('Changes to config.yaml')
    const added = Array.from(diff.querySelectorAll('span')).find((line) => line.textContent === '+  max_hops: 9\n')
    expect(added).toHaveClass('config-editor__added')
    expect(mockedPreview).toHaveBeenCalledWith('d1', { 'agent.max_hops': 9 })
    expect(mockedApply).not.toHaveBeenCalled()
  })

  it('applies with the digest it read, and reports the new generation', async () => {
    const { onApplied } = renderEditor()
    fireEvent.change(await screen.findByLabelText('Most steps per question'), { target: { value: '9' } })
    fireEvent.click(screen.getByRole('button', { name: 'Review 1 change' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Apply and reload' }))

    await waitFor(() => expect(onApplied).toHaveBeenCalledWith(7))
    expect(mockedApply).toHaveBeenCalledWith('d1', { 'agent.max_hops': 9 })
  })

  it('unsetting is a change of its own -- null, not a default value', async () => {
    renderEditor()
    fireEvent.click(await screen.findByRole('button', { name: 'Unset A value of the wrong type' }))
    fireEvent.click(screen.getByRole('button', { name: 'Review 1 change' }))
    await waitFor(() => expect(mockedPreview).toHaveBeenCalledWith('d1', { on_type_mismatch: null }))
  })

  it('setting one that was absent, then putting it back, is no change at all', async () => {
    renderEditor()
    fireEvent.click(await screen.findByRole('button', { name: 'Set Filter operators' }))
    expect(screen.getByRole('button', { name: 'Review 1 change' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'Unset Filter operators' }))
    expect(screen.getByRole('button', { name: 'Review changes' })).toBeDisabled()
  })

  it('a file changed since it was read is said plainly, and the changes are kept', async () => {
    mockedPreview.mockRejectedValue(new ApiError(409, 'config.yaml has changed since you opened it.'))
    renderEditor()
    fireEvent.change(await screen.findByLabelText('Most steps per question'), { target: { value: '9' } })
    fireEvent.click(screen.getByRole('button', { name: 'Review 1 change' }))

    expect(await screen.findByText(/has changed since you opened it.*still here/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Load config.yaml again' })).toBeInTheDocument()
    expect(screen.getByLabelText('Most steps per question')).toHaveValue(9)
  })
})
