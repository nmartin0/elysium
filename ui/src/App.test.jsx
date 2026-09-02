import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

// App.jsx pulls in every sub-app package plus the shell's own API --
// mocked here so this file tests ONLY App.jsx's own responsibility
// (auth gating, which effects fire, how a 401 is handled), not each
// sub-app's own internal behavior, which already has its own tests
// (or will) closer to where that behavior actually lives.
vi.mock('@elysium/shell-api/api', () => {
  class ApiError extends Error {
    constructor(status, message) {
      super(message)
      this.status = status
    }
  }
  return {
    getToken: vi.fn(),
    logout: vi.fn(),
    getMyVisibleSchema: vi.fn(),
    getVisibleApps: vi.fn(),
    ApiError,
    // A real, working implementation, matching the actual one exactly
    // -- not just a vi.fn() stub -- so this test genuinely exercises
    // the real 401-detection logic, not a fake that always/never
    // fires regardless of what's tested.
    handleIfSessionExpired: (err, onSessionExpired) => {
      if (err instanceof ApiError && err.status === 401) {
        onSessionExpired()
        return true
      }
      return false
    },
  }
})
vi.mock('@elysium/shell-api/components/LoginForm', () => ({
  default: ({ onSuccess }) => (
    <div>
      <p>login screen</p>
      <button onClick={onSuccess}>fake login submit</button>
    </div>
  ),
}))
vi.mock('@elysium/app-query/QueryPanel', () => ({ default: () => <p>query screen</p> }))
vi.mock('@elysium/app-browse/ObjectSearchPanel', () => ({ default: () => <p>browse screen</p> }))
vi.mock('@elysium/app-browse/ObjectDetailPanel', () => ({ default: () => <p>object detail screen</p> }))
vi.mock('@elysium/app-admin/AdminPanel', () => ({ default: () => <p>admin screen</p> }))

import { getToken, getMyVisibleSchema, getVisibleApps, ApiError } from '@elysium/shell-api/api'
import App from './App'

beforeEach(() => {
  vi.clearAllMocks()
  getMyVisibleSchema.mockResolvedValue({})
  getVisibleApps.mockResolvedValue([])
})

describe('App -- the security-critical auth guard', () => {
  it('shows the login screen, not the route tree, when there is no token', () => {
    getToken.mockReturnValue(null)
    render(<App />)
    expect(screen.getByText('login screen')).toBeInTheDocument()
    expect(screen.queryByText('query screen')).not.toBeInTheDocument()
  })

  it('shows the real route tree, not the login screen, when a token is already present', async () => {
    getToken.mockReturnValue('real-token')
    render(<App />)
    await waitFor(() => expect(screen.getByText('query screen')).toBeInTheDocument())
    expect(screen.queryByText('login screen')).not.toBeInTheDocument()
  })

  it('transitions from login to the route tree on a successful login', async () => {
    getToken.mockReturnValue(null)
    render(<App />)
    expect(screen.getByText('login screen')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'fake login submit' }))

    await waitFor(() => expect(screen.getByText('query screen')).toBeInTheDocument())
    expect(screen.queryByText('login screen')).not.toBeInTheDocument()
  })
})

describe('App -- fetching visibleSchema/visibleApps once logged in', () => {
  it('fetches both visibleSchema and visibleApps when a token is already present', async () => {
    getToken.mockReturnValue('real-token')
    render(<App />)
    await waitFor(() => {
      expect(getMyVisibleSchema).toHaveBeenCalledTimes(1)
      expect(getVisibleApps).toHaveBeenCalledTimes(1)
    })
  })

  it('does not fetch anything while logged out', () => {
    getToken.mockReturnValue(null)
    render(<App />)
    expect(getMyVisibleSchema).not.toHaveBeenCalled()
    expect(getVisibleApps).not.toHaveBeenCalled()
  })
})

describe('App -- a 401 mid-session returns to the login screen', () => {
  it('a 401 from the visibleSchema fetch logs the user back out', async () => {
    getToken.mockReturnValue('stale-token')
    getMyVisibleSchema.mockRejectedValue(new ApiError(401, 'session expired'))
    render(<App />)
    await waitFor(() => expect(screen.getByText('login screen')).toBeInTheDocument())
  })

  it('a 401 from the visibleApps fetch logs the user back out too', async () => {
    getToken.mockReturnValue('stale-token')
    getVisibleApps.mockRejectedValue(new ApiError(401, 'session expired'))
    render(<App />)
    await waitFor(() => expect(screen.getByText('login screen')).toBeInTheDocument())
  })

  it('a NON-401 error from visibleSchema does NOT log the user out -- leaves them on the real route tree', async () => {
    getToken.mockReturnValue('real-token')
    getMyVisibleSchema.mockRejectedValue(new ApiError(500, 'server error'))
    render(<App />)
    await waitFor(() => expect(screen.getByText('query screen')).toBeInTheDocument())
    expect(screen.queryByText('login screen')).not.toBeInTheDocument()
  })
})
