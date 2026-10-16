import { describe, expect, it } from 'vitest'
import type { VisibleSchema } from '@elysium/shell-api/types'
import { buildCanvasModel, cardinalityLabel, declaredAreas } from './canvasModel'

// The shape /me/visible-schema returns: each side of a link type is a
// link field on its own type, naming the same link_type.
const SCHEMA: VisibleSchema = {
  Customer: {
    display_name: 'Customer',
    group: 'Accounts',
    fields: {
      name: { type: 'data' },
      region: { type: 'data' },
      transactions: {
        type: 'link',
        target: 'Transaction',
        link_type: 'customer_transactions',
        cardinality: 'one_to_many',
      },
    },
  },
  Transaction: {
    fields: {
      amount: { type: 'data' },
      customer: { type: 'link', target: 'Customer', link_type: 'customer_transactions', cardinality: 'many_to_one' },
      approver: { type: 'link', target: 'Customer', link_type: 'transaction_approver', cardinality: 'many_to_one' },
      secret: { type: 'link', target: 'Payroll', link_type: 'transaction_payroll', cardinality: 'many_to_one' },
    },
  },
}

describe('what the canvas draws', () => {
  it('a type per visible type, counting data fields and links apart', () => {
    const { types } = buildCanvasModel(SCHEMA)
    expect(types.map((type) => [type.name, type.fieldCount, type.linkCount])).toEqual([
      ['Customer', 2, 1],
      ['Transaction', 1, 3],
    ])
  })

  it('a two-sided link ONCE; two different link types between one pair TWICE', () => {
    const { links } = buildCanvasModel(SCHEMA)
    expect(links.map((link) => link.name).sort()).toEqual(['customer_transactions', 'transaction_approver'])
  })

  it('no edge to a type that is not drawn', () => {
    const { links } = buildCanvasModel(SCHEMA)
    expect(links.some((link) => link.target === 'Payroll' || link.source === 'Payroll')).toBe(false)
  })

  it('the cardinality on the edge, as an ER diagram writes it', () => {
    expect(cardinalityLabel('one_to_many')).toBe('1:M')
    expect(cardinalityLabel('many_to_one')).toBe('M:1')
    expect(cardinalityLabel('many_to_many')).toBe('M:N')
    expect(cardinalityLabel('whatever')).toBe('whatever')
  })

  it('actions ON the type (DEV_UI 14.3), not as nodes of their own', () => {
    const { types } = buildCanvasModel(SCHEMA, {
      Refund: { affected_object_types: ['Transaction'] },
      Merge: { affected_object_types: ['Customer', 'Transaction'] },
    })
    expect(types.find((type) => type.name === 'Transaction')!.actions).toEqual(['Merge', 'Refund'])
    expect(types.find((type) => type.name === 'Customer')!.actions).toEqual(['Merge'])
  })

  it('an action touching only types the caller cannot see counts nowhere', () => {
    const { types } = buildCanvasModel(SCHEMA, { RunPayroll: { affected_object_types: ['Payroll'] } })
    expect(types.every((type) => type.actions.length === 0)).toBe(true)
  })

  it("the ontology's own groups become ready-made subject areas", () => {
    expect(declaredAreas(buildCanvasModel(SCHEMA).types)).toEqual([
      { name: 'Accounts', types: ['Customer'], declared: true },
    ])
  })
})

describe('the fields a node lists at close zoom (DEV_UI 14.5)', () => {
  it('lists data fields by display name, the key first, links left to the edges', () => {
    const model = buildCanvasModel({
      Order: {
        id_field: 'order_id',
        fields: {
          total: { type: 'data', display_name: 'Total' },
          order_id: { type: 'data', display_name: 'Order ID' },
          customer: { type: 'link', target: 'Order', link_type: 'x', cardinality: 'many_to_one' },
        },
      },
    })

    expect(model.types[0]!.fields).toEqual(['Order ID', 'Total'])
    expect(model.types[0]!.key).toBe('Order ID')
  })

  it('has no key when none is declared', () => {
    const model = buildCanvasModel({ Note: { fields: { body: { type: 'data' } } } })

    expect(model.types[0]!.key).toBeNull()
    expect(model.types[0]!.fields).toEqual(['body'])
  })
})
