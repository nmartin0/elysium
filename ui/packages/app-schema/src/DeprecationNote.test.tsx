import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'

import DeprecationNote from './DeprecationNote'

const WHY = { reason: 'Replaced by a single address field.', replaced_by: 'address', remove_after: '2027-03-31' }

describe('the sentence beside a deprecated name', () => {
  it('gives the reason, the replacement and the planned date', () => {
    const { container } = render(<DeprecationNote status="deprecated" deprecation={WHY} />)

    expect(container).toHaveTextContent(
      'Deprecated: Replaced by a single address field. Use address instead. Removal planned after 2027-03-31.',
    )
  })

  it('leaves out what was not said', () => {
    const { container } = render(
      <DeprecationNote status="deprecated" deprecation={{ reason: 'Old.', replaced_by: null, remove_after: null }} />,
    )

    expect(container).toHaveTextContent(/^Deprecated: Old\.$/)
  })

  it('says which type a link took its status from', () => {
    const { container } = render(<DeprecationNote status="deprecated" deprecation={null} inheritedFrom="Customer" />)

    expect(container).toHaveTextContent('Deprecated because Customer is.')
  })

  it('says nothing for an active name, or for a deprecated one with no reason', () => {
    expect(render(<DeprecationNote status="active" deprecation={WHY} />).container).toBeEmptyDOMElement()
    expect(render(<DeprecationNote status="deprecated" deprecation={null} />).container).toBeEmptyDOMElement()
  })
})
