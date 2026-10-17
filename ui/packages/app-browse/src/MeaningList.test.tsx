import { describe, expect, it, vi } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import type { MeaningResults } from '@elysium/shell-api/api'
import MeaningList from './MeaningList'

const schema = { SupportTicket: { fields: {}, title_field: 'subject' } } as never

function show(load: () => Promise<MeaningResults>, key = 'k', delayMs = 0) {
  return render(
    <MemoryRouter>
      <MeaningList
        title="Similar records"
        objectType="SupportTicket"
        visibleSchema={schema}
        load={load}
        requestKey={key}
        emptyText="No similar records that you can see."
        onSessionExpired={vi.fn()}
        delayMs={delayMs}
      />
    </MemoryRouter>,
  )
}

describe('records ranked by meaning (R45)', () => {
  it('lists them nearest first, as links titled like everywhere else, with no scores', async () => {
    show(async () => ({
      available: true,
      results: [
        { id: '2', fields: { subject: 'Requesting a refund' } },
        { id: '7', fields: { subject: 'Money back please' } },
      ],
    }))
    const links = await screen.findAllByRole('link')
    expect(links.map((link) => link.textContent)).toEqual(['Requesting a refund', 'Money back please'])
    expect(links[0]).toHaveAttribute('href', '/objects/SupportTicket/2')
    expect(screen.getByRole('list').tagName).toBe('OL')
    expect(screen.queryByText(/score|%/)).not.toBeInTheDocument()
  })

  it('names a record of a type without a title by the text it was ranked by, with its id beside it', async () => {
    render(
      <MemoryRouter>
        <MeaningList
          title="Similar records"
          objectType="SupportTicket"
          visibleSchema={{ SupportTicket: { fields: {} } } as never}
          load={async () => ({
            available: true,
            text_fields: ['subject'],
            results: [{ id: '1', fields: { status: 'open', subject: 'Requesting a refund' } }],
          })}
          requestKey="k"
          emptyText="none"
          onSessionExpired={vi.fn()}
        />
      </MemoryRouter>,
    )
    expect(await screen.findByRole('link', { name: 'Requesting a refund' })).toBeInTheDocument()
    expect(screen.getByText('1')).toHaveClass('meaning-list__id')
  })

  it('shows nothing at all where it is not offered', async () => {
    const load = vi.fn(async () => ({ available: false, offered: false, reason: 'not offered', results: [] }))
    const { container } = show(load)
    await waitFor(() => expect(load).toHaveBeenCalled())
    await act(async () => {})
    expect(container).toBeEmptyDOMElement()
  })

  it('says why when it is offered but cannot answer now', async () => {
    show(async () => ({
      available: false,
      offered: true,
      reason: 'The embedding model did not answer; word search still works.',
      results: [],
    }))
    expect(await screen.findByText(/did not answer; word search still works/)).toBeInTheDocument()
  })

  it('says so when nothing near can be seen', async () => {
    show(async () => ({ available: true, results: [] }))
    expect(await screen.findByText('No similar records that you can see.')).toBeInTheDocument()
  })

  it('waits for typing to pause before asking the model', async () => {
    vi.useFakeTimers()
    try {
      const load = vi.fn(async () => ({ available: true, results: [] }))
      const view = show(load, 'r', 600)
      for (const key of ['re', 'ref', 'refund']) {
        await act(async () => {
          vi.advanceTimersByTime(200)
        })
        view.rerender(
          <MemoryRouter>
            <MeaningList
              title="Similar records"
              objectType="SupportTicket"
              visibleSchema={schema}
              load={load}
              requestKey={key}
              emptyText="none"
              onSessionExpired={vi.fn()}
              delayMs={600}
            />
          </MemoryRouter>,
        )
      }
      expect(load).not.toHaveBeenCalled()
      await act(async () => {
        vi.advanceTimersByTime(600)
      })
      expect(load).toHaveBeenCalledTimes(1)
    } finally {
      vi.useRealTimers()
    }
  })
})
