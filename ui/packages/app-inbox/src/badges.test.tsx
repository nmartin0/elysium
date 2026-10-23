// The Inbox's badge hook: what it reads and what it gives the rail. The
// frame drawing a badge is tested with the shell (ui/src/Shell.test.tsx).
import { afterEach, describe, expect, it, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { useInboxBadges } from './badges'

function answering(counts: Record<string, number>) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      String(url).endsWith('/me/inbox')
        ? new Response(JSON.stringify(counts), { status: 200 })
        : new Response('{}', { status: 404 }),
    ),
  )
}

const inRouter = ({ children }: { children: ReactNode }) => <MemoryRouter>{children}</MemoryRouter>

describe('the Inbox badge', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('counts decisions and unread notices together, on the Inbox entry', async () => {
    answering({ approvals: 2, notifications: 1, identity: 1 })

    const { result } = renderHook(() => useInboxBadges(), { wrapper: inRouter })

    await waitFor(() => expect(result.current['/inbox']).toEqual({ count: 4, label: '4 waiting' }))
  })

  it('gives zero when nothing is waiting, which the frame draws as nothing', async () => {
    answering({ approvals: 0, notifications: 0, identity: 0 })

    const { result } = renderHook(() => useInboxBadges(), { wrapper: inRouter })

    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalled())
    expect(result.current['/inbox']?.count).toBe(0)
  })
})
