/**
 * Health indexed by OBJECT TYPE, which is the question the Silos
 * screen is opened with and could not answer.
 *
 * THE CASE THAT MAKES THIS WORTH A MODULE is the deployment's own:
 * `risk_sql` backs exactly one thing, `Customer.risk_score`, and
 * backs no object type primarily. When it stops answering, Customer
 * keeps refreshing and one field does not. The payload used to say
 * only that risk_sql was unreachable and that it "backs Customer" --
 * from which the two outages are indistinguishable.
 *
 * AND THE WORDING, WHICH A FIRST VERSION GOT WRONG. `read_from_mirror`
 * has been always-true since GOLD-9, so every read is served from
 * published gold and a dead SOURCE breaks no query at all. It stops
 * the values being replaced. "Cannot be read" would have been a false
 * alarm on a deployment answering every request correctly, so the
 * verb under test here is REFRESH.
 */

import { describe, it, expect } from 'vitest'

import { frozenTypes, unfixableTypes, type SiloForHealth } from './typeHealth'

/** The dev deployment's own shape, which is why it is the fixture:
 *  primary_sql is primary for Customer and Transaction; risk_sql is
 *  primary for nothing and backs one field of Customer. */
function silos(overrides: Partial<Record<string, Partial<SiloForHealth>>> = {}): SiloForHealth[] {
  const base: Record<string, SiloForHealth> = {
    primary_sql: {
      name: 'primary_sql',
      object_types: ['Customer', 'Transaction'],
      primary_for: ['Customer', 'Transaction'],
      fields: [
        { object_type: 'Customer', field: 'customer_id', is_identifier: true },
        { object_type: 'Customer', field: 'name', is_identifier: false },
        { object_type: 'Customer', field: 'region', is_identifier: false },
        { object_type: 'Transaction', field: 'amount', is_identifier: false },
      ],
      reachable: true,
    },
    risk_sql: {
      name: 'risk_sql',
      object_types: ['Customer'],
      primary_for: [],
      fields: [
        { object_type: 'Customer', field: 'customer_id', is_identifier: true },
        { object_type: 'Customer', field: 'risk_score', is_identifier: false },
      ],
      reachable: true,
    },
  }
  for (const [name, patch] of Object.entries(overrides)) {
    base[name] = { ...base[name]!, ...patch }
  }
  return Object.values(base)
}

describe('nothing is down', () => {
  it('names no type at all', () => {
    // THE CONTROL FOR EVERY TEST BELOW. A function returning every
    // backed type would pass all of them and fail this one.
    expect(frozenTypes(silos())).toEqual([])
  })
})

describe('an additional-storage silo stops answering', () => {
  it('names the field that stopped, not the type', () => {
    // THE WHOLE REASON `primary_for` WAS ADDED TO THE PAYLOAD.
    // risk_sql backs Customer and is primary for nothing, so Customer
    // goes on refreshing and risk_score does not.
    const frozen = frozenTypes(silos({ risk_sql: { reachable: false } }))

    expect(frozen).toEqual([{ objectType: 'Customer', silos: ['risk_sql'], whole: false, fields: ['risk_score'] }])
  })

  it('does not count the identifier as a field that stopped', () => {
    // The id is emitted once per storage holding the type, additional
    // storage included -- so counting it would make every partial
    // outage look like it took the join key with it.
    const [frozen] = frozenTypes(silos({ risk_sql: { reachable: false } }))

    expect(frozen?.fields).not.toContain('customer_id')
  })

  it('leaves a type the dead silo does not back alone', () => {
    const frozen = frozenTypes(silos({ risk_sql: { reachable: false } }))

    expect(frozen.map((entry) => entry.objectType)).not.toContain('Transaction')
  })
})

describe('a primary silo stops answering', () => {
  it('says the whole type stopped', () => {
    const frozen = frozenTypes(silos({ primary_sql: { reachable: false } }))

    expect(frozen.map((entry) => entry.objectType)).toEqual(['Customer', 'Transaction'])
    expect(frozen.every((entry) => entry.whole)).toBe(true)
  })

  it('carries no field list, because naming every field says less', () => {
    const frozen = frozenTypes(silos({ primary_sql: { reachable: false } }))

    expect(frozen.every((entry) => entry.fields.length === 0)).toBe(true)
  })

  it('stays whole even when a second silo only takes one field', () => {
    // BOTH DOWN. Customer is whole-frozen by primary_sql; the partial
    // finding from risk_sql must not downgrade it, and both silos are
    // still named because the operator has two things to fix.
    const frozen = frozenTypes(silos({ primary_sql: { reachable: false }, risk_sql: { reachable: false } }))
    const customer = frozen.find((entry) => entry.objectType === 'Customer')

    expect(customer?.whole).toBe(true)
    expect(customer?.silos).toEqual(['primary_sql', 'risk_sql'])
    expect(customer?.fields).toEqual([])
  })
})

describe('the order and the shape', () => {
  it('puts a whole-type outage above a partial one', () => {
    // A reader scanning the list should meet the worse thing first.
    const frozen = frozenTypes([
      {
        name: 'extra',
        object_types: ['Customer'],
        primary_for: [],
        fields: [{ object_type: 'Customer', field: 'risk_score', is_identifier: false }],
        reachable: false,
      },
      {
        name: 'main',
        object_types: ['Transaction'],
        primary_for: ['Transaction'],
        fields: [{ object_type: 'Transaction', field: 'amount', is_identifier: false }],
        reachable: false,
      },
    ])

    expect(frozen.map((entry) => entry.objectType)).toEqual(['Transaction', 'Customer'])
  })

  it('reports one type once however many of its silos are down', () => {
    const frozen = frozenTypes(silos({ primary_sql: { reachable: false }, risk_sql: { reachable: false } }))

    expect(frozen.filter((entry) => entry.objectType === 'Customer')).toHaveLength(1)
  })

  it('treats a missing primary_for as NOT primary rather than guessing', () => {
    // An older server does not send the field. Inferring primacy from
    // which silo holds the most fields would be a guess rendered as a
    // fact -- and the cost of guessing wrong is telling somebody
    // their whole type is frozen when one field is. Under-claiming is
    // recoverable; over-claiming costs trust.
    const frozen = frozenTypes([
      {
        name: 'primary_sql',
        object_types: ['Customer'],
        fields: [
          { object_type: 'Customer', field: 'customer_id', is_identifier: true },
          { object_type: 'Customer', field: 'name', is_identifier: false },
        ],
        reachable: false,
      },
    ])

    expect(frozen[0]?.whole).toBe(false)
    expect(frozen[0]?.fields).toEqual(['name'])
  })
})

describe('never published, and no way to publish it', () => {
  it('names a type whose source is down AND which has never been published', () => {
    // BOTH FACTS WERE ALREADY ON THE SCREEN, in different sections.
    // Apart, the first one's advice is "run a sync"; together, that is
    // advice nobody can take.
    const frozen = frozenTypes(silos({ primary_sql: { reachable: false } }))

    expect(unfixableTypes(frozen, ['Transaction'])).toEqual(['Transaction'])
  })

  it('says nothing about a never-published type whose source is fine', () => {
    // THE CONTROL. This one IS a sync away from working, and calling
    // it unfixable would send somebody looking for an outage that is
    // not there.
    expect(unfixableTypes(frozenTypes(silos()), ['Transaction'])).toEqual([])
  })

  it('does not call a PARTLY frozen type unfixable', () => {
    // Customer's primary storage is answering, so a sync can publish
    // it -- just without a current risk_score. Advice to wait is
    // correct here and wrong in the case above, which is the whole
    // distinction.
    const frozen = frozenTypes(silos({ risk_sql: { reachable: false } }))

    expect(unfixableTypes(frozen, ['Customer'])).toEqual([])
  })

  it('says nothing when everything has been published', () => {
    const frozen = frozenTypes(silos({ primary_sql: { reachable: false } }))

    expect(unfixableTypes(frozen, [])).toEqual([])
  })
})
