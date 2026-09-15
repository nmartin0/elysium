/**
 * rangeSelection.ts -- Shift-click to select everything between.
 *
 * THE ESTABLISHED PATTERN IS ANCHOR-BASED: the first clicked row is
 * the anchor; Shift and a second click set every row between them to
 * the second row's state; the second click becomes the new anchor.
 * Excel, Gmail, Outlook and Finder all behave this way, and people
 * arrive expecting it.
 *
 * TWO PITFALLS OTHERS SHIPPED AND DOCUMENTED, both avoided here
 * deliberately rather than by luck.
 *
 * A STALE ANCHOR. Sentry shipped a bug where deselecting everything
 * left the anchor pointing at a row no longer selected, so the next
 * shift-click "would then range-extend from that ghost anchor". Their
 * fix was to clear the anchor whenever the selection empties, and that
 * is what `nextAnchor` does below.
 *
 * INDICES VERSUS IDENTITY. An Angular thread is explicit that `$index`
 * breaks the moment a list is sorted, filtered or paged -- "as soon as
 * I filter or change the sort order... $index is useless to me". OUR
 * LIST IS ALL THREE. So the range is computed over the ids CURRENTLY
 * ON SCREEN, in the order they are displayed, and the anchor is an id
 * rather than a position. An anchor that has scrolled out of the
 * current page simply is not found, and the click falls back to a
 * plain toggle -- which is the honest answer, because there is no
 * defensible range between a row you can see and one you cannot.
 *
 * THE SECOND CLICK'S STATE WINS, not "always select". Shift-clicking
 * an already-selected row DESELECTS the range, which is what makes the
 * gesture usable for correcting a mistake rather than only for making
 * one.
 */

export interface RangeSelectionResult {
  selected: Set<string>
  /** The id to treat as the anchor for the NEXT shift-click, or null
   *  when there should not be one. */
  anchor: string | null
}

/** Applies a click, with or without Shift, to the current selection.
 *
 * PURE, AND TAKES THE DISPLAYED ORDER AS AN ARGUMENT. The caller knows
 * what is on screen and in what order; this knows the rules. Keeping
 * them apart is what stops the rules being re-derived every time the
 * list gains a sort or a filter.
 */
export function applyClick(
  clickedId: string,
  displayedIds: readonly string[],
  selected: ReadonlySet<string>,
  anchor: string | null,
  withShift: boolean,
): RangeSelectionResult {
  const next = new Set(selected)

  const anchorIndex = anchor === null ? -1 : displayedIds.indexOf(anchor)
  const clickedIndex = displayedIds.indexOf(clickedId)

  // A PLAIN CLICK, or a shift-click with nowhere to range FROM -- no
  // anchor yet, or an anchor that has left the page. Both are ordinary
  // states rather than errors, and both mean "just toggle this one".
  if (!withShift || anchorIndex === -1 || clickedIndex === -1) {
    if (next.has(clickedId)) next.delete(clickedId)
    else next.add(clickedId)
    return { selected: next, anchor: nextAnchor(clickedId, next) }
  }

  // THE CLICKED ROW'S NEW STATE, applied to the whole range. Its
  // CURRENT state is what decides: shift-clicking a selected row
  // deselects the range.
  const selecting = !next.has(clickedId)

  const from = Math.min(anchorIndex, clickedIndex)
  const to = Math.max(anchorIndex, clickedIndex)
  for (let index = from; index <= to; index += 1) {
    const id = displayedIds[index]
    if (id === undefined) continue
    if (selecting) next.add(id)
    else next.delete(id)
  }

  return { selected: next, anchor: nextAnchor(clickedId, next) }
}

/** The anchor to keep, or null when keeping one would be wrong.
 *
 * CLEARED WHEN THE SELECTION EMPTIES, which is the documented bug this
 * avoids: an anchor surviving an empty selection makes the next
 * shift-click extend from a row nobody selected. Sentry's repro is
 * exactly that -- deselect every row one by one, then shift-click a
 * single row, and get a range instead.
 */
function nextAnchor(clickedId: string, selected: ReadonlySet<string>): string | null {
  return selected.size === 0 ? null : clickedId
}
