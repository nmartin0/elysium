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

// --- The ontology, as GET /me/visible-schema returns it -------------
//
// Here rather than in a module of its own: this file is already "the
// cross-sub-app contract types", and that is exactly what these are.
// Browse renders objects with them, Schema browses them, the shell
// holds and passes them down. A second types module for the same
// purpose is the duplication this file exists to prevent.
//
// These lived in app-browse/ObjectDetailPanel, because that is the
// file that happened to need them first -- which made app-schema
// import from app-browse and inverted the package layering.
//
// Every field is optional except `type`, matching the API: an
// ontology declaring no display metadata is valid and renders from
// derived labels.

export interface FieldSchema {
  type: string
  /** Whether this field's VALUE may be read.
   *
   *  False is the middle rung of the grant ladder: the caller holds
   *  `discover:Type.field` and not `read:Type.field`, so they may know
   *  the field exists and not what it holds. The field is still
   *  present here -- omitting it would leave a reader unable to tell a
   *  partial view from a complete one, which is the rubber-stamp
   *  problem the approvals diff already solves this way.
   *
   *  Optional because the agent's own view of the schema omits
   *  unreadable fields entirely, so anything it receives is readable.
   */
  readable?: boolean
  /** How many decimal places this field is worth showing, if the
   *  ontology says. Absent means show the value as it arrived --
   *  there is no sensible default, which is why it is declared rather
   *  than guessed. */
  decimal_places?: number | null
  target?: string
  // Added by SchemaPanel, the next consumer to need more of this
  // shape -- optional, so nothing that already reads it changes.
  display_name?: string
  description?: string | null
  cardinality?: string | null
  link_type?: string | null
  /** The SEMANTIC type the ontology declares -- string, integer,
   *  number, decimal, boolean, date, timestamp, timestamptz.
   *
   *  TWO CONSUMERS NOW. The filter vocabulary validates against it,
   *  which is why it was added. And FORMATTING needs it: the UI
   *  cannot infer that '2026-03-12' is a date when
   *  'ACME-2026-03-12' is also a string, so without this a date
   *  renders as text and a timestamp is never converted to the
   *  reader's zone.
   *
   *  Absent means the author declared none; the server then accepts
   *  any operator and the UI shows the value as it arrived. */
  data_type?: string
  visibility?: string
  status?: string
}

export interface TypeSchema {
  /** Whether this type may be SEARCHED.
   *
   *  False means the caller holds `discover:Type` and not `read:Type`:
   *  they may know the type exists, and it yields no ids. A search box
   *  would return nothing, so offering one would be a lie about what
   *  the deployment will do.
   */
  readable?: boolean
  title_field?: string | null
  fields?: Record<string, FieldSchema>
  // Display metadata. Every one is optional at the API too -- an
  // ontology declaring none of it is valid, and renders from derived
  // labels.
  display_name?: string
  plural_display_name?: string
  description?: string | null
  icon?: string | null
  color?: string | null
  status?: string
  group?: string | null
  id_field?: string | null
}

export type VisibleSchema = Record<string, TypeSchema>
