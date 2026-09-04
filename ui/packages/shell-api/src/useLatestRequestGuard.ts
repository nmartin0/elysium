import { useRef } from 'react'

// useLatestRequestGuard.ts  (extracted during a full-migration review
// pass, requested directly -- "make sure we've followed our
// programming principles... DRY" -- found as a real, genuine gap:
// ObjectSearchPanel.tsx and ObjectDetailPanel.tsx each independently
// hand-wrote the exact same useRef(0) + increment-and-compare guard,
// with ObjectDetailPanel's own comment already, explicitly saying
// "Same stale-response guard as ObjectSearchPanel's own live search"
// -- correctly IDENTIFIED as the same pattern, but never actually
// extracted, leaving two real, independent copies that could
// silently drift out of sync with each other (e.g. a real bug fixed
// in one copy but not the other).
//
// The real, well-known race this guards against: two in-flight
// requests can resolve in either order over a real network. Without
// this, a slower, EARLIER request's response could overwrite a
// faster, LATER one's already-correct results -- not a hypothetical,
// confirmed as the exact, real motivation for BOTH original call
// sites (ObjectSearchPanel's own live, debounced search; ObjectDetailPanel's
// own rapid navigation between two different objects on the same
// route pattern, which React Router re-renders in place rather than
// unmounting/remounting).
//
// A small, deliberately minimal API -- startRequest()/isStale(id), not
// a bigger abstraction hiding the fetch itself. Every real call site
// has its own, genuinely different response shape and error handling
// (ObjectSearchPanel sets two separate pieces of state on success;
// ObjectDetailPanel sets one, and unlike ObjectSearchPanel, never shows
// "Searching..." for a stale request since ObjectDetailPanel has no
// live/debounced search concept at all) -- trying to also own the
// fetch/response handling itself would force a single, generic shape
// onto two real, legitimately different situations. This hook owns
// only the one, real, shared concern both already had: "is the
// response I just got still the one that matters."
export function useLatestRequestGuard() {
  const latestRequestId = useRef(0)

  function startRequest(): number {
    return ++latestRequestId.current
  }

  function isStale(requestId: number): boolean {
    return requestId !== latestRequestId.current
  }

  return { startRequest, isStale }
}
