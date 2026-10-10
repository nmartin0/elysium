/**
 * What you are looking at, named by how it was built.
 *
 * DEV_UI.md 11.1: "everything on screen IS a set, named by how it was
 * built (`Customer · 3 filters · 1,284`), so the interface always has a
 * subject and saving is a PROMOTION rather than a creation."
 *
 * AND 11.6 SAYS WHERE IT GOES: "the set is the SUBJECT, so it belongs
 * in the top bar, where a document's name sits. Everything else is
 * about it: left is ways to change the set, centre is the set viewed
 * somehow, right is about one member." That is also why the page
 * titles I put on every app came back out -- an app name is the wrong
 * thing in that place.
 *
 * WHY THE PARTS ARE WHAT THEY ARE. The type says what KIND of thing;
 * the filter count says how narrowed it is without listing the filters
 * again, which the bar below already does; the total says how big.
 * Together they are what a person would say out loud if asked what
 * they were looking at.
 *
 * LIVE, AND IT SAYS SO. 11.3: every mature product ships two kinds of
 * set and "whichever a person is looking at must say so on its face",
 * because the two failure modes are both FAQ entries -- "why are
 * contacts dropping off my list?" (it is live) and "why isn't my list
 * updating?" (it is frozen). Elysium has only live sets today, so this
 * says Live rather than staying silent and leaving the question open
 * when frozen ones arrive.
 *
 * WHAT THIS IS NOT YET. A set here is a DESCRIPTION, not a thing the
 * backend knows about. 11.2's audit finding: "there is no set object in
 * the backend at all ... a set needs a REPRESENTATION (object type +
 * conditions + the traversal chain that produced it)". Naming it is
 * the half that can be done without that, and it is what makes the
 * absence of the other half visible.
 */

import StatusTag from '@elysium/shell-api/components/StatusTag'

import AskAboutSet from './AskAboutSet'

export default function SetName({
  objectType,
  filterCount,
  total,
  loading,
  actions,
}: {
  objectType: string | null
  filterCount: number
  /** How many objects match. */
  total: number
  /** While a search is in flight the old count is a lie; the name keeps
   *  its shape and drops the number rather than flickering a stale one. */
  loading?: boolean
  /** Anything that acts on the SET rather than on a row -- the export,
   *  today. Passed in rather than imported here, because this
   *  component is the subject's name and should not grow a dependency
   *  on every verb somebody adds to it. */
  actions?: React.ReactNode
}) {
  if (!objectType) return null

  return (
    <p className="set-name">
      <span className="set-name__type">{objectType}</span>
      {filterCount > 0 && (
        <>
          <span className="set-name__dot" aria-hidden="true">
            ·
          </span>
          <span className="set-name__filters">
            {filterCount} {filterCount === 1 ? 'filter' : 'filters'}
          </span>
        </>
      )}
      {!loading && (
        <>
          <span className="set-name__dot" aria-hidden="true">
            ·
          </span>
          <span className="set-name__total">{total.toLocaleString()}</span>
        </>
      )}
      <StatusTag state="active">Live</StatusTag>
      {/* The agent, where the subject is. DEV_UI.md 5.4 wants it "inside
          Browse, seeded with what is on screen" rather than in its own
          app -- and the set's name is exactly what is on screen. */}
      {/* BOTH ACT ON THE SUBJECT, so both sit beside it. The export
          comes first because it is the commoner verb; the agent link
          is the one somebody goes looking for. */}
      {!loading && actions}
      {!loading && <AskAboutSet objectType={objectType} filterCount={filterCount} total={total} />}
    </p>
  )
}
