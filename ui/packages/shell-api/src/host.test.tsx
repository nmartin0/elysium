import { act, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { publishHostValues, resetHostValues, stageHostValues, useHostValues } from './host'

function Reader() {
  const { username, visibleSchema } = useHostValues()
  return (
    <p>
      {username || 'nobody'} sees {Object.keys(visibleSchema ?? {}).join(',') || 'nothing'}
    </p>
  )
}

afterEach(() => act(() => resetHostValues()))

describe('the host values', () => {
  it('start empty, so a page rendered before the host publishes still renders', () => {
    render(<Reader />)

    expect(screen.getByText('nobody sees nothing')).toBeInTheDocument()
  })

  it('reach every reader when the host publishes, and again when it changes', () => {
    render(<Reader />)

    act(() =>
      publishHostValues({ visibleSchema: { Customer: {} as never }, username: 'alice', onSessionExpired: () => {} }),
    )
    expect(screen.getByText('alice sees Customer')).toBeInTheDocument()

    act(() => publishHostValues({ visibleSchema: null, username: 'bob', onSessionExpired: () => {} }))
    expect(screen.getByText('bob sees nothing')).toBeInTheDocument()
  })

  it("carry the host's session-expiry handler", () => {
    const expired = vi.fn()
    function Caller() {
      const { onSessionExpired } = useHostValues()
      return <button onClick={onSessionExpired}>end</button>
    }
    render(<Caller />)

    act(() => publishHostValues({ visibleSchema: null, username: 'alice', onSessionExpired: expired }))
    screen.getByRole('button', { name: 'end' }).click()

    expect(expired).toHaveBeenCalledTimes(1)
  })

  it('reach a reader rendering in the same pass once staged, before anyone is told', () => {
    /** A module page mounting with Elysium's page must not render its
     *  first frame -- and run its first effects -- with empty values. */
    stageHostValues({ visibleSchema: null, username: 'staged', onSessionExpired: () => {} })

    render(<Reader />)

    expect(screen.getByText('staged sees nothing')).toBeInTheDocument()
  })
})
