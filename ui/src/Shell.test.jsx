import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import Shell from './Shell'

function renderShell(visibleApps, onLogout = vi.fn(), initialPath = '/query') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route element={<Shell visibleApps={visibleApps} onLogout={onLogout} />}>
          <Route path="/query" element={<p>query screen</p>} />
          <Route path="/admin" element={<p>admin screen</p>} />
        </Route>
      </Routes>
    </MemoryRouter>
  )
}

describe('Shell', () => {
  it('renders nav links exactly matching the visibleApps it was given', () => {
    renderShell([
      { name: 'Query', path: '/query', gating_permission: null },
      { name: 'Browse', path: '/browse', gating_permission: null },
    ])
    expect(screen.getByRole('link', { name: 'Query' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Browse' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Admin' })).not.toBeInTheDocument()
  })

  it('renders no nav links at all for an empty visibleApps -- the deliberate default before the fetch resolves', () => {
    renderShell([])
    expect(screen.queryAllByRole('link')).toHaveLength(0)
    // Still renders the rest of the chrome -- an empty nav isn't a
    // broken shell, just a temporarily-empty one.
    expect(screen.getByText('Elysium')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Log out' })).toBeInTheDocument()
  })

  it('shows Admin only when it is actually present in visibleApps', () => {
    renderShell([
      { name: 'Query', path: '/query', gating_permission: null },
      { name: 'Admin', path: '/admin', gating_permission: 'manage:users' },
    ])
    expect(screen.getByRole('link', { name: 'Admin' })).toBeInTheDocument()
  })

  it('renders the correct child route inside Outlet for the current path', () => {
    renderShell([{ name: 'Admin', path: '/admin', gating_permission: 'manage:users' }], vi.fn(), '/admin')
    expect(screen.getByText('admin screen')).toBeInTheDocument()
    expect(screen.queryByText('query screen')).not.toBeInTheDocument()
  })

  it('calls onLogout when the Log out button is clicked', () => {
    const onLogout = vi.fn()
    renderShell([{ name: 'Query', path: '/query', gating_permission: null }], onLogout)
    fireEvent.click(screen.getByRole('button', { name: 'Log out' }))
    expect(onLogout).toHaveBeenCalledTimes(1)
  })
})
