// setupTests.ts -- runs once before every test file. Adds jest-dom's
// own matchers (toBeInTheDocument, etc.) to Vitest's expect(), the
// standard pairing confirmed directly against current (2026) docs
// before adopting it, not assumed from memory.
import '@testing-library/jest-dom'

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
