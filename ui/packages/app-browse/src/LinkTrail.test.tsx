/**
 * "Customer Ada Okafor › Transactions" -- the trail above a linked view.
 *
 * BY TITLE, as Foundry shows linked objects, with the id as fallback --
 * and a failed fetch keeps the id rather than hiding the trail, which
 * is still true without a title.
 */
import { act, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return { ...actual, getObjectDetail: vi.fn() }
})

import { getObjectDetail } from '@elysium/shell-api/api'
import LinkTrail from './LinkTrail'

const ORIGIN = { type: 'Customer', id: 'cust_001', field: 'customer_id' }
const SCHEMA = { Customer: { title_field: 'name', fields: {} } } as never

function show() {
  return render(
    <MemoryRouter>
      <LinkTrail origin={ORIGIN} targetType="Transaction" visibleSchema={SCHEMA} />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('the trail', () => {
  it('names the origin by its title', async () => {
    vi.mocked(getObjectDetail).mockResolvedValue({ fields: { name: 'Ada Okafor' } })
    show()

    expect(await screen.findByText('Customer Ada Okafor')).toBeInTheDocument()
  })

  it('says where it leads', async () => {
    vi.mocked(getObjectDetail).mockResolvedValue({ fields: { name: 'Ada Okafor' } })
    show()

    expect(await screen.findByText('Transaction')).toBeInTheDocument()
  })

  it('links back to the origin', async () => {
    /** THE POINT OF A TRAIL is that you can walk it. */
    vi.mocked(getObjectDetail).mockResolvedValue({ fields: { name: 'Ada Okafor' } })
    show()

    const back = await screen.findByRole('link', { name: 'Customer Ada Okafor' })
    expect(back).toHaveAttribute('href', '/objects/Customer/cust_001')
  })

  it('keeps the id when the origin cannot be fetched', async () => {
    /** STILL TRUE WITHOUT A TITLE, so no error over working results.
     *
     *  AFTER THE FAILURE IS HANDLED, not before. The id shows at once
     *  while the title is fetched, so a first version found that
     *  initial render and passed before the rejection had even run --
     *  proving the id APPEARED, not that it STAYED. A control blanking
     *  the title on failure passed it. So this waits for the fetch to
     *  be made and its rejection to settle, then looks. */
    vi.mocked(getObjectDetail).mockRejectedValue(new Error('unreachable'))
    show()

    await waitFor(() => expect(getObjectDetail).toHaveBeenCalled())
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })

    expect(screen.getByText('Customer cust_001')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('is labelled as navigation', async () => {
    vi.mocked(getObjectDetail).mockResolvedValue({ fields: {} })
    show()

    expect(await screen.findByRole('navigation', { name: 'How you got here' })).toBeInTheDocument()
  })
})
