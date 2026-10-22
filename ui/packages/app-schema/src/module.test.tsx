import { act, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { publishHostValues, resetHostValues } from '@elysium/shell-api/host'
import { activate } from './module'

// The panel itself is tested in SchemaPanel.test.tsx; here, only that the
// module hands it what the host published.
vi.mock('./SchemaPanel', () => ({
  default: (props: { username: string; visibleSchema: object | null }) => (
    <p>
      panel for {props.username} with {Object.keys(props.visibleSchema ?? {}).join(',') || 'no schema'}
    </p>
  ),
}))

afterEach(() => act(() => resetHostValues()))

describe('the Schema graph as a module', () => {
  it('offers the page its manifest declares', () => {
    expect(Object.keys(activate().pages)).toEqual(['schema'])
  })

  it('gives the panel what the host published, not props from the page', () => {
    const SchemaPage = activate().pages.schema!
    render(<SchemaPage />)

    act(() =>
      publishHostValues({ visibleSchema: { Customer: {} as never }, username: 'alice', onSessionExpired: () => {} }),
    )

    expect(screen.getByText('panel for alice with Customer')).toBeInTheDocument()
  })
})
