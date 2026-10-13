import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

const askHelp = vi.fn()

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>()
  return { ...actual, askHelp: (q: string, s: string | null) => askHelp(q, s) }
})

const { default: HelpPanel } = await import('./HelpPanel')
const { ApiError } = await import('../api')

describe('HelpPanel', () => {
  it('asks with the screen the person is on, and shows the answer as text', async () => {
    askHelp.mockResolvedValue('1. Open Browse\n2. Add a filter <b>region</b>')
    render(<HelpPanel isOpen onClose={() => {}} screen="Browse" />)

    fireEvent.change(screen.getByLabelText('Your question'), { target: { value: 'How do I filter?' } })
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))

    const answer = await screen.findByText(/Open Browse/)
    expect(askHelp).toHaveBeenCalledWith('How do I filter?', 'Browse')
    // TEXT, NEVER MARKUP: a model's reply is not trusted HTML.
    expect(answer.textContent).toContain('<b>region</b>')
    expect(answer.querySelector('b')).toBeNull()
  })

  it('says it has no data, so a refusal to give some is not read as a fault', () => {
    render(<HelpPanel isOpen onClose={() => {}} screen={null} />)

    expect(screen.getByText(/not your data/)).toBeInTheDocument()
  })

  it('shows why when the assistant cannot answer', async () => {
    askHelp.mockRejectedValue(new ApiError(503, 'The The help assistant cannot reach its model right now.'))
    render(<HelpPanel isOpen onClose={() => {}} screen={null} />)

    fireEvent.change(screen.getByLabelText('Your question'), { target: { value: 'hi' } })
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))

    expect(await screen.findByText(/cannot reach its model/)).toBeInTheDocument()
  })
})
