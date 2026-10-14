/**
 * TableSkeleton -- the loading state for a table whose shape is known
 * (DEV_UI 9.7, E1).
 *
 * "LOADING, chosen by expected wait, not by taste":
 *
 *   under 100ms   nothing. An indicator that flashes is worse than none.
 *   100ms - 1s    an inline cue, no layout change.
 *   over 1s       a skeleton IN THE SHAPE OF THE INCOMING LAYOUT.
 *
 * THE DELAY IS CSS, NOT A TIMER. The skeleton is rendered at once and
 * stays transparent until a second has passed (animation-delay), so a
 * fast answer replaces it before anyone sees it and there is no timer
 * state to clean up. "Skeletons are aria-hidden; a polite live region
 * says 'loading'" -- the caller's status text is that region.
 *
 * The shimmer is off under prefers-reduced-motion: it is "the canonical
 * vestibular trigger".
 */

interface TableSkeletonProps {
  /** How many rows to sketch -- about a screen's worth. */
  rows?: number
  /** How many columns, so the sketch has the table's own shape. */
  columns?: number
}

export default function TableSkeleton({ rows = 8, columns = 4 }: TableSkeletonProps) {
  return (
    <div className="table-skeleton" aria-hidden="true">
      {Array.from({ length: rows }, (_, row) => (
        <div key={row} className="table-skeleton__row">
          {Array.from({ length: columns }, (_, column) => (
            <span key={column} className="table-skeleton__cell" />
          ))}
        </div>
      ))}
    </div>
  )
}
