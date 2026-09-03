import { describe, it, expect } from 'vitest'
import { formatFieldName, formatValue, getDisplayTitle } from './format'

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
  it('renders null as (not set)', () => {
    expect(formatValue(null)).toBe('(not set)')
  })

  it('renders undefined as (not set)', () => {
    expect(formatValue(undefined)).toBe('(not set)')
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
