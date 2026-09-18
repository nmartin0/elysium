/**
 * SelectionBar -- what an action would apply to, said before it does.
 *
 * FOUNDRY'S RULE, and it is the one that shapes this: an action
 * receives "the current set of selected objects in your exploration
 * (or all objects, if none are selected)". So selecting nothing does
 * not mean acting on nothing -- it means acting on everything the
 * filter matched.
 *
 * THAT IS THE DANGEROUS PART. A person who clears their selection
 * intending to cancel would, on pressing an action, hit the whole
 * result set instead. So the bar states which of the two is in force,
 * always, in the same words the action will use.
 *
 * THE COUNT IS THE SAFETY FEATURE. "Selection count appears in the
 * toolbar" in Foundry's own results table, and the reason is that
 * "apply to 3" and "apply to 4,000" are different decisions that
 * otherwise look identical.
 *
 * THE CEILING IS SHOWN WHEN IT BINDS, rather than discovered on
 * submit. MAX_BULK_OBJECTS is 1000 in the write mediator -- a person
 * who has selected 1,200 objects should learn that before filling in a
 * form, not after.
 */

import { Button, Tag } from '@blueprintjs/core'

/** Matches MAX_BULK_OBJECTS in core/ontology/write_mediator.py. Declared
 *  rather than fetched: the server refuses regardless, so this is a
 *  courtesy, and a courtesy that is briefly out of date is better than
 *  a request on every render. */
const MAX_BULK_OBJECTS = 1000

interface SelectionBarProps {
  /** How many objects are explicitly selected. */
  selectedCount: number
  /** How many the current filter matches, selected or not. */
  matchCount: number
  /** Selects every object the filter matches, not only those shown.
   *  Absent when there is nothing beyond the page to select. */
  onSelectAllMatching?: () => void
  /** True while that selection is being resolved by the server. */
  selectingAll?: boolean
  /** How many are on screen right now. Differs from matchCount as soon
   *  as results are paged, and an action with no selection reaches
   *  only these -- so this is the number the bar must promise. */
  pageCount: number
  onClear: () => void
}

export default function SelectionBar({
  selectedCount,
  matchCount,
  pageCount,
  onClear,
  onSelectAllMatching,
  selectingAll,
}: SelectionBarProps) {
  // NOTHING SELECTED AND NOTHING MATCHED means there is no set to
  // describe, and a bar saying so would be noise.
  if (matchCount === 0) return null

  // WHAT AN ACTION WOULD ACTUALLY REACH, which is the page rather than
  // every match when nothing is selected. Foundry's select-all "selects
  // all objects matching the applied filters, not just the objects on
  // the current page"; we hold one page, so promising every match would
  // be a quiet under-application -- fewer objects touched than the
  // person was just told, with nothing looking wrong afterwards.
  const acting = selectedCount > 0 ? selectedCount : pageCount
  const pagedBeyondView = selectedCount === 0 && matchCount > pageCount
  const overCeiling = acting > MAX_BULK_OBJECTS

  return (
    <div className="selection-bar" aria-live="polite">
      <Tag minimal intent={overCeiling ? 'warning' : 'none'}>
        {selectedCount > 0 ? `${selectedCount} selected` : `No selection — actions apply to the ${pageCount} shown`}
      </Tag>

      {pagedBeyondView && (
        // SAID OUT LOUD, because the gap is invisible otherwise: the
        // count says 20 and the filter matched 500, and nothing on
        // screen connects the two.
        <>
          <Tag minimal>{matchCount - pageCount} more match the filter</Tag>
          {onSelectAllMatching !== undefined && (
            // AN EXPLICIT CONTROL, not an overloaded checkbox. The
            // guidance is to "make it explicit (e.g. 'Select all 3,200
            // matching items')" -- a header checkbox that sometimes
            // means the page and sometimes means the filter is a
            // control whose meaning depends on state nobody can see.
            //
            // THE COUNT IS IN THE LABEL for the same reason: this is
            // the click that turns 20 into 500, and it should say so
            // before it is pressed rather than after.
            <Button minimal small loading={selectingAll} onClick={onSelectAllMatching}>
              Select all {matchCount} matching
            </Button>
          )}
        </>
      )}

      {overCeiling && (
        // NAMED BEFORE THE FORM, not refused after it. The server
        // enforces this regardless; the point of saying it here is
        // that a person can narrow the filter while they still
        // remember what they were doing.
        <Tag minimal intent="warning">
          Over the {MAX_BULK_OBJECTS} limit — narrow the filter to act on these
        </Tag>
      )}

      {selectedCount > 0 && (
        <Button minimal small onClick={onClear} aria-label="Clear selection">
          Clear
        </Button>
      )}
    </div>
  )
}
