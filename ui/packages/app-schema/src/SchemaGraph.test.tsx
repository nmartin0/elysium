import { describe, it, expect } from 'vitest'

import type { VisibleSchema } from '@elysium/shell-api/types'
import { buildGraph, cardinalityLabel } from './SchemaGraph'

/**
 * The model, tested directly. The chart draws to a canvas jsdom cannot
 * read, so testing through the component would assert that jsdom
 * returned an empty canvas -- the same reason the aggregate chart
 * options are plain functions.
 */

const TWO_TYPES: VisibleSchema = {
  Customer: {
    fields: {
      name: { type: 'data' },
      transactions: {
        type: 'link', target: 'Transaction',
        link_type: 'CustomerTransactions', cardinality: 'one_to_many',
      },
    },
  },
  Transaction: {
    fields: {
      amount: { type: 'data' },
      customer_id: {
        type: 'link', target: 'Customer',
        link_type: 'CustomerTransactions', cardinality: 'many_to_one',
      },
    },
  },
}

describe('buildGraph', () => {
  it('makes a node per object type', () => {
    expect(buildGraph(TWO_TYPES).nodes.map((n) => n.name).sort())
      .toEqual(['Customer', 'Transaction'])
  })

  it('draws a two-sided link ONCE', () => {
    /**
     * Both sides of a link type describe one relationship. Drawing
     * each side gives two edges between the same nodes, which reads as
     * two relationships -- and the graph exists to show the shape
     * accurately rather than densely.
     */
    const links = buildGraph(TWO_TYPES).links

    expect(links).toHaveLength(1)
    expect(links[0]?.name).toBe('CustomerTransactions')
  })

  it('drops an edge to a type the caller cannot see', () => {
    /**
     * Not a security decision -- the schema handed in is already
     * scoped, so an invisible type is simply absent. It is that an
     * edge to a node that is not there is a drawing bug: ECharts
     * silently invents the missing endpoint, so the caller would see a
     * node for a type they were denied.
     */
    const partial: VisibleSchema = {
      Customer: {
        fields: {
          secret: {
            type: 'link', target: 'Ledger',
            link_type: 'CustomerLedger', cardinality: 'one_to_one',
          },
        },
      },
    }

    expect(buildGraph(partial).links).toEqual([])
    expect(buildGraph(partial).nodes.map((n) => n.name)).toEqual(['Customer'])
  })

  it('sizes a node by how many fields the type has', () => {
    // A type with more fields is a bigger thing in the ontology, and
    // that is worth seeing without reading a label.
    const nodes = buildGraph(TWO_TYPES).nodes

    expect(nodes.find((n) => n.name === 'Customer')?.value).toBe(2)
  })

  it('handles an ontology with no links at all', () => {
    // Legal, and the first thing a new deployment looks like.
    const isolated: VisibleSchema = { Customer: { fields: { name: { type: 'data' } } } }

    const model = buildGraph(isolated)

    expect(model.nodes).toHaveLength(1)
    expect(model.links).toEqual([])
  })

  it('keeps two DIFFERENT link types between the same pair', () => {
    // De-duplication is per link type, not per pair of nodes: two
    // relationships between the same types are two edges.
    const twoLinks: VisibleSchema = {
      Customer: {
        fields: {
          a: { type: 'link', target: 'Account', link_type: 'Owns', cardinality: 'one_to_many' },
          b: { type: 'link', target: 'Account', link_type: 'Bills', cardinality: 'one_to_one' },
        },
      },
      Account: { fields: { balance: { type: 'data' } } },
    }

    expect(buildGraph(twoLinks).links).toHaveLength(2)
  })
})

describe('the graph is the same picture every time', () => {
  it('gives every node a deterministic starting position', () => {
    /**
     * ECharts seeds a force layout RANDOMLY, so the same ontology drew
     * a different picture on every visit -- impossible to build any
     * familiarity with, and it reads as the application being unsure
     * of itself.
     */
    const first = buildGraph(TWO_TYPES)
    const second = buildGraph(TWO_TYPES)

    expect(first.nodes.map((n) => [n.name, n.x, n.y]))
      .toEqual(second.nodes.map((n) => [n.name, n.x, n.y]))
  })

  it('does not depend on the order the schema arrived in', () => {
    // Object key order is not guaranteed across sources, so sorting is
    // what makes "same ontology" mean "same picture" rather than "same
    // object literal".
    const reversed: VisibleSchema = {
      Transaction: TWO_TYPES.Transaction!,
      Customer: TWO_TYPES.Customer!,
    }

    expect(buildGraph(reversed).nodes.map((n) => [n.name, n.x]))
      .toEqual(buildGraph(TWO_TYPES).nodes.map((n) => [n.name, n.x]))
  })
})

describe('cardinality on the edge', () => {
  it('writes a relationship the way an ER diagram does', () => {
    // Short form, because an edge label competes with the node labels
    // around it and this is the notation people already read.
    expect(cardinalityLabel('one_to_many')).toBe('1:M')
    expect(cardinalityLabel('many_to_one')).toBe('M:1')
    expect(cardinalityLabel('one_to_one')).toBe('1:1')
  })

  it('writes many-to-many as M:N, not M:M', () => {
    // Two "many" sides are not the same many, and one letter twice
    // implies they are.
    expect(cardinalityLabel('many_to_many')).toBe('M:N')
  })

  it('passes an unrecognised cardinality through unchanged', () => {
    // Better to show something odd than to guess and show something
    // wrong -- a schema may declare a shape this does not know.
    expect(cardinalityLabel('sometimes')).toBe('sometimes')
  })

  it('puts the cardinality on the edge', () => {
    expect(buildGraph(TWO_TYPES).links[0]?.label).toBe('1:M')
  })
})

describe('actions in the graph', () => {
  const ACTIONS = [
    { api_name: 'UpdateCustomerName', affected_object_types: ['Customer'] },
    { api_name: 'ArchiveLedger', affected_object_types: ['Ledger'] },
  ]

  it('draws an action as a node joined to what it affects', () => {
    const model = buildGraph(TWO_TYPES, ACTIONS)

    const action = model.nodes.find((n) => n.name === 'UpdateCustomerName')
    expect(action?.kind).toBe('action')
    expect(model.links.some((l) =>
      l.source === 'UpdateCustomerName' && l.target === 'Customer')).toBe(true)
  })

  it('omits an action that touches nothing the caller can see', () => {
    /**
     * ArchiveLedger affects only Ledger, which is not in this schema.
     * Drawing it would put a node on screen connected to nothing --
     * which says "there is something here you may not see", the
     * disclosure uniform denial exists to prevent.
     */
    const model = buildGraph(TWO_TYPES, ACTIONS)

    expect(model.nodes.some((n) => n.name === 'ArchiveLedger')).toBe(false)
  })

  it('draws no actions when none are given', () => {
    // The graph must work before action types have loaded.
    expect(buildGraph(TWO_TYPES).nodes.every((n) => n.kind === 'object')).toBe(true)
  })
})
