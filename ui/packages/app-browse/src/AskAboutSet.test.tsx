import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

/**
 * DEV_UI.md section 4's symptom: "the agent lives in its own app, so a
 * question about what you are looking at means starting again in
 * another tab, describing in words what was already on screen."
 * Decided 14 Oct: a panel over Browse that sends the set itself.
 */

const query = vi.fn()

vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return { ...actual, query: (...args: unknown[]) => query(...args) }
})

const { default: AskAboutSet } = await import('./AskAboutSet')

const CONDITIONS = [{ field: 'category', operator: 'in', value: ['refund'] }]

const show = (props: Partial<Parameters<typeof AskAboutSet>[0]> = {}) =>
  render(
    <MemoryRouter>
      <AskAboutSet objectType="Transaction" filterCount={1} total={404} conditions={CONDITIONS} text="" {...props} />
    </MemoryRouter>,
  )

function answering(status: number, body: unknown) {
  query.mockResolvedValue(new Response(JSON.stringify(body), { status }))
}

async function askAbout(question: string) {
  fireEvent.click(screen.getByRole('button', { name: 'Ask about this set' }))
  fireEvent.change(await screen.findByLabelText('Your question about this set'), { target: { value: question } })
  fireEvent.click(screen.getByRole('button', { name: 'Ask' }))
}

describe('asking about the set on screen, without leaving it', () => {
  it('opens over Browse, naming the set it is about', async () => {
    show()
    fireEvent.click(screen.getByRole('button', { name: 'Ask about this set' }))

    expect(await screen.findByText('404 Transaction objects matching 1 filter')).toBeInTheDocument()
  })

  it('sends the set itself -- type, conditions, text -- not a phrase about it', async () => {
    answering(200, { answer: 'Transaction 4.', request_id: 'r1' })
    show({ text: 'Feldman' })
    await askAbout('Which is largest?')

    expect(await screen.findByText('Transaction 4.')).toBeInTheDocument()
    expect(query).toHaveBeenCalledWith('Which is largest?', {
      object_type: 'Transaction',
      conditions: CONDITIONS,
      text: 'Feldman',
    })
  })

  it('shows a refusal as the server words it', async () => {
    answering(400, { detail: 'That set cannot be asked about: Unknown set' })
    show()
    await askAbout('Which?')

    expect(await screen.findByText('That set cannot be asked about: Unknown set')).toBeInTheDocument()
  })

  it('offers to continue in Query with the question', async () => {
    show()
    fireEvent.click(screen.getByRole('button', { name: 'Ask about this set' }))
    fireEvent.change(await screen.findByLabelText('Your question about this set'), {
      target: { value: 'Which is largest?' },
    })

    const link = screen.getByRole('link', { name: 'Continue in Query' })
    expect(decodeURIComponent(link.getAttribute('href') ?? '')).toBe('/query?q=Which is largest?')
  })

  it('a frozen set still goes through Query, by name -- its keys are not a filter', () => {
    show({ frozen: 'Q3 escalations' })

    const link = screen.getByRole('link', { name: 'Ask about this set' })
    expect(decodeURIComponent(link.getAttribute('href') ?? '')).toContain('frozen set Q3 escalations')
  })
})
