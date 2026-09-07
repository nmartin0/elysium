/**
 * One search box, used by all three list tabs.
 *
 * Object types had a filter and the other two did not, which is the
 * kind of difference that reads as an oversight rather than a
 * decision -- because it was one.
 *
 * The clear button appears only when there is something to clear. A
 * permanently visible one is a control that does nothing most of the
 * time, and an empty field already looks empty.
 */

import { useEffect, useRef, useState } from 'react'
import { Button, InputGroup } from '@blueprintjs/core'

/** How many recently-sent values to remember. An echo arrives at most
 *  a render or two late, so sixteen is generous. */
export const RECENT_SENT = 16

/**
 * The echo record, bounded, newest last.
 *
 * A separate exported function because the BOUND is the property worth
 * testing and it cannot be observed from rendered output -- a test
 * that only types into the box and asserts the box looks right passes
 * whether or not the record grows. That test was written first and
 * proved hollow against a deliberately unbounded version.
 */
export function rememberSent(previous: readonly string[], next: string): string[] {
  return [...previous, next].slice(-RECENT_SENT)
}

interface FilterBoxProps {
  value: string
  onChange: (value: string) => void
  placeholder: string
}

export default function FilterBox({ value, onChange, placeholder }: FilterBoxProps) {
  // THE INPUT IS DRIVEN BY LOCAL STATE, not directly by the URL.
  //
  // Driving it from the URL dropped keystrokes when typing quickly:
  // each character triggers a router navigation, which is
  // asynchronous, so React would re-render with the PREVIOUS value
  // still in the URL and overwrite the character just typed. Typing
  // "Cust" produced "Cut" or "Cst".
  //
  // Local state is authoritative while the field has focus. The URL
  // is still updated on every keystroke -- it is what makes the view
  // shareable and reloadable -- but it no longer decides what the box
  // shows.
  const [text, setText] = useState(value)

  // The recent values this box has sent upward, newest last.
  //
  // Distinguishes our own echo from real navigation. A lagging parent
  // echoes back an OLDER value: "Cus" arriving after "Cust" was typed
  // must be ignored, or adopting it swallows the "t". Comparing
  // against only the LAST value sent was not enough for exactly that
  // reason.
  //
  // BOUNDED, because an unbounded record grows one entry per keystroke
  // for as long as someone types without navigating. A dropped echo
  // is safe here in a way a dropped recent one is not: the parent is
  // at most a render or two behind, so anything older than the last
  // few values cannot still be in flight.
  //
  // Not a prefix test instead -- "is the incoming value a prefix of
  // what I have?" looks equivalent and breaks on deletion: backspace
  // from "Cust" to "Cus" while the parent echoes "Cust", and the
  // deleted character comes back.
  const sent = useRef<string[]>([value])

  useEffect(() => {
    if (!sent.current.includes(value)) {
      // A genuinely external value. Start the record over, so a later
      // echo of something typed before this navigation cannot suppress
      // it.
      sent.current = [value]
      setText(value)
    }
  }, [value])

  function update(next: string) {
    setText(next)
    sent.current = rememberSent(sent.current, next)
    onChange(next)
  }

  return (
    <InputGroup
      leftIcon="search"
      placeholder={placeholder}
      value={text}
      onChange={(e) => update(e.currentTarget.value)}
      rightElement={
        text === '' ? undefined : (
          <Button minimal icon="cross" aria-label="Clear filter" onClick={() => update('')} />
        )
      }
    />
  )
}
