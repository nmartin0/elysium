import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

import { useFetchOnce } from './useFetchOnce'
import { ApiError } from './api'

function Harness({ fetcher, onSessionExpired }: { fetcher: () => Promise<unknown>; onSessionExpired: () => void }) {
  const { data, error } = useFetchOnce<{ value: string }>(fetcher, onSessionExpired)
  return <div>{error ?? data?.value ?? 'loading'}</div>
}

beforeEach(() => vi.clearAllMocks())

describe('useFetchOnce', () => {
  it('reports what it fetched', async () => {
    render(<Harness fetcher={() => Promise.resolve({ value: 'ok' })} onSessionExpired={vi.fn()} />)

    expect(await screen.findByText('ok')).toBeInTheDocument()
  })

  it('fetches ONCE, even though the caller passes a new arrow each render', () => {
    /**
     * The contract the name promises, and the reason `fetcher` is not
     * a dependency. Callers pass an inline arrow, which is new on
     * every render -- depending on it would refetch forever.
     */
    const fetcher = vi.fn(() => Promise.resolve({ value: 'ok' }))
    const { rerender } = render(<Harness fetcher={fetcher} onSessionExpired={vi.fn()} />)

    rerender(<Harness fetcher={() => fetcher()} onSessionExpired={vi.fn()} />)
    rerender(<Harness fetcher={() => fetcher()} onSessionExpired={vi.fn()} />)

    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it('routes an expired session instead of displaying it', async () => {
    /**
     * An expired session is not an error to show -- it is a redirect
     * to the login screen. "401 Unauthorized" in a red box tells the
     * user something true and useless.
     */
    const onSessionExpired = vi.fn()
    render(
      <Harness fetcher={() => Promise.reject(new ApiError(401, 'Unauthorized'))} onSessionExpired={onSessionExpired} />,
    )

    await waitFor(() => expect(onSessionExpired).toHaveBeenCalled())
    expect(screen.getByText('loading')).toBeInTheDocument()
  })

  it('shows a real failure', async () => {
    render(<Harness fetcher={() => Promise.reject(new Error('it broke'))} onSessionExpired={vi.fn()} />)

    expect(await screen.findByText(/it broke/)).toBeInTheDocument()
  })

  // NO test for the cancelled guard, and two attempts is why.
  //
  // The first spied on console.error; React 18 stopped warning about
  // setState after unmount, so it could never fire. The second counted
  // renders; React makes that setState a silent NO-OP, so the count
  // does not move either. Both passed with the guard removed.
  //
  // The guard stays: it is correct, costs one comparison, and a future
  // React may reinstate the warning. But a test that cannot fail is
  // not a test, and a third attempt would be building a seam for the
  // test to grip rather than checking behaviour.
})
