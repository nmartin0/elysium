import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

const getRuleSuggestions = vi.fn()
const scanRuleSuggestions = vi.fn()
const decideRuleSuggestion = vi.fn()

vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return {
    ...actual,
    getRuleSuggestions: () => getRuleSuggestions(),
    scanRuleSuggestions: () => scanRuleSuggestions(),
    decideRuleSuggestion: (...args: unknown[]) => decideRuleSuggestion(...args),
  }
})

const { default: RuleSuggestions } = await import('./RuleSuggestions')

function suggestion(overrides: Record<string, unknown> = {}) {
  return {
    id: 's1',
    object_type: 'Customer',
    field: 'email',
    kind: 'absence',
    value: 'N/A',
    seen: 4,
    why: "a word meaning 'no value', stored as a value",
    examples: ['N/A'],
    state: 'pending',
    last_seen: '2026-10-14T10:00:00+00:00',
    yaml: 'object_types:\n  Customer:\n    fields:\n      email:\n        standardise:\n          null_if: ["N/A"]',
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  getRuleSuggestions.mockResolvedValue([])
})

describe('RuleSuggestions', () => {
  it('lists a pending suggestion with Accept and Dismiss', async () => {
    getRuleSuggestions.mockResolvedValue([suggestion()])

    render(<RuleSuggestions onSessionExpired={() => {}} />)

    expect(await screen.findByText('Customer.email')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Accept' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Dismiss' })).toBeInTheDocument()
  })

  it('dismissing records it and reloads', async () => {
    getRuleSuggestions.mockResolvedValueOnce([suggestion()]).mockResolvedValueOnce([suggestion({ state: 'dismissed' })])
    decideRuleSuggestion.mockResolvedValue(undefined)

    render(<RuleSuggestions onSessionExpired={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Dismiss' }))

    await waitFor(() => expect(decideRuleSuggestion).toHaveBeenCalledWith('s1', 'dismissed'))
    expect(await screen.findByText('dismissed')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Accept' })).not.toBeInTheDocument()
  })

  it('an accepted one shows the lines to add, and no buttons', async () => {
    getRuleSuggestions.mockResolvedValue([suggestion({ state: 'accepted' })])

    render(<RuleSuggestions onSessionExpired={() => {}} />)

    const yaml = await screen.findByLabelText('Lines to add for email')
    expect(yaml.textContent).toContain('null_if: ["N/A"]')
    expect(screen.queryByRole('button', { name: 'Accept' })).not.toBeInTheDocument()
  })

  it('a pending one does not show YAML until accepted', async () => {
    // THE CONTROL for the one above: the lines are the answer to an
    // acceptance, not something to paste before deciding.
    getRuleSuggestions.mockResolvedValue([suggestion()])

    render(<RuleSuggestions onSessionExpired={() => {}} />)

    await screen.findByText('Customer.email')
    expect(screen.queryByLabelText('Lines to add for email')).not.toBeInTheDocument()
  })

  it('a range shows the dates seen', async () => {
    getRuleSuggestions.mockResolvedValue([
      suggestion({ kind: 'range', field: 'born_on', value: '', examples: ['0201-05-12', '2299-01-01'] }),
    ])

    render(<RuleSuggestions onSessionExpired={() => {}} />)

    expect(await screen.findByText('0201-05-12, 2299-01-01')).toBeInTheDocument()
  })

  it('scanning says what it found', async () => {
    scanRuleSuggestions.mockResolvedValue({ new: 2, updated: 1, declared: 0, kept_dismissed: 3 })

    render(<RuleSuggestions onSessionExpired={() => {}} />)
    fireEvent.click(await screen.findByRole('button', { name: /Scan bronze now/ }))

    expect(await screen.findByText(/2 new, 1 still open, 0 already declared, 3 dismissed earlier/)).toBeInTheDocument()
  })
})
