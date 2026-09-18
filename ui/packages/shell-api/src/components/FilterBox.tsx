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

  /**
   * The value we last sent that has not been echoed back yet, or null
   * when nothing is outstanding.
   *
   * ONE PENDING VALUE, not a history of everything sent. The previous
   * design remembered the last sixteen and ignored any incoming value
   * among them, which worked for typing and broke for navigation:
   * pressing Back sets the value to "" -- which this box had also
   * sent, at mount -- so it was taken for an echo and the box kept
   * showing the old search against an empty URL.
   *
   * The distinction that actually matters is not "have I sent this
   * before" but "am I still waiting for my own last send". While
   * waiting, anything that is not that value is a LAGGING echo of an
   * older keystroke and must be ignored, or fast typing loses
   * characters. Once it arrives, nothing is outstanding and any
   * incoming value is the parent's -- a navigation, a reset, a tab
   * change -- and is adopted.
   */
  const pending = useRef<string | null>(null)

  useEffect(() => {
    if (pending.current === null) {
      // Nothing outstanding: this came from the parent.
      setText(value)
      return
    }
    if (value === pending.current) {
      // Our own send, echoed. Caught up.
      pending.current = null
      return
    }
    /**
     * Otherwise: a lagging echo of an older keystroke. Ignored.
     *
     * A probe settled this. An echo does CHANGE the value -- typing
     * "C", "Cu", "Cus" makes the parent render "", "C", "Cu" -- so
     * "did the value change" cannot tell an echo from a navigation.
     * Only "is it the value I am waiting for" can.
     *
     * KNOWN LIMIT, recorded rather than guarded against: a parent that
     * never echoes a send leaves this waiting forever and ignoring
     * later navigations. Every real parent echoes through the URL, and
     * an escape hatch for the hypothetical case could not be
     * distinguished from a lagging echo -- it broke fast typing when
     * tried.
     */
    // Otherwise: a lagging echo of an older keystroke. Ignore it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value])

  function update(next: string) {
    setText(next)
    pending.current = next
    onChange(next)
  }

  return (
    <InputGroup
      leftIcon="search"
      placeholder={placeholder}
      value={text}
      onChange={(e) => update(e.currentTarget.value)}
      rightElement={
        text === '' ? undefined : <Button minimal icon="cross" aria-label="Clear filter" onClick={() => update('')} />
      }
    />
  )
}
