// types.ts (shared, cross-sub-app contract types)
//
// SubAppProps -- the one, minimum contract EVERY sub-app route is
// guaranteed to receive from the shell, formalized here as a real,
// exported TypeScript interface rather than left as an implicit,
// by-convention pattern each sub-app's own props interface previously
// happened to independently, identically redeclare (confirmed
// directly by reading all four: QueryPanelProps, ObjectSearchPanelProps,
// ObjectDetailPanelProps, AdminPanelProps -- every one declared
// `onSessionExpired: () => void` on its own, word for word).
//
// Extend this, don't redeclare its own fields -- see any real sub-app
// (e.g. QueryPanel.tsx) for the current pattern. Genuinely enforced
// by the type checker now, not just true by convention: a sub-app
// that forgets to accept onSessionExpired, or accepts it with the
// wrong signature, fails to typecheck against App.tsx's own real
// <Route> wiring, rather than silently compiling and only failing
// at runtime the first time a 401 actually happens.
//
// Deliberately narrow -- ONLY the field every real sub-app route
// genuinely, currently receives. Not a home for anything a given
// sub-app happens to also need (visibleSchema, for instance, is real
// but only used by two of the four routes) -- those stay each sub-
// app's own, additional, individually-declared props, extending this
// base rather than folded into it.
export interface SubAppProps {
  // Fired the moment any real api.ts call this sub-app makes comes
  // back with a 401 -- see api.ts's own handleIfSessionExpired() for
  // the real, shared detection logic every sub-app already,
  // consistently routes its own catch blocks through. App.tsx passes
  // its own real handleSessionExpired (resets auth state, returns to
  // the login screen) as this prop on every real route.
  onSessionExpired: () => void
}
