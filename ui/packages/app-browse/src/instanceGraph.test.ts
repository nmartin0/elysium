import { describe, expect, it } from 'vitest'

import { EMPTY, MAX_NODES, expand, isFull, linkFieldsOf, nodeKey, seed, targetsFrom } from './instanceGraph'

/**
 * The graph as a model, which is the only part of it anything can
 * assert about: ECharts draws to a canvas jsdom cannot read, and
 * "does expanding twice duplicate a node" is a question no screenshot
 * answers.
 */

const object = (type: string, id: string, title = id) => ({ type, id, title })

describe('identity', () => {
  /**
   * TWO TYPES CAN SHARE AN ID. `Customer/1` and `Transaction/1` are
   * different things and the dev deployment has both. This codebase
   * has been bitten by it before -- LinkTrail has a test called "does
   * not reuse a title across two types that share an id", written
   * after it did.
   */
  it('keys a node on its type AND its id', () => {
    expect(nodeKey('Customer', '1')).not.toBe(nodeKey('Transaction', '1'))
  })

  it('keeps two types sharing an id as two nodes', () => {
    const graph = seed([object('Customer', '1'), object('Transaction', '1')])

    expect(graph.nodes).toHaveLength(2)
  })

  it('does not draw the same object twice', () => {
    const graph = seed([object('Customer', '1'), object('Customer', '1')])

    expect(graph.nodes).toHaveLength(1)
  })
})

describe('seeding from a set', () => {
  it('puts every object on the canvas and no edges', () => {
    const graph = seed([object('Customer', '1'), object('Customer', '2')])

    expect(graph.nodes.map((node) => node.id)).toEqual(['1', '2'])
    expect(graph.edges).toEqual([])
  })

  it('starts nothing expanded', () => {
    expect(seed([object('Customer', '1')]).nodes[0]?.expanded).toBe(false)
  })

  it('is empty for an empty set', () => {
    expect(seed([])).toEqual(EMPTY)
  })
})

describe('the ceiling', () => {
  const many = (count: number) => Array.from({ length: count }, (_, index) => object('Customer', String(index)))

  it('stops at the limit', () => {
    expect(seed(many(MAX_NODES + 10)).nodes).toHaveLength(MAX_NODES)
  })

  /**
   * REFUSED, NOT TRUNCATED. A canvas that quietly dropped half an
   * expansion would show a customer with three transactions who has
   * forty, and nothing on screen could say so. Every other ceiling in
   * this project says the real number -- /matching-ids and the export
   * both refuse and name it.
   */
  it('says how many it would not draw', () => {
    expect(seed(many(MAX_NODES + 10)).refused).toBe(10)
  })

  it('refuses nothing when the set fits', () => {
    expect(seed(many(3)).refused).toBe(0)
  })

  it('knows when it is full', () => {
    expect(isFull(seed(many(MAX_NODES)))).toBe(true)
    expect(isFull(seed(many(MAX_NODES - 1)))).toBe(false)
  })

  it('refuses an EXPANSION past the ceiling too, and counts it', () => {
    const graph = seed(many(MAX_NODES))
    const from = graph.nodes[0]!

    const after = expand(graph, from, [{ type: 'Transaction', id: 't1', title: 't1', field: 'transactions' }])

    expect(after.nodes).toHaveLength(MAX_NODES)
    expect(after.refused).toBe(1)
  })

  it('still marks the source expanded when the ceiling refused its targets', () => {
    // Otherwise the node looks unexplored forever and a person clicks
    // it again and again getting nothing.
    const graph = seed(many(MAX_NODES))
    const from = graph.nodes[0]!

    const after = expand(graph, from, [{ type: 'Transaction', id: 't1', title: 't1', field: 'transactions' }])

    expect(after.nodes.find((node) => node.key === from.key)?.expanded).toBe(true)
  })
})

describe('expanding', () => {
  const start = seed([object('Customer', 'c1')])
  const from = start.nodes[0]!

  it('adds what was found and an edge to each', () => {
    const after = expand(start, from, [
      { type: 'Transaction', id: 't1', title: 't1', field: 'transactions' },
      { type: 'Transaction', id: 't2', title: 't2', field: 'transactions' },
    ])

    expect(after.nodes).toHaveLength(3)
    expect(after.edges).toHaveLength(2)
    expect(after.edges[0]).toEqual({
      source: 'Customer/c1',
      target: 'Transaction/t1',
      field: 'transactions',
    })
  })

  /**
   * "NOTHING IS ATTACHED" AND "I HAVE NOT LOOKED" ARE DIFFERENT FACTS,
   * and a canvas that conflates them is one people stop trusting. The
   * first is an answer.
   */
  it('marks the source expanded even when it found nothing', () => {
    const after = expand(start, from, [])

    expect(after.nodes[0]?.expanded).toBe(true)
    expect(after.edges).toEqual([])
  })

  it('does not duplicate a node that is already there', () => {
    const twice = expand(
      expand(start, from, [{ type: 'Transaction', id: 't1', title: 't1', field: 'transactions' }]),
      from,
      [{ type: 'Transaction', id: 't1', title: 't1', field: 'transactions' }],
    )

    expect(twice.nodes).toHaveLength(2)
  })

  it('does not duplicate an edge either', () => {
    const twice = expand(
      expand(start, from, [{ type: 'Transaction', id: 't1', title: 't1', field: 'transactions' }]),
      from,
      [{ type: 'Transaction', id: 't1', title: 't1', field: 'transactions' }],
    )

    expect(twice.edges).toHaveLength(1)
  })

  it('draws a SECOND edge when two different fields link the same pair', () => {
    // `billing_account` and `primary_account` pointing at one account
    // are two facts, and one line would lose one of them.
    const after = expand(start, from, [
      { type: 'Account', id: 'a1', title: 'a1', field: 'billing_account' },
      { type: 'Account', id: 'a1', title: 'a1', field: 'primary_account' },
    ])

    expect(after.nodes).toHaveLength(2)
    expect(after.edges.map((edge) => edge.field)).toEqual(['billing_account', 'primary_account'])
  })

  /**
   * A SELF-LOOP READS AS A SMUDGE rather than as information, and it
   * happens for real -- a parent account whose parent is itself.
   */
  it('draws no edge from a node to itself', () => {
    const after = expand(start, from, [{ type: 'Customer', id: 'c1', title: 'c1', field: 'referred_by' }])

    expect(after.edges).toEqual([])
    expect(after.nodes).toHaveLength(1)
  })

  it('connects to a node that was already on the canvas', () => {
    const both = seed([object('Customer', 'c1'), object('Transaction', 't1')])
    const customer = both.nodes[0]!

    const after = expand(both, customer, [{ type: 'Transaction', id: 't1', title: 't1', field: 'transactions' }])

    expect(after.nodes).toHaveLength(2)
    expect(after.edges).toHaveLength(1)
  })

  it('leaves the original graph alone', () => {
    expand(start, from, [{ type: 'Transaction', id: 't1', title: 't1', field: 'transactions' }])

    expect(start.nodes).toHaveLength(1)
    expect(start.edges).toHaveLength(0)
  })
})

describe('which fields can be expanded', () => {
  const SCHEMA = {
    Customer: {
      fields: {
        name: { type: 'data' },
        transactions: { type: 'link', target: 'Transaction' },
        account: { type: 'link', target: 'Account' },
      },
    },
  }

  it('names the link fields and what each points at', () => {
    expect(linkFieldsOf(SCHEMA, 'Customer')).toEqual([
      { field: 'transactions', target: 'Transaction' },
      { field: 'account', target: 'Account' },
    ])
  })

  it('offers no data field, which cannot be followed', () => {
    expect(linkFieldsOf(SCHEMA, 'Customer').map((each) => each.field)).not.toContain('name')
  })

  /**
   * READ FROM THE CALLER'S OWN SCHEMA, so a link they may not discover
   * is not one they can expand -- the same filtering every other
   * screen gets, by using the same source rather than a second one.
   */
  it('offers nothing for a type that is not in their schema', () => {
    expect(linkFieldsOf(SCHEMA, 'Secret')).toEqual([])
    expect(linkFieldsOf(null, 'Customer')).toEqual([])
  })

  it('skips a link with no declared target, which points nowhere', () => {
    expect(linkFieldsOf({ T: { fields: { x: { type: 'link' } } } }, 'T')).toEqual([])
  })
})

describe('reading one object s link values', () => {
  const LINKS = [
    { field: 'transactions', target: 'Transaction' },
    { field: 'account', target: 'Account' },
  ]

  /**
   * A LINK FIELD HOLDS AN ID OR A LIST, by cardinality -- `get_field`
   * resolves "one" to an id and "many" to a list. A caller assuming
   * either would silently draw nothing for half the ontology.
   */
  it('reads a cardinality-many field as several targets', () => {
    expect(targetsFrom({ transactions: ['t1', 't2'] }, LINKS)).toHaveLength(2)
  })

  it('reads a cardinality-one field as a single target', () => {
    expect(targetsFrom({ account: 'a1' }, LINKS)).toEqual([
      { type: 'Account', id: 'a1', title: 'a1', field: 'account' },
    ])
  })

  it('reads a numeric id as a string, since a key is one', () => {
    expect(targetsFrom({ transactions: [1, 2] }, LINKS).map((each) => each.id)).toEqual(['1', '2'])
  })

  /**
   * A FIELD THE CALLER MAY NOT READ ARRIVES AS NULL rather than being
   * omitted -- `get_object`'s own contract. Drawing a node for it
   * would be drawing a link they are not allowed to know about.
   */
  it('follows nothing for a withheld field', () => {
    expect(targetsFrom({ transactions: null }, LINKS)).toEqual([])
  })

  it('follows nothing for an absent field', () => {
    expect(targetsFrom({}, LINKS)).toEqual([])
    expect(targetsFrom(null, LINKS)).toEqual([])
  })

  it('skips an empty id inside a list rather than drawing a blank node', () => {
    expect(targetsFrom({ transactions: ['t1', '', null] }, LINKS)).toHaveLength(1)
  })

  it('follows only the fields it was given', () => {
    expect(targetsFrom({ secret: 'x' }, LINKS)).toEqual([])
  })
})
