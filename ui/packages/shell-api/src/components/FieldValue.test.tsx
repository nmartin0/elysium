import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import FieldValue from './FieldValue'

describe('FieldValue: three things that are not the same (DEV_UI 9.7, E4)', () => {
  it('says "Not permitted" for a field the reader may not read, though the value is null', () => {
    // NULL ON THE WIRE. The server nulls a discover-only field, so a
    // component checking null first would render "not set" -- which is
    // what Browse did.
    render(<FieldValue value={null} readable={false} />)
    expect(screen.getByText('Not permitted')).toBeInTheDocument()
    expect(screen.queryByText('not set')).toBeNull()
  })

  it('withholds even a value that arrived, when the schema says unreadable', () => {
    render(<FieldValue value="ada@example.com" readable={false} />)
    expect(screen.getByText('Not permitted')).toBeInTheDocument()
    expect(screen.queryByText('ada@example.com')).toBeNull()
  })

  it('shows a real null as a dash a screen reader hears as "not set"', () => {
    const { container } = render(<FieldValue value={null} />)
    expect(screen.getByText('not set')).toHaveClass('visually-hidden')
    expect(container.querySelector('[aria-hidden="true"]')?.textContent).toBe('—')
    expect(screen.queryByText('Not permitted')).toBeNull()
  })

  it('treats an absent `readable` as readable', () => {
    // THE CONTROL. Most schemas never say `readable`; reading undefined
    // as false would withhold the whole product.
    render(<FieldValue value="Ada Okafor" />)
    expect(screen.getByText('Ada Okafor')).toBeInTheDocument()
  })

  it('formats by type', () => {
    render(<FieldValue value="2026-05-01" dataType="date" />)
    expect(screen.queryByText('2026-05-01')).toBeNull()
  })
})
