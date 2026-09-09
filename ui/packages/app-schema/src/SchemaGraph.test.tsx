import { describe, it, expect } from 'vitest'

import type { VisibleSchema } from '@elysium/shell-api/types'
import { buildGraph } from './SchemaGraph'

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
