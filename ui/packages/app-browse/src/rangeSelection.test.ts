/**
 * Shift-click to select everything between.
 *
 * ANCHOR-BASED, which is the established pattern: the first clicked
 * row is the anchor; Shift and a second click set every row between
 * them to the second row's state; the second click becomes the new
 * anchor. Excel, Gmail, Outlook and Finder all behave this way, and
 * people arrive expecting it.
 *
 * TWO PITFALLS OTHERS SHIPPED AND DOCUMENTED have their own describe
 * blocks below. Both were cheaper to read about than to rediscover.
 */

import { describe, expect, it } from 'vitest'

import { applyClick } from './rangeSelection'

const ROWS = ['a', 'b', 'c', 'd', 'e']

/** Applies a sequence of clicks, so a test reads like the gesture. */
function clicks(...steps: Array<[string, boolean]>) {
  let selected = new Set<string>()
  let anchor: string | null = null
  for (const [id, withShift] of steps) {
    const outcome = applyClick(id, ROWS, selected, anchor, withShift)
    selected = outcome.selected
    anchor = outcome.anchor
  }
  return { selected: [...selected].sort(), anchor }
}

describe('the basic gesture', () => {
  it('a plain click selects one row', () => {
    expect(clicks(['b', false]).selected).toEqual(['b'])
  })

  it('shift selects everything between the anchor and the click', () => {
    expect(clicks(['b', false], ['d', true]).selected).toEqual(['b', 'c', 'd'])
  })

  it('works in either direction', () => {
    // Clicking upward is the same gesture, and a range computed with
    // min/max rather than assuming order is what makes it so.
    expect(clicks(['d', false], ['b', true]).selected).toEqual(['b', 'c', 'd'])
  })

  it('the second click becomes the new anchor', () => {
    // So a third shift-click extends from there, not from the
    // original -- which is what "multiple times" means in practice.
    expect(clicks(['a', false], ['b', true], ['d', true]).selected).toEqual(['a', 'b', 'c', 'd'])
  })

  it('shift-clicking a selected row DESELECTS the range', () => {
    // The clicked row's new state wins, not "always select". This is
    // what makes the gesture usable for correcting a mistake rather
    // than only for making one.
    //   click a        -> {a},           anchor a
    //   shift-click e  -> {a,b,c,d,e},   anchor e
    //   shift-click c  -> c is selected, so the range c..e is
    //                     DESELECTED, leaving {a,b}
    //
    // Written out because I got it wrong first time: the range runs
    // from the CURRENT anchor (e), not from the original click (a).
    const result = clicks(['a', false], ['e', true], ['c', true])

    expect(result.selected).toEqual(['a', 'b'])
  })

  it('a plain click after a range toggles only that row', () => {
    // THE CONTROL. A shift-less click that extended anyway would make
    // the modifier meaningless.
    expect(clicks(['b', false], ['d', true], ['a', false]).selected).toEqual(['a', 'b', 'c', 'd'])
  })
})

describe('the stale-anchor bug, which Sentry shipped and documented', () => {
  /**
   * Their repro: shift-click every row off one by one, ending with an
   * empty selection, then shift-click a single row -- and get a range
   * instead, because "the anchor lingers" on a row nobody selected.
   *
   * The fix is to clear the anchor whenever the selection empties.
   */
  it('clears the anchor when the selection becomes empty', () => {
    const result = clicks(['a', false], ['a', false])

    expect(result.selected).toEqual([])
    expect(result.anchor).toBeNull()
  })

  it('a shift-click after emptying behaves as a plain click', () => {
    // Sentry's exact sequence, in miniature: select, deselect to
    // nothing, then shift-click elsewhere. Without the fix this
    // returns a range from the ghost anchor.
    const result = clicks(['a', false], ['a', false], ['c', true])

    expect(result.selected).toEqual(['c'])
  })

  it('keeps the anchor while anything is still selected', () => {
    // THE CONTROL on the fix. Clearing too eagerly would break the
    // ordinary case, where a range is built up over several clicks.
    const result = clicks(['a', false], ['b', false])

    expect(result.anchor).toBe('b')
  })
})

describe('identity rather than index, because the list moves', () => {
  /**
   * An Angular thread is explicit that `$index` breaks the moment a
   * list is sorted, filtered or paged -- "as soon as I filter or
   * change the sort order... $index is useless to me".
   *
   * OUR LIST IS ALL THREE, so the anchor is an id and the range is
   * computed over what is on screen NOW.
   */
  it('ranges over the displayed order, not the underlying one', () => {
    // The same ids in a different order produce a different range,
    // which is correct: a person means what they can see.
    const reversed = ['e', 'd', 'c', 'b', 'a']
    const outcome = applyClick('a', reversed, new Set(['e']), 'e', true)

    expect([...outcome.selected].sort()).toEqual(['a', 'b', 'c', 'd', 'e'])
  })

  it('falls back to a plain toggle when the anchor has left the page', () => {
    // There is no defensible range between a row you can see and one
    // you cannot, so this toggles rather than guessing.
    const outcome = applyClick('c', ROWS, new Set(['z']), 'z', true)

    expect([...outcome.selected].sort()).toEqual(['c', 'z'])
  })

  it('falls back when the clicked row is somehow not displayed', () => {
    const outcome = applyClick('z', ROWS, new Set(['a']), 'a', true)

    expect([...outcome.selected].sort()).toEqual(['a', 'z'])
  })
})
