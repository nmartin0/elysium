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

  // EVERY value this box has sent upward, not just the latest.
  //
  // Comparing against only the latest was not enough: a lagging parent
  // echoes back an OLDER value, so "Cus" arriving after "Cust" was
  // typed did not match the latest and looked like external
  // navigation -- which adopted it and swallowed the "t". Typing
  // "Cust" produced "Cus".
  //
  // A value this box has ever sent is its own echo and is ignored.
  // Anything else is real navigation -- Back, a cross-reference, a tab
  // switch -- and is adopted.
  const sent = useRef(new Set([value]))

  useEffect(() => {
    if (!sent.current.has(value)) {
      // A genuinely external value. Start the record over, so a later
      // echo of something typed before this navigation cannot suppress
      // it.
      sent.current = new Set([value])
      setText(value)
    }
  }, [value])

  function update(next: string) {
    setText(next)
    sent.current.add(next)
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
