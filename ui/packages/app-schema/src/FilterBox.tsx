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

import { Button, InputGroup } from '@blueprintjs/core'

interface FilterBoxProps {
  value: string
  onChange: (value: string) => void
  placeholder: string
}

export default function FilterBox({ value, onChange, placeholder }: FilterBoxProps) {
  return (
    <InputGroup
      leftIcon="search"
      placeholder={placeholder}
      value={value}
      onChange={(e) => onChange(e.currentTarget.value)}
      rightElement={
        value === '' ? undefined : (
          <Button minimal icon="cross" aria-label="Clear filter" onClick={() => onChange('')} />
        )
      }
    />
  )
}
