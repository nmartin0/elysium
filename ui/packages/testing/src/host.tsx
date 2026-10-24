/**
 * THE TEST HOST: a module's page rendered inside a faithful frame, and a
 * server whose answers a test chooses.
 *
 * BLOCKING.md item 3: the provider "SHIPS A TEST HOST ... so a sub-app's
 * tests render inside a faithful frame instead of hand-mocking". The
 * precedent is Backstage's `renderInTestApp` with `mockApis`, where a
 * mock "returns a working fake".
 *
 * THE FRAME is what Elysium's page gives a module: a router, Blueprint's
 * overlays, and the host values (@elysium/shell-api/host) published. A
 * page that renders here renders in the shell.
 *
 * THE SERVER IS STUBBED AT `fetch`, not by mocking the API module. Every
 * call a page makes goes through the kit's client to `fetch`, so one
 * switch makes every call hang, fail or find the session expired, with
 * no list of functions to keep in step with the client -- the hand-mocks
 * this replaces each named the functions they knew about.
 */
import { OverlaysProvider } from '@blueprintjs/core'
import { publishHostValues, resetHostValues, type HostValues } from '@elysium/shell-api/host'
import { act, render, type RenderResult } from '@testing-library/react'
import { Suspense, type ReactElement } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { vi, type Mock } from 'vitest'

export interface TestHostOptions {
  /** The address the page is opened at. */
  route?: string
  /** What the host publishes; anything left out gets a harmless default. */
  hostValues?: Partial<HostValues>
}

export interface TestHost extends RenderResult {
  /** The values published, including the session-expiry handler to assert on. */
  hostValues: HostValues & { onSessionExpired: Mock<() => void> }
}

/** What the frame shows while a page's code is still arriving -- a page
 *  a module loads on demand (React's `lazy`), as Browse's are. No role,
 *  so it is never mistaken for the page's own loading state or alert;
 *  the conformance suite waits for it to go before checking anything. */
export const SUSPENDED_ATTRIBUTE = 'data-test-host-suspended'

/** Renders `ui` as the shell would mount a module's page: inside a
 *  Suspense boundary, as the frame's own around its outlet. */
export function renderInTestHost(ui: ReactElement, options: TestHostOptions = {}): TestHost {
  const hostValues = {
    visibleSchema: {},
    username: 'conformance',
    ...options.hostValues,
    onSessionExpired: vi.fn<() => void>(),
  }
  if (options.hostValues?.onSessionExpired)
    hostValues.onSessionExpired.mockImplementation(options.hostValues.onSessionExpired)
  act(() => publishHostValues(hostValues))
  const result = render(
    <OverlaysProvider>
      <MemoryRouter initialEntries={[options.route ?? '/']}>
        <Suspense fallback={<span {...{ [SUSPENDED_ATTRIBUTE]: '' }} />}>{ui}</Suspense>
      </MemoryRouter>
    </OverlaysProvider>,
  )
  return Object.assign(result, { hostValues })
}

/** What the stubbed server does with every request. */
export type ServerAnswer = { kind: 'pending' } | { kind: 'status'; status: number; body?: unknown }

export interface StubServer {
  /** How many requests reached it. */
  requests: () => number
  /** Answers every request still waiting, as `answer`. */
  settle: (answer: ServerAnswer) => void
}

/**
 * Replaces `fetch` for the rest of the test (restored by
 * `vi.unstubAllGlobals()`, which the conformance suite calls after each
 * check). `pending` holds every request open until `settle`.
 */
export function stubServer(answer: ServerAnswer): StubServer {
  const waiting: ((response: Response) => void)[] = []
  let count = 0
  const respond = (a: Exclude<ServerAnswer, { kind: 'pending' }>) =>
    new Response(JSON.stringify(a.body ?? { detail: `The conformance server answered ${a.status}.` }), {
      status: a.status,
      headers: { 'Content-Type': 'application/json' },
    })
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      count += 1
      if (answer.kind === 'status') return respond(answer)
      return new Promise<Response>((resolve) => waiting.push(resolve))
    }),
  )
  return {
    requests: () => count,
    settle: (next) => {
      for (const resolve of waiting.splice(0)) {
        resolve(next.kind === 'status' ? respond(next) : new Response('{}', { status: 200 }))
      }
    },
  }
}

/** Back to nothing published, for the end of a test. */
export function resetTestHost(): void {
  act(() => resetHostValues())
}
