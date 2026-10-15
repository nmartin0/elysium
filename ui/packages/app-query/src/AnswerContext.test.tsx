import { describe, expect, it } from 'vitest'
import { doorHref } from './AnswerContext'

describe('where an answer leads', () => {
  it("an object's page", () => {
    expect(doorHref({ kind: 'object', object_type: 'Support ticket', object_id: 't/1', label: 'x' })).toBe(
      '/objects/Support%20ticket/t%2F1',
    )
  })

  it('a set, in the URL form Browse already reads', () => {
    const href = doorHref({
      kind: 'set',
      object_type: 'Transaction',
      label: 'The Transactions counted',
      filters: [{ field: 'customer_id', values: ['cust_001'], mode: 'keep' }],
    })
    const url = new URL(href, 'http://x')
    expect(url.pathname).toBe('/browse')
    expect(url.searchParams.get('type')).toBe('Transaction')
    expect(JSON.parse(url.searchParams.get('filters')!)).toEqual([
      { field: 'customer_id', values: ['cust_001'], mode: 'keep' },
    ])
  })
})
