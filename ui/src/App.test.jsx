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

import { logout, getMyVisibleSchema, getVisibleApps, ApiError } from '@elysium/shell-api/api'
import App from './App'

beforeEach(() => {
  vi.clearAllMocks()
  getVisibleApps.mockResolvedValue([])
})

// getMyVisibleSchema() now serves TWO real purposes -- the initial
// "is there already a valid session" probe (see App.jsx's own header
// comment for why this specific call was chosen), AND the separate,
// authStatus==='loggedIn'-gated effect that fetches the real schema
// afterward. This means it's genuinely called TWICE on the "already
// logged in when the page loads" path -- once for each -- a
// deliberate, accepted design tradeoff (see that same comment), not
// an oversight; tests below account for this explicitly rather than
// asserting a call count that would only hold for a DIFFERENT design.
describe('App -- the three-state boot sequence (checking / loggedOut / loggedIn)', () => {
  it('shows a real loading state first, before the initial session check resolves', () => {
    // Deliberately never resolved within this test -- observing the
    // FIRST, synchronous render, before any microtask/effect has had
    // a chance to run at all.
    getMyVisibleSchema.mockReturnValue(new Promise(() => {}))
    render(<App />)
    expect(screen.getByText('Loading…')).toBeInTheDocument()
    expect(screen.queryByText('login screen')).not.toBeInTheDocument()
    expect(screen.queryByText('query screen')).not.toBeInTheDocument()
  })

  it('shows the login screen, not the route tree, when no session exists yet (a 401 from the initial check)', async () => {
    getMyVisibleSchema.mockRejectedValue(new ApiError(401, 'no session'))
    render(<App />)
    await waitFor(() => expect(screen.getByText('login screen')).toBeInTheDocument())
    expect(screen.queryByText('query screen')).not.toBeInTheDocument()
  })

  it('also shows the login screen on a NON-401 failure from the initial check -- fails closed, never assumes logged in', async () => {
    getMyVisibleSchema.mockRejectedValue(new Error('network down'))
    render(<App />)
    await waitFor(() => expect(screen.getByText('login screen')).toBeInTheDocument())
  })

  it('shows the real route tree, not the login screen, when a session already exists', async () => {
    getMyVisibleSchema.mockResolvedValue({})
    render(<App />)
    await waitFor(() => expect(screen.getByText('query screen')).toBeInTheDocument())
    expect(screen.queryByText('login screen')).not.toBeInTheDocument()
    expect(screen.queryByText('Loading…')).not.toBeInTheDocument()
  })

  it('transitions from login to the route tree on a successful login', async () => {
    // First call (the initial check) rejects -- no session yet.
    // Every call after that (the real, post-login fetch) succeeds.
    getMyVisibleSchema.mockRejectedValueOnce(new ApiError(401, 'no session')).mockResolvedValue({})
    render(<App />)
    await waitFor(() => expect(screen.getByText('login screen')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: 'fake login submit' }))

    await waitFor(() => expect(screen.getByText('query screen')).toBeInTheDocument())
    expect(screen.queryByText('login screen')).not.toBeInTheDocument()
  })

  it('a real logout (via the REAL, unmocked Shell.jsx) returns to the login screen', async () => {
    // Shell.jsx is deliberately NOT mocked in this file (only the
    // @elysium/* package imports are) -- so this exercises App.jsx's
    // own real handleLogout(), through a real click on Shell's own
    // real "Log out" button, not a synthetic call to a mocked
    // function. Shell.test.jsx separately confirms Shell's own
    // button correctly calls whichever onLogout it's given; THIS
    // test is what confirms App.jsx wires its own, real
    // handleLogout() to that prop correctly, and that handleLogout()
    // itself does the right thing.
    getMyVisibleSchema.mockResolvedValue({})
    render(<App />)
    await waitFor(() => expect(screen.getByText('query screen')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: 'Log out' }))

    await waitFor(() => expect(screen.getByText('login screen')).toBeInTheDocument())
    expect(logout).toHaveBeenCalledTimes(1)
    expect(screen.queryByText('query screen')).not.toBeInTheDocument()
  })
})

describe('App -- fetching visibleSchema/visibleApps once logged in', () => {
  it('fetches visibleApps once a session is confirmed to already exist', async () => {
    getMyVisibleSchema.mockResolvedValue({})
    render(<App />)
    await waitFor(() => expect(getVisibleApps).toHaveBeenCalledTimes(1))
  })

  it('does not fetch visibleApps while the initial session check is still pending or has failed', async () => {
    getMyVisibleSchema.mockRejectedValue(new ApiError(401, 'no session'))
    render(<App />)
    await waitFor(() => expect(screen.getByText('login screen')).toBeInTheDocument())
    expect(getVisibleApps).not.toHaveBeenCalled()
  })

  it('fetches visibleApps again after a fresh login, since the initial check already ran once before it', async () => {
    getMyVisibleSchema.mockRejectedValueOnce(new ApiError(401, 'no session')).mockResolvedValue({})
    render(<App />)
    await waitFor(() => expect(screen.getByText('login screen')).toBeInTheDocument())
    expect(getVisibleApps).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'fake login submit' }))

    await waitFor(() => expect(getVisibleApps).toHaveBeenCalledTimes(1))
  })
})

describe('App -- a 401 mid-session returns to the login screen', () => {
  it('a 401 from the real, post-login visibleSchema fetch logs the user back out', async () => {
    // Initial check succeeds (already logged in) -- but the SEPARATE,
    // real fetch right after fails with 401, simulating a session
    // that expired between the initial check and that second call.
    getMyVisibleSchema.mockResolvedValueOnce({}).mockRejectedValue(new ApiError(401, 'session expired'))
    render(<App />)
    await waitFor(() => expect(screen.getByText('login screen')).toBeInTheDocument())
  })

  it('a 401 from the visibleApps fetch logs the user back out too', async () => {
    getMyVisibleSchema.mockResolvedValue({})
    getVisibleApps.mockRejectedValue(new ApiError(401, 'session expired'))
    render(<App />)
    await waitFor(() => expect(screen.getByText('login screen')).toBeInTheDocument())
  })

  it('a NON-401 error from the post-login visibleSchema fetch does NOT log the user out -- leaves them on the real route tree', async () => {
    getMyVisibleSchema.mockResolvedValueOnce({}).mockRejectedValue(new ApiError(500, 'server error'))
    render(<App />)
    await waitFor(() => expect(screen.getByText('query screen')).toBeInTheDocument())
    expect(screen.queryByText('login screen')).not.toBeInTheDocument()
  })
})
