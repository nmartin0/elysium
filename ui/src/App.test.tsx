import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

// App.jsx pulls in every sub-app package plus the shell's own API --
// mocked here so this file tests ONLY App.jsx's own responsibility
// (auth gating, which effects fire, how a 401 is handled), not each
// sub-app's own internal behavior, which already has its own tests
// (or will) closer to where that behavior actually lives.
//
// Partial mock via importOriginal, not a hand-duplicated module shape
// -- confirmed directly against Vitest's own current, official docs,
// not assumed: spreading the REAL module and overriding only the
// network-calling functions this file actually needs faked means
// ApiError and handleIfSessionExpired are the real, actual
// implementations (never a hand-copied reimplementation that could
// silently drift out of sync with the real one), and any FUTURE
// export added to api.ts flows through automatically -- this is the
// real, structural fix for a real, confirmed fragility: the prior,
// hand-duplicated mock shape broke in 12 tests across 6 files the
// moment a new, real, shared getErrorMessage() export was added to
// api.ts, precisely because those mocks never included it.
vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return {
    ...actual,
    logout: vi.fn(),
    // The change-password screen's call. Mocked by RESOLVED FILE, so
    // the form's own relative '../api' import sees this mock too.
    changeOwnPassword: vi.fn(),
    getCurrentUser: vi.fn(),
    getMyVisibleSchema: vi.fn(),
    getModuleFeed: vi.fn(),
  }
})
vi.mock('@elysium/shell-api/components/LoginForm', () => ({
  default: ({ onSuccess }: { onSuccess: () => void }) => (
    <div>
      <p>login screen</p>
      <button onClick={onSuccess}>fake login submit</button>
    </div>
  ),
}))
// QUERY AND ADMIN HAVE BUNDLES OF THEIR OWN (BLOCKING.md item 3, step 3),
// which jsdom cannot import, so their bundles are stood in for: the loader
// is the real one, given an importer that answers for their addresses and
// imports anything else for real -- which in jsdom fails, as a bundle that
// was never built would.
const QUERY_BUNDLE = '/api/modules/query/files/dist/index.js'
const ADMIN_BUNDLE = '/api/modules/admin/files/dist/index.js'
vi.mock('@shell/core/moduleLoader', async (importOriginal) => {
  const real = await importOriginal<typeof import('@shell/core/moduleLoader')>()
  const standIns: Record<string, Record<string, () => React.JSX.Element>> = {
    '/api/modules/query/files/dist/index.js': { query: () => <p>query screen</p> },
    '/api/modules/admin/files/dist/index.js': { admin: () => <p>admin screen</p> },
  }
  class StandIn extends real.ModuleLoader {
    constructor() {
      super((address) =>
        standIns[address]
          ? Promise.resolve({ activate: () => ({ pages: standIns[address] }) })
          : import(/* @vite-ignore */ address),
      )
    }
  }
  return { ...real, ModuleLoader: StandIn }
})

import {
  logout,
  changeOwnPassword,
  getCurrentUser,
  getMyVisibleSchema,
  getModuleFeed,
  ApiError,
} from '@elysium/shell-api/api'
import { useHostValues } from '@elysium/shell-api/host'
import App from './App'

const mockedLogout = vi.mocked(logout)
const mockedGetCurrentUser = vi.mocked(getCurrentUser)
const mockedGetMyVisibleSchema = vi.mocked(getMyVisibleSchema)
const mockedGetModuleFeed = vi.mocked(getModuleFeed)

beforeEach(() => {
  vi.clearAllMocks()
  // The feed as the server sends it: the shell routes /query to the
  // query module's page, from the bundle stood in for above.
  mockedGetModuleFeed.mockResolvedValue({
    contract: 1,
    home: '/query',
    modules: [
      {
        id: 'query',
        name: 'Query',
        version: '1',
        entry: QUERY_BUNDLE,
        styles: [],
        contributes: { pages: [{ id: 'query', path: '/query' }], nav: [{ title: 'Query', path: '/query' }] },
      },
    ],
  })
  mockedGetCurrentUser.mockResolvedValue({ username: 'testuser', role_name: 'editor', mac_value: 'us-west' })
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
    mockedGetCurrentUser.mockReturnValue(new Promise(() => {}))
    render(<App />)
    expect(screen.getByText('Loading…')).toBeInTheDocument()
    expect(screen.queryByText('login screen')).not.toBeInTheDocument()
    expect(screen.queryByText('query screen')).not.toBeInTheDocument()
  })

  it('shows the login screen, not the route tree, when no session exists yet (a 401 from the initial check)', async () => {
    mockedGetCurrentUser.mockRejectedValue(new ApiError(401, 'no session'))
    render(<App />)
    await waitFor(() => expect(screen.getByText('login screen')).toBeInTheDocument())
    expect(screen.queryByText('query screen')).not.toBeInTheDocument()
  })

  it('also shows the login screen on a NON-401 failure from the initial check -- fails closed, never assumes logged in', async () => {
    mockedGetCurrentUser.mockRejectedValue(new Error('network down'))
    render(<App />)
    await waitFor(() => expect(screen.getByText('login screen')).toBeInTheDocument())
  })

  it('shows the real route tree, not the login screen, when a session already exists', async () => {
    mockedGetMyVisibleSchema.mockResolvedValue({})
    render(<App />)
    await waitFor(() => expect(screen.getByText('query screen')).toBeInTheDocument())
    expect(screen.queryByText('login screen')).not.toBeInTheDocument()
    expect(screen.queryByText('Loading…')).not.toBeInTheDocument()
  })

  it('transitions from login to the route tree on a successful login', async () => {
    // First call (the initial check) rejects -- no session yet.
    // Every call after that (the real, post-login fetch) succeeds.
    mockedGetCurrentUser
      .mockRejectedValueOnce(new ApiError(401, 'no session'))
      .mockResolvedValue({ username: 'testuser', role_name: 'editor', mac_value: 'us-west' })
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
    mockedGetMyVisibleSchema.mockResolvedValue({})
    render(<App />)

    // WAIT FOR THE THING THIS TEST CLICKS, not for something else that
    // happens to arrive first.
    //
    // This used to wait for "query screen" and then immediately click
    // the user menu. Those are fed by SEPARATE fetches -- App makes
    // three independent useFetchOnLogin calls, for visibleSchema,
    // the module feed and currentUser -- and only the first gates the
    // screen. So the username could still be absent when the click
    // happened, and the trigger read "Account" instead.
    //
    // It passed everywhere it was run, until a slower machine ran the
    // full suite and it did not. Reproduced deliberately by resolving
    // getCurrentUser 120ms late: fails the same way on this commit AND
    // on the one before the change that surfaced it, which is what
    // identifies it as a racy test rather than a regression.
    const trigger = await screen.findByRole('button', { name: 'testuser' })

    fireEvent.click(trigger)
    fireEvent.click(screen.getByRole('menuitem', { name: 'Log out' }))

    await waitFor(() => expect(screen.getByText('login screen')).toBeInTheDocument())
    expect(mockedLogout).toHaveBeenCalledTimes(1)
    expect(screen.queryByText('query screen')).not.toBeInTheDocument()
  })
})

describe('App -- the screen and the username arrive separately', () => {
  it('waits for the user menu even when the username is slow', async () => {
    /**
     * THE RACE, MADE PERMANENT rather than left to a fast machine.
     *
     * App makes three independent useFetchOnLogin calls --
     * visibleSchema, the module feed and currentUser -- and only the first
     * gates the screen. A test that waits for "query screen" and then
     * reaches for the username is asserting on something it never
     * waited for; the trigger reads "Account" until currentUser lands.
     *
     * It passed on every machine it was run on until a slower one ran
     * the full suite. Reproduced by resolving getCurrentUser 120ms
     * late, which failed identically on the commit BEFORE the change
     * that surfaced it -- so: a racy test, not a regression.
     *
     * HELD UNTIL THE SCREEN IS UP rather than delayed 120ms, since
     * step 3: Query's page now comes from a bundle, a few more turns of
     * the event loop than a page in this one, and a fixed delay is a race
     * again. Held, the username cannot arrive first however slow the page.
     * The FIRST call is the probe that says a session exists (App.tsx's
     * /me), which gates everything, so it answers at once; the second is
     * the user menu's own fetch, the one held.
     */
    mockedGetMyVisibleSchema.mockResolvedValue({})
    let deliverUser: (user: { username: string; role_name: string; mac_value: string }) => void = () => {}
    mockedGetCurrentUser
      .mockResolvedValueOnce({ username: 'testuser', role_name: 'editor', mac_value: 'us-west' })
      .mockImplementation(() => new Promise((resolve) => (deliverUser = resolve)))
    render(<App />)

    // The screen is up FIRST, with no username yet -- the state the
    // old test clicked into.
    await waitFor(() => expect(screen.getByText('query screen')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'testuser' })).not.toBeInTheDocument()

    deliverUser({ username: 'testuser', role_name: 'editor', mac_value: 'us-west' })
    // And the username follows.
    expect(await screen.findByRole('button', { name: 'testuser' })).toBeInTheDocument()
  })
})

describe('App -- fetching visibleSchema/the module feed/currentUser once logged in', () => {
  it('fetches the module feed once a session is confirmed to already exist', async () => {
    mockedGetMyVisibleSchema.mockResolvedValue({})
    render(<App />)
    await waitFor(() => expect(mockedGetModuleFeed).toHaveBeenCalledTimes(1))
  })

  it('does not fetch the module feed while the initial session check is still pending or has failed', async () => {
    mockedGetCurrentUser.mockRejectedValue(new ApiError(401, 'no session'))
    render(<App />)
    await waitFor(() => expect(screen.getByText('login screen')).toBeInTheDocument())
    expect(mockedGetModuleFeed).not.toHaveBeenCalled()
  })

  it('fetches the module feed again after a fresh login, since the initial check already ran once before it', async () => {
    mockedGetCurrentUser
      .mockRejectedValueOnce(new ApiError(401, 'no session'))
      .mockResolvedValue({ username: 'testuser', role_name: 'editor', mac_value: 'us-west' })
    render(<App />)
    await waitFor(() => expect(screen.getByText('login screen')).toBeInTheDocument())
    expect(mockedGetModuleFeed).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'fake login submit' }))

    await waitFor(() => expect(mockedGetModuleFeed).toHaveBeenCalledTimes(1))
  })

  it("fetches currentUser once a session is confirmed to already exist, and Shell's own real UserMenu shows it", async () => {
    // Shell.jsx is deliberately NOT mocked in this file (see the real-
    // logout test above) -- so this confirms the WHOLE real chain,
    // not just that getCurrentUser() was called: App.tsx fetches it,
    // passes it down as a real prop, and Shell's own real UserMenu
    // actually renders the real username it received.
    mockedGetMyVisibleSchema.mockResolvedValue({})
    render(<App />)
    // TWICE: the probe asks /me, then the post-login effect asks again --
    // the redundant fetch App.tsx's comment accepts. A first version
    // waited for ONE call, which passes the instant the probe's lands.
    await waitFor(() => expect(mockedGetCurrentUser).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(screen.getByRole('button', { name: 'testuser' })).toBeInTheDocument())
  })

  it('asks /me only once -- the probe -- while the initial session check has failed', async () => {
    // THE PROBE IS /me NOW (resolveSession in App.tsx), so "not at all"
    // is no longer the claim. The post-login effect must not ALSO fire.
    mockedGetCurrentUser.mockRejectedValue(new ApiError(401, 'no session'))
    render(<App />)
    await waitFor(() => expect(screen.getByText('login screen')).toBeInTheDocument())
    expect(mockedGetCurrentUser).toHaveBeenCalledTimes(1)
  })
})

describe('App -- a 401 mid-session returns to the login screen', () => {
  it('a 401 from the real, post-login visibleSchema fetch logs the user back out', async () => {
    // Initial check succeeds (already logged in) -- but the SEPARATE,
    // real fetch right after fails with 401, simulating a session
    // that expired between the initial check and that second call.
    // The probe (/me) succeeds by default; the post-login schema fetch 401s.
    mockedGetMyVisibleSchema.mockRejectedValue(new ApiError(401, 'session expired'))
    render(<App />)
    await waitFor(() => expect(screen.getByText('login screen')).toBeInTheDocument())
  })

  it('a 401 from the module-feed fetch logs the user back out too', async () => {
    mockedGetMyVisibleSchema.mockResolvedValue({})
    mockedGetModuleFeed.mockRejectedValue(new ApiError(401, 'session expired'))
    render(<App />)
    await waitFor(() => expect(screen.getByText('login screen')).toBeInTheDocument())
  })

  it('a 401 from the currentUser fetch logs the user back out too', async () => {
    mockedGetMyVisibleSchema.mockResolvedValue({})
    mockedGetCurrentUser.mockRejectedValue(new ApiError(401, 'session expired'))
    render(<App />)
    await waitFor(() => expect(screen.getByText('login screen')).toBeInTheDocument())
  })

  it('a NON-401 error from the post-login visibleSchema fetch does NOT log the user out -- leaves them on the real route tree', async () => {
    mockedGetMyVisibleSchema.mockResolvedValueOnce({}).mockRejectedValue(new ApiError(500, 'server error'))
    render(<App />)
    await waitFor(() => expect(screen.getByText('query screen')).toBeInTheDocument())
    expect(screen.queryByText('login screen')).not.toBeInTheDocument()
  })
})

describe('App -- after an administrator reset your password', () => {
  /** THE ADMINISTRATOR KNOWS IT, so until you choose your own the
   *  server refuses everything but /me, changing it, and logging out.
   *  A STATE OF ITS OWN: nothing else is fetched -- it would all be
   *  refused -- and everything is fetched fresh once you have chosen. */
  const RESET = { username: 'testuser', role_name: 'editor', mac_value: 'us-west', must_change_password: true }

  it('asks for a new password instead of showing the apps, and says why', async () => {
    vi.mocked(getCurrentUser).mockResolvedValue(RESET)
    render(<App />)

    expect(await screen.findByText(/An administrator reset your password/)).toBeInTheDocument()
    expect(screen.queryByText('query screen')).not.toBeInTheDocument()
  })

  it('fetches nothing the server would refuse', async () => {
    vi.mocked(getCurrentUser).mockResolvedValue(RESET)
    render(<App />)
    await screen.findByText(/An administrator reset your password/)

    expect(mockedGetModuleFeed).not.toHaveBeenCalled()
    expect(vi.mocked(getMyVisibleSchema)).not.toHaveBeenCalled()
  })

  it('carries on into the apps once the password is chosen', async () => {
    vi.mocked(getCurrentUser).mockResolvedValue(RESET)
    vi.mocked(changeOwnPassword).mockResolvedValue(0)
    render(<App />)
    await screen.findByText(/An administrator reset your password/)

    fireEvent.change(screen.getByLabelText('Current password'), { target: { value: 'the-reset-one-given' } })
    fireEvent.change(screen.getByLabelText('New password'), { target: { value: 'my-own-choice-at-last' } })
    fireEvent.change(screen.getByLabelText('New password, again'), { target: { value: 'my-own-choice-at-last' } })
    fireEvent.click(screen.getByRole('button', { name: 'Change password' }))

    await waitFor(() => expect(mockedGetModuleFeed).toHaveBeenCalled())
  })

  it('a fresh login lands here too', async () => {
    /** THE LOOP THIS STATE PREVENTS: a probe refused as "logged out"
     *  sent a reset account to the login form, and logging in again
     *  tripped the same refusal. */
    vi.mocked(getCurrentUser).mockRejectedValueOnce(new ApiError(401, 'no session')).mockResolvedValue(RESET)
    render(<App />)
    await screen.findByText('login screen')

    fireEvent.click(screen.getByRole('button', { name: 'fake login submit' }))

    expect(await screen.findByText(/An administrator reset your password/)).toBeInTheDocument()
  })

  it('offers a way out', async () => {
    /** A REQUIRED STEP WITH NO EXIT traps somebody not ready to choose. */
    vi.mocked(getCurrentUser).mockResolvedValue(RESET)
    render(<App />)

    expect(await screen.findByRole('button', { name: 'Log out' })).toBeInTheDocument()
  })
})

describe('App -- routes and rail come from the module feed', () => {
  afterEach(() => window.history.pushState({}, '', '/'))

  it('offers in the rail what the feed contributes, and nothing else', async () => {
    mockedGetMyVisibleSchema.mockResolvedValue({})
    render(<App />)

    await screen.findByText('query screen')
    expect(screen.getByRole('menuitem', { name: 'Query' })).toBeInTheDocument()
    expect(screen.queryByRole('menuitem', { name: 'Admin' })).not.toBeInTheDocument()
  })

  it('holds a deep link until the feed arrives, rather than sending it home', async () => {
    /** BEFORE THE FEED the shell cannot know whether anything opens an
     *  address; redirecting then would lose every bookmark. */
    let deliver: (feed: unknown) => void = () => {}
    mockedGetModuleFeed.mockReturnValue(new Promise((resolve) => (deliver = resolve)))
    mockedGetMyVisibleSchema.mockResolvedValue({})
    window.history.pushState({}, '', '/admin')
    render(<App />)

    await waitFor(() => expect(mockedGetModuleFeed).toHaveBeenCalled())
    expect(window.location.pathname).toBe('/admin')

    deliver({
      contract: 1,
      home: '/query',
      modules: [
        {
          id: 'admin',
          name: 'Admin',
          version: '1',
          entry: ADMIN_BUNDLE,
          styles: [],
          contributes: { pages: [{ id: 'admin', path: '/admin' }] },
        },
      ],
    })

    expect(await screen.findByText('admin screen')).toBeInTheDocument()
    expect(window.location.pathname).toBe('/admin')
  })

  it('says nothing opens a page whose module this page has no code for', async () => {
    mockedGetModuleFeed.mockResolvedValue({
      contract: 1,
      home: '/query',
      modules: [
        {
          id: 'elsewhere',
          name: 'Elsewhere',
          version: '1',
          entry: null,
          contributes: { pages: [{ id: 'main', path: '/elsewhere' }] },
        },
      ],
    })
    mockedGetMyVisibleSchema.mockResolvedValue({})
    window.history.pushState({}, '', '/elsewhere')
    render(<App />)

    expect(await screen.findByText(/belongs to the module/)).toHaveTextContent('elsewhere')
  })
})

describe('App -- a module feed that cannot be had', () => {
  it('says so, rather than loading for ever', async () => {
    /** BEFORE THE FEED, A FAILURE LEFT THE ROUTES IN PLACE. With the
     *  routes made from the feed, a silent failure would leave every
     *  page on "Loading" with nothing to say why. */
    mockedGetModuleFeed.mockRejectedValue(new ApiError(500, 'the configuration could not be read'))
    mockedGetMyVisibleSchema.mockResolvedValue({})
    render(<App />)

    expect(await screen.findByRole('alert')).toHaveTextContent(/the configuration could not be read/)
    expect(screen.queryByText('Loading…')).not.toBeInTheDocument()
  })

  it('still signs the person out on an expired session', async () => {
    mockedGetModuleFeed.mockRejectedValue(new ApiError(401, 'session expired'))
    mockedGetMyVisibleSchema.mockResolvedValue({})
    render(<App />)

    expect(await screen.findByText('login screen')).toBeInTheDocument()
  })

  it('refuses a feed in another contract version by name', async () => {
    mockedGetModuleFeed.mockResolvedValue({ contract: 2, home: '/query', modules: [] })
    mockedGetMyVisibleSchema.mockResolvedValue({})
    render(<App />)

    expect(await screen.findByRole('alert')).toHaveTextContent(/contract 2/)
  })
})

describe('App -- modules with bundles of their own', () => {
  afterEach(() => window.history.pushState({}, '', '/'))

  it('says which module could not be loaded when its bundle cannot be fetched, and keeps the rest', async () => {
    // jsdom cannot import a bundle at all, which makes it a faithful
    // stand-in for one that was never built or answered 404.
    mockedGetModuleFeed.mockResolvedValue({
      contract: 1,
      home: '/query',
      modules: [
        {
          id: 'query',
          name: 'Query',
          version: '1',
          entry: QUERY_BUNDLE,
          styles: [],
          contributes: { pages: [{ id: 'query', path: '/query' }], nav: [{ title: 'Query', path: '/query' }] },
        },
        {
          id: 'graph',
          name: 'Graph',
          version: '1',
          entry: '/api/modules/graph/files/dist/index.js',
          styles: [],
          contributes: { pages: [{ id: 'main', path: '/graph' }], nav: [{ title: 'Graph', path: '/graph' }] },
        },
      ],
    })
    mockedGetMyVisibleSchema.mockResolvedValue({})
    window.history.pushState({}, '', '/graph')
    render(<App />)

    expect(await screen.findByRole('alert')).toHaveTextContent(/graph could not be loaded/)
    expect(screen.getByRole('menuitem', { name: 'Query' })).toBeInTheDocument()
  })

  it('publishes what pages need, for modules that cannot be handed props', async () => {
    function Reader() {
      const { username, visibleSchema } = useHostValues()
      return (
        <p>
          published: {username} / {Object.keys(visibleSchema ?? {}).join(',')}
        </p>
      )
    }
    mockedGetMyVisibleSchema.mockResolvedValue({ Customer: { fields: {} } })
    render(
      <>
        <App />
        <Reader />
      </>,
    )

    expect(await screen.findByText('published: testuser / Customer')).toBeInTheDocument()
  })
})
