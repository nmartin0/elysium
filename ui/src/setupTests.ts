// setupTests.ts -- runs once before every test file. Adds jest-dom's
// own matchers (toBeInTheDocument, etc.) to Vitest's expect(), the
// standard pairing confirmed directly against current (2026) docs
// before adopting it, not assumed from memory.
import { expect } from 'vitest'
import '@testing-library/jest-dom'
import { configure } from '@testing-library/dom'

// RTL'S OWN TIMEOUT, WHICH VITEST'S DOES NOT COVER.
//
// `waitFor` and every `findBy*` built on it default to 1,000ms --
// Testing Library's knob, not vitest's, so raising `testTimeout` in
// vite.config.ts does nothing for them. SchemaPanel's "filters object
// types by name" overran it on the owner's machine: the filter box
// debounces through useDeferredValue, and a debounce plus a re-render
// exceeded a second under a run that took 1,942 seconds where mine
// takes 280.
//
// Five seconds, not thirty. A findBy that needs longer than that is
// waiting for something that is not coming, and the failure should
// arrive while somebody still remembers what they changed.
configure({ asyncUtilTimeout: 5_000 })

// window.matchMedia -- jsdom itself does not implement this API at
// all (a real, well-known, longstanding gap, confirmed directly by
// the real TypeError this produced the first time Shell.tsx's own
// getInitialCollapsedState() ran under a real test, not assumed
// upfront). A safe, standard default here (always reports "no match"
// -- effectively "not a narrow viewport") so every OTHER test that
// merely renders something touching matchMedia doesn't crash;
// individual tests that need to exercise a SPECIFIC matchMedia result
// (e.g. simulating a narrow viewport) can override this with their
// own vi.spyOn(window, 'matchMedia') -- writable: true is what makes
// that override possible.
//
// Typed against the real, built-in MediaQueryList DOM type (part of
// TypeScript's own lib.dom.d.ts, no extra dependency needed) -- not
// `any`, now that this file is genuinely type-checked as part of the
// Blueprint migration's own hardening pass. No type assertion needed
// either -- confirmed directly, not assumed: this object literal
// satisfies the real MediaQueryList interface structurally on its
// own, once the return type annotation sits directly on the arrow
// function itself. This is the same real shape Shell.test.tsx's own
// per-test matchMedia mocks already had to match by hand; expressing
// it here, once, with real types, is what would catch a shape
// mismatch at compile time instead of only at runtime.
// ONLY WHERE THERE IS A DOM TO PATCH.
//
// Twenty-five of this suite's eighty-five test files exercise pure
// functions -- formatters, selectors, parsers -- and pay for a jsdom
// environment they never touch. Measured on a full run: 72s standing
// up environments and 50s importing, against 75s actually running
// tests.
//
// A file opting out with `// @vitest-environment node` has no
// `window`, and this setup file runs for every file regardless.
// Guarding is what makes the opt-out possible at all.
if (typeof window !== 'undefined') {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string): MediaQueryList => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  })
}

/**
 * An act() warning from OUR OWN components fails the test, unless its
 * file is on the list below.
 *
 * MEASURED: one run produces 83 of these. Most come from Blueprint's
 * internals -- Blueprint6.Icon, Popper, Blueprint6.Text -- which we do
 * not control and cannot wrap. Twenty-five came from our own
 * components across six files; SEVEN ARE FIXED and eighteen remain
 * across five.
 *
 * WHY THEY MATTER. "Not wrapped in act" means a state update landed
 * after the test stopped watching. That is exactly the failure
 * App.test.tsx had: it waited for "query screen", then clicked a
 * button fed by a DIFFERENT fetch, and passed on every machine until
 * one slow enough ran it. A warning is not a proven race -- some are
 * harmless teardown -- but each one marks a place where the test is
 * not watching what the user would see.
 *
 * WHY A GUARD RATHER THAN A FIX. Twenty-five sites need reading one
 * at a time to tell a real race from benign noise, and that is work
 * with judgement in it. What cannot wait is the NOISE: a genuinely
 * diagnostic warning would arrive as number 84 in a list nobody
 * reads. This makes a warning from a file not already known about
 * fail loudly, so the count can only go down.
 *
 * IT FAILS AS AN UNHANDLED ERROR, not as a failing assertion: the
 * throw happens inside console.error, often from an async callback
 * after the test body has finished. vitest sets a non-zero exit code
 * for unhandled errors, so `npm test` fails -- but the test itself may
 * still print as passed. Read the exit code.
 *
 * TO FIX ONE: wrap the state update in act(), or await what the test
 * is actually waiting for, then remove the file from the list. The
 * list going empty is the goal.
 */
const ACT_WARNING = /not wrapped in act/
/** Blueprint's own internals. Not ours to wrap, and exempt by NAME
 *  rather than by file, so our components in the same test still
 *  count. Matched ANYWHERE in the joined arguments, not adjacent to
 *  "An update to": React passes the name as a separate format
 *  argument, so joining puts it at the end. A first version anchored
 *  it to the phrase and exempted nothing. */
const THEIRS = /\b(Blueprint6\.\w+|Popper)\b/

/** Test files that produce act warnings from our own components, with
 *  the count measured by EMPTYING THIS LIST and reading what flagged.
 *
 *  A first version listed twelve files and thirty-three warnings,
 *  derived by grepping the run output for the lines NEAR each warning.
 *  That over-attributed: a Blueprint warning printed inside a test
 *  file was counted against it. Emptying the list and letting the
 *  guard itself report is the only way to get this right, and it is
 *  how the number should be checked whenever it is updated. */
const KNOWN = new Set([
  // Each entry is a count and a REASON. Two kinds are left:
  //
  // TRANSIENT-STATE TESTS, where the point IS the pre-settled frame --
  // "shows Loading… before listUsers resolves" cannot await what it is
  // asserting the absence of. Awaiting first would delete the test.
  // The fix for these is to settle before the test ENDS, not before
  // the assertion, and that is a different edit.
  //
  // NOT-YET-READ, which are probably the same mount-fetch race
  // PendingWriteCard had and are simply not done.
  'ObjectSearchPanel.test.tsx', // 7 -- 3 transient-state, 4 not yet read
  'AdminPanel.test.tsx', // 5 -- 1 transient-state, 4 not yet read
  'UserMenu.test.tsx', // 3 -- not yet read
  'MirrorPanel.test.tsx', // 2 -- the 30s poll test, not yet read
  'useFetchOnce.test.tsx', // 1 -- its own Harness, deliberate
])

const reportError = console.error.bind(console)
console.error = (...args: unknown[]) => {
  // EVERY ARGUMENT, not just the strings. React formats this warning
  // as "An update to %s inside a test was not wrapped in act(...)"
  // with the COMPONENT NAME as a separate argument -- so a first
  // version of this guard read only the format string, never saw a
  // component name at all, and would have thrown on Blueprint's own
  // warnings as readily as ours. It caught itself on the first run.
  const text = args.map((a) => (typeof a === 'string' ? a : String(a))).join(' ')
  if (ACT_WARNING.test(text) && !THEIRS.test(text)) {
    const state = expect.getState()
    const file = (state.testPath ?? '').split('/').pop() ?? ''
    if (!KNOWN.has(file)) {
      // THE TEST NAME, not just the file. A warning you cannot
      // attribute to one test is half a warning: finding which of
      // forty tests it belongs to by bisection is the work this line
      // removes, and it is how the six files below were triaged.
      throw new Error(
        `act() warning from our own component in ${file}\n` +
          `  test: ${state.currentTestName ?? '(outside a test)'}\n` +
          `A state update landed after the test stopped watching. Either await what the test is ` +
          `really waiting for, or add the file to KNOWN and say why.\n\n${text}`,
      )
    }
  }
  reportError(...args)
}
