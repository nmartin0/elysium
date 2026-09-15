import { describe, it, expect } from 'vitest'
import { formatFieldName, formatTimestamp, formatValue, getDisplayTitle, pluralise } from './format'

describe('formatFieldName', () => {
  it('capitalizes a single-word field name', () => {
    expect(formatFieldName('balance')).toBe('Balance')
  })

  it('replaces underscores with spaces and capitalizes only the first word', () => {
    expect(formatFieldName('reopen_reason')).toBe('Reopen reason')
  })

  it('handles a name with multiple underscores', () => {
    expect(formatFieldName('new_from_balance')).toBe('New from balance')
  })

  it('does not produce Title Case for multi-word names', () => {
    // Explicitly NOT "Reopen Reason" -- the module's own docstring is
    // deliberate about this; a regression here would be a real,
    // visible style change, not just a wording nitpick.
    expect(formatFieldName('reopen_reason')).not.toBe('Reopen Reason')
  })
})

describe('formatValue', () => {
  it('renders null as —', () => {
    expect(formatValue(null)).toBe('—')
  })

  it('renders undefined as —', () => {
    expect(formatValue(undefined)).toBe('—')
  })

  it('stringifies a number', () => {
    expect(formatValue(42)).toBe('42')
  })

  it('stringifies zero (not treated the same as null/undefined)', () => {
    expect(formatValue(0)).toBe('0')
  })

  it('leaves a string value as-is', () => {
    expect(formatValue('Ada Okafor')).toBe('Ada Okafor')
  })

  it('stringifies false (not treated the same as null/undefined)', () => {
    expect(formatValue(false)).toBe('false')
  })
})

describe('getDisplayTitle', () => {
  it('returns the title field value when the schema declares one and it is present', () => {
    const typeSchema = { title_field: 'name' }
    const fields = { name: 'Ada Okafor', region: 'us-west' }
    expect(getDisplayTitle(typeSchema, fields, 'cust_001')).toBe('Ada Okafor')
  })

  it('falls back to the raw id when the type has no title_field declared', () => {
    const typeSchema = { title_field: null }
    const fields = { name: 'Ada Okafor' }
    expect(getDisplayTitle(typeSchema, fields, 'cust_001')).toBe('cust_001')
  })

  it('falls back to the raw id when the schema for this type has not loaded yet', () => {
    expect(getDisplayTitle(undefined, { name: 'Ada Okafor' }, 'cust_001')).toBe('cust_001')
    expect(getDisplayTitle(null, { name: 'Ada Okafor' }, 'cust_001')).toBe('cust_001')
  })

  it('falls back to the raw id when the title field is withheld (RBAC-gated null from the backend)', () => {
    // Mirrors the real, server-side case directly: visible_schema()
    // itself resolves this distinction -- title_field comes back
    // null, never a field name the caller can't actually read. This
    // function must never assume the field is present just because
    // title_field names it.
    const typeSchema = { title_field: 'name' }
    const fields = { region: 'us-west' } // no "name" key at all
    expect(getDisplayTitle(typeSchema, fields, 'cust_001')).toBe('cust_001')
  })

  it('falls back to the raw id when the declared title field is present but null', () => {
    const typeSchema = { title_field: 'name' }
    const fields = { name: null }
    expect(getDisplayTitle(typeSchema, fields, 'cust_001')).toBe('cust_001')
  })
})

describe('formatTimestamp', () => {
  const now = new Date('2026-09-09T12:00:00Z')

  it('reads relatively within the day', () => {
    // "3 hours ago" is what you want for something that happened
    // during your shift.
    expect(formatTimestamp('2026-09-09T09:00:00Z', now)).toBe('3 hours ago')
    expect(formatTimestamp('2026-09-09T11:30:00Z', now)).toBe('30 minutes ago')
    expect(formatTimestamp('2026-09-09T11:59:30Z', now)).toBe('just now')
  })

  it('switches to an absolute date past 24 hours', () => {
    /**
     * The platform's own rule: relative "up to 24 hours ago", then a
     * short form with the day of the week. "47 days ago" is a number
     * nobody can place.
     */
    const older = formatTimestamp('2026-07-22T13:00:00Z', now)

    expect(older).not.toMatch(/ago/)
    expect(older).toMatch(/2026/)
  })

  it('names the timezone on the absolute form', () => {
    /**
     * "Wed, 22 Jul 2026, 13:00" does not say whose clock it is, and it
     * is the READER'S -- toLocaleString with no timezone uses the
     * browser's. Two colleagues in different offices reading one note
     * would see different numbers with no way to tell they mean the
     * same moment.
     *
     * Compares against the SAME date formatted without a zone, rather
     * than matching a pattern. A first version used
     * /[A-Z]{2,5}/ -- which matches "Wed" and "Jul", so it passed with
     * the zone removed entirely. Proven by a control, which is the
     * only reason it was caught.
     *
     * Which zone appears depends on where the test runs, so the
     * assertion is that the output is LONGER than the zone-less form
     * and starts with it.
     */
    const older = formatTimestamp('2026-07-22T13:00:00Z', now)
    const withoutZone = new Date('2026-07-22T13:00:00Z').toLocaleString(undefined, {
      weekday: 'short',
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })

    expect(older.startsWith(withoutZone)).toBe(true)
    expect(older.length).toBeGreaterThan(withoutZone.length)
  })

  it('puts no timezone on the relative form', () => {
    // "3 hours ago" means the same thing everywhere; a zone on it
    // would be noise.
    expect(formatTimestamp('2026-09-09T09:00:00Z', now)).toBe('3 hours ago')
  })

  it('singularises', () => {
    expect(formatTimestamp('2026-09-09T11:00:00Z', now)).toBe('1 hour ago')
    expect(formatTimestamp('2026-09-09T11:59:00Z', now)).toBe('1 minute ago')
  })

  it('shows a FUTURE timestamp absolutely', () => {
    /**
     * Clock skew between a server and a browser makes this real. "in
     * 3 seconds" reads as a bug rather than as skew, so a future time
     * falls through to the absolute form.
     */
    const ahead = formatTimestamp('2026-09-09T12:00:30Z', now)

    expect(ahead).not.toMatch(/ago|just now/)
  })

  it('passes an unparseable value through unchanged', () => {
    // Better to show something odd than to render "Invalid Date",
    // which tells the user nothing and hides what arrived.
    expect(formatTimestamp('not a date', now)).toBe('not a date')
  })
})

describe('a blank cell is never produced', () => {
  /**
   * UI_ROADMAP.md item 8 asks for null, zero and unknown to be
   * VISUALLY DISTINCT, on the grounds that "a blank cell in Elysium
   * could mean no value, or could mean MAC hid it".
   *
   * THE MAC CASE TURNED OUT NOT TO HAPPEN, verified against the
   * mediator rather than assumed: a field the caller may not read is
   * OMITTED from the response entirely rather than returned as null,
   * so it never reaches a formatter. The other ambiguities are real.
   */
  it('renders an empty string as something, not nothing', () => {
    // "" is a real value a source can hold, and String('') paints
    // exactly as wide as a cell that was never filled.
    expect(formatValue('')).toBe('(empty)')
  })

  it('distinguishes whitespace from empty', () => {
    // A field holding "   " is a data-quality fact worth seeing. Both
    // render blank otherwise, and they are not the same problem.
    expect(formatValue('   ')).toBe('(whitespace)')
  })

  it('renders an empty array as "(none)", not as "not set"', () => {
    // A link that resolved to nothing -- a customer with no
    // transactions -- is a DIFFERENT fact from a field never set: it
    // says the link was followed and found nothing.
    expect(formatValue([])).toBe('(none)')
  })

  it('leaves zero alone', () => {
    // THE CONTROL, and the classic falsy bug. A guard treating 0 as
    // empty would hide the answer in any count or balance field.
    expect(formatValue(0)).toBe('0')
  })

  it('leaves false alone', () => {
    expect(formatValue(false)).toBe('false')
  })

  it('uses one convention for absence across the app', () => {
    // Four places already rendered an absent value as a dash --
    // AdminPanel's mac_value, DeploymentConfig's lists, Silos' object
    // types -- so this function having its own was a third convention.
    expect(formatValue(null)).toBe('—')
    expect(formatValue(undefined)).toBe('—')
  })
})

describe('decimal places, where the ontology declared them', () => {
  /**
   * The UI cannot know how precise a number is worth showing. The same
   * `number` type carries a coordinate, a count and a ratio, and two
   * places is wrong for at least two of them -- so this only rounds
   * when an ontology author said so.
   *
   * DISPLAY ONLY. The stored value, the value an action writes and the
   * value a filter compares against are all untouched. Rounding for
   * display and then filtering on the rounded figure would be a
   * different and much worse feature.
   */
  it('rounds to the declared places', () => {
    expect(formatValue(49.9876, 2)).toBe('49.99')
  })

  it('pads to them as well', () => {
    // "49.9" under a column of "49.99" is harder to compare than
    // "49.90", which is the whole point of a declared precision.
    expect(formatValue(49.9, 2)).toBe('49.90')
  })

  it('zero places is a real answer, not an absent one', () => {
    expect(formatValue(1234.56, 0)).toBe('1235')
  })

  it('leaves the number alone when nothing was declared', () => {
    // THE CONTROL, and the overwhelmingly common case. A default would
    // silently reformat every number in every deployment.
    expect(formatValue(49.9876)).toBe('49.9876')
    expect(formatValue(49.9876, null)).toBe('49.9876')
  })

  it('does not touch a string that looks like a number', () => {
    // toFixed on a string throws. A value arriving as text is text,
    // whatever the ontology says the column holds.
    expect(formatValue('49.9876', 2)).toBe('49.9876')
  })

  it('does not turn NaN into the word NaN', () => {
    // NaN and Infinity are numbers, and toFixed renders them as words
    // that read like data rather than like the absence of it.
    expect(formatValue(Number.NaN, 2)).toBe('NaN')
    expect(formatValue(Number.POSITIVE_INFINITY, 2)).toBe('Infinity')
  })

  it('still withholds null rather than rounding it', () => {
    expect(formatValue(null, 2)).toBe('—')
  })
})

describe('counts agree with their nouns', () => {
  /**
   * "All 1 silos are reachable" is the kind of thing that makes a
   * careful product look careless, and it appears wherever a count is
   * interpolated in front of a hardcoded plural. Three places had it.
   */
  it('uses the singular for one', () => {
    expect(pluralise(1, 'silo', 'silos')).toBe('1 silo')
  })

  it('uses the plural for more', () => {
    expect(pluralise(3, 'silo', 'silos')).toBe('3 silos')
  })

  it('uses the plural for none', () => {
    // "0 silos", not "0 silo" -- English treats zero as plural, which
    // is the case a naive `count > 1` check gets wrong.
    expect(pluralise(0, 'silo', 'silos')).toBe('0 silos')
  })

  it('takes the plural rather than deriving it', () => {
    // English plurals are irregular, and a rule appending "s" would be
    // wrong often enough to be worse than the bug it replaced.
    expect(pluralise(2, 'entity', 'entities')).toBe('2 entities')
    expect(pluralise(2, 'index', 'indices')).toBe('2 indices')
  })
})
