import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return { ...actual, exportObjects: vi.fn() }
})

import { ApiError, exportObjects } from '@elysium/shell-api/api'
import ExportSet from './ExportSet'

const mocked = vi.mocked(exportObjects)

beforeEach(() => {
  vi.clearAllMocks()
  mocked.mockResolvedValue(undefined)
})

function show(props: Partial<Parameters<typeof ExportSet>[0]> = {}) {
  return render(<ExportSet objectType="Customer" queryText="" conditions={[]} onSessionExpired={vi.fn()} {...props} />)
}

describe('exporting the set', () => {
  it('offers it once a type is chosen', () => {
    show()
    expect(screen.getByRole('button', { name: /export/i })).toBeInTheDocument()
  })

  it('offers nothing before one is', () => {
    // Nothing is on screen to export, and a button that would fail is
    // worse than no button.
    show({ objectType: null })
    expect(screen.queryByRole('button', { name: /export/i })).toBeNull()
  })

  /**
   * IT EXPORTS THE SET, NOT THE SELECTION, which is the opposite of
   * the Actions menu beside it -- and deliberately. An action is done
   * TO chosen objects, so defaulting to the page is a safety property.
   * An export is a copy of what you are looking at, and "I filtered to
   * 300 and got 50" is the surprise that matters here.
   */
  it('sends the whole set, filters and all', async () => {
    const conditions = [{ field: 'region', operator: 'in', value: ['us-west'] }]
    show({ queryText: 'ada', conditions })

    fireEvent.click(screen.getByRole('button', { name: /export/i }))

    await waitFor(() => expect(mocked).toHaveBeenCalledWith('Customer', 'ada', conditions))
  })

  it('shows the server s own words when it refuses', async () => {
    // The server knows the real count and the ceiling; a message
    // written here would guess at both and drift from the route.
    mocked.mockRejectedValue(new ApiError(400, '1500 objects match, and at most 1000 can be exported at once.'))
    show()

    fireEvent.click(screen.getByRole('button', { name: /export/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent('1500 objects match')
  })

  it('says nothing when it worked', async () => {
    show()

    fireEvent.click(screen.getByRole('button', { name: /export/i }))

    await waitFor(() => expect(mocked).toHaveBeenCalled())
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('clears the last refusal when asked again', async () => {
    mocked.mockRejectedValueOnce(new ApiError(400, 'Too many'))
    show()
    const button = screen.getByRole('button', { name: /export/i })

    fireEvent.click(button)
    expect(await screen.findByRole('alert')).toBeInTheDocument()

    fireEvent.click(button)
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
  })

  it('hands an expired session to the shell rather than rendering it', async () => {
    // A session that has gone is not an export problem, and showing it
    // as one would leave somebody retrying a button that cannot work.
    const onSessionExpired = vi.fn()
    mocked.mockRejectedValue(new ApiError(401, 'Not authenticated'))
    show({ onSessionExpired })

    fireEvent.click(screen.getByRole('button', { name: /export/i }))

    await waitFor(() => expect(onSessionExpired).toHaveBeenCalled())
    expect(screen.queryByRole('alert')).toBeNull()
  })
})
