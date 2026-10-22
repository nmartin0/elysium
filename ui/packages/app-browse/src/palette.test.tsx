import { publishHostValues, resetHostValues } from '@elysium/shell-api/host'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getSavedViews, getVisibleActionTypesCached } from '@elysium/shell-api/api'
import { useBrowsePalette } from './palette'

vi.mock('@elysium/shell-api/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@elysium/shell-api/api')>()),
  getSavedViews: vi.fn(),
  getVisibleActionTypesCached: vi.fn(),
}))

const at = (path: string) =>
  function Router({ children }: { children: ReactNode }) {
    return <MemoryRouter initialEntries={[path]}>{children}</MemoryRouter>
  }
const labels = (commands: { label: string }[] | undefined) => (commands ?? []).map((c) => c.label)

beforeEach(() => {
  // The response's whole shape (ServerSavedView), not only what the
  // palette reads: a fixture shaped like the model proves nothing.
  vi.mocked(getSavedViews).mockResolvedValue([
    {
      view_id: 'v1',
      name: 'Big spenders',
      object_type: 'Customer',
      query_text: '',
      conditions: [],
      presentation: {},
      created_at: '2026-10-01T00:00:00Z',
    },
  ])
  vi.mocked(getVisibleActionTypesCached).mockResolvedValue({
    Escalate: { affected_object_types: ['Customer'], executable: true },
  })
  act(() =>
    publishHostValues({ visibleSchema: { Customer: { fields: {} } }, username: 'a', onSessionExpired: () => {} }),
  )
})
afterEach(() => {
  act(() => resetHostValues())
  vi.clearAllMocks()
})

describe("Browse's palette", () => {
  it('fetches nothing while the palette is shut', () => {
    renderHook(() => useBrowsePalette({ open: false }), { wrapper: at('/query') })
    expect(getSavedViews).not.toHaveBeenCalled()
    expect(getVisibleActionTypesCached).not.toHaveBeenCalled()
  })

  it('lists the types from the published schema, and the saved views once the palette opens', async () => {
    const { result } = renderHook(() => useBrowsePalette({ open: true }), { wrapper: at('/query') })
    await waitFor(() => expect(labels(result.current.after)).toEqual(['Browse Customer', 'Big spenders']))
  })

  it("offers an object's actions on that object's page, before navigation", async () => {
    const { result } = renderHook(() => useBrowsePalette({ open: true }), { wrapper: at('/objects/Customer/c1') })
    await waitFor(() => expect(labels(result.current.before)).toEqual(['Escalate']))
  })

  it('a failed fetch is fewer commands, not an error', async () => {
    vi.mocked(getSavedViews).mockRejectedValue(new Error('down'))
    vi.mocked(getVisibleActionTypesCached).mockRejectedValue(new Error('down'))
    const { result } = renderHook(() => useBrowsePalette({ open: true }), { wrapper: at('/objects/Customer/c1') })
    await waitFor(() => expect(getSavedViews).toHaveBeenCalled())
    expect(labels(result.current.after)).toEqual(['Browse Customer'])
    expect(result.current.before).toEqual([])
  })
})
