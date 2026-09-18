import { describe, expect, it } from 'vitest'

import { formatTemporal, formatValue } from './format'

/**
 * A date, a wall-clock reading, and an instant render differently
 * because they MEAN differently.
 *
 * THE BUG THIS PREVENTS is specific and easy to write by accident:
 * passing '2026-03-12' through `new Date()` makes it MIDNIGHT UTC, and
 * rendering that in local time moves it to the 11th for every reader
 * west of Greenwich. Somebody's birthday shifts a day.
 */
describe('a date is never converted', () => {
  it('renders the day it says, whatever the reader s zone', () => {
    // The parts are read from the text, not resolved through an
    // instant, so no zone can move them.
    expect(formatTemporal('2026-03-12', 'date')).toMatch(/12/)
    expect(formatTemporal('2026-03-12', 'date')).toMatch(/2026/)
  })

  it('does not slip to the previous day', () => {
    // THE CONTROL ON THE BUG ITSELF. A naive `new Date('2026-01-01')`
    // is midnight UTC, which is 31 December for anyone behind it.
    expect(formatTemporal('2026-01-01', 'date')).not.toMatch(/2025/)
    expect(formatTemporal('2026-01-01', 'date')).not.toMatch(/31/)
  })

  it('leaves a value it cannot read alone', () => {
    expect(formatTemporal('not-a-date', 'date')).toBe('not-a-date')
  })
})

describe('an instant is converted, because it names a moment', () => {
  it('reads an offset and renders in the reader s zone', () => {
    // The server sends UTC with the offset on the wire; the browser
    // knows the reader's zone without being told.
    const rendered = formatTemporal('2026-03-12T14:30:00+00:00', 'timestamptz')

    expect(rendered).not.toBe('2026-03-12T14:30:00+00:00')
    expect(rendered).toMatch(/2026/)
  })

  it('leaves an unparseable value alone', () => {
    expect(formatTemporal('nonsense', 'timestamptz')).toBe('nonsense')
  })
})

describe('a wall-clock reading is shown as given', () => {
  it('converts nothing, because there is nothing to convert from', () => {
    // Inventing a zone here would be the guess the backend refuses to
    // make.
    expect(formatTemporal('2026-03-12T14:30:00', 'timestamp')).toBe('2026-03-12 14:30:00')
  })
})

describe('formatValue routes by declared type', () => {
  it('sends a date to the temporal formatter', () => {
    // Without the type, '2026-03-12' is just a string to JavaScript --
    // and so is 'ACME-2026-03-12'. Only the ontology knows.
    expect(formatValue('2026-03-12', null, 'date')).not.toBe('2026-03-12')
  })

  it('leaves a string alone', () => {
    expect(formatValue('2026-03-12', null, 'string')).toBe('2026-03-12')
  })

  it('leaves an undeclared field alone', () => {
    // Absent means the author declared none; show it as it arrived.
    expect(formatValue('2026-03-12')).toBe('2026-03-12')
  })

  it('a missing date is missing, not midnight', () => {
    // Nulls are handled before the temporal branch, deliberately.
    expect(formatValue(null, null, 'date')).toBe('—')
  })

  it('still applies decimal places to a number', () => {
    // THE CONTROL that the new branch did not capture the old ones.
    expect(formatValue(10.5, 2)).toBe('10.50')
  })
})
