/**
 * Is THIS OBJECT TYPE healthy -- the question the Silos screen could
 * not answer.
 *
 * `AUDIT_CHECKLIST.csv` R6 asks for "health checks per table and
 * object type". Per TABLE largely existed: the Mirror panel already
 * judges every table it lists -- never synced, refused, N held back,
 * serving more than was last fetched -- and `health_condition.py`
 * computes refused and stale per table for the notification path. Per
 * OBJECT TYPE did not exist anywhere.
 *
 * THE DATA WAS ALREADY ON THE SCREEN AND NEVER CROSSED. `silos_route`
 * builds `types_by_silo`, `fields_by_silo` AND `failures` in one
 * function and returns them side by side, so an operator reads
 * "risk_sql -- unreachable", expands it, and works out for themselves
 * that this means `Customer.risk_score` and nothing else. Indexed by
 * silo, that audit is one expansion per silo; indexed by type, it is
 * one line.
 *
 * WHAT A DEAD SOURCE ACTUALLY COSTS, which a first version got wrong.
 * `read_from_mirror` has been ALWAYS TRUE since GOLD-9 -- live reads
 * are gone and `deployment_loader` refuses a config that asks for
 * them. Every read is served from published gold. So a source that
 * stops answering does NOT make its type unreadable; it makes it stop
 * REFRESHING, and the values being served go on being served, quietly
 * ageing. "Customer cannot be read" would have been a false alarm on
 * a deployment that was still answering every query correctly.
 *
 * EXCEPT IN ONE CASE, and it is the one worth finding: a type that has
 * NEVER been published has nothing in gold to serve, so its reads
 * genuinely do fail (`GoldPublicationMissing`) -- and if its source is
 * also down, the sync that would fix it cannot run. Waiting does not
 * help. Those two facts were already both on this screen, in different
 * sections, and nobody joined them either.
 *
 * A PURE FUNCTION OVER THE PAYLOAD, not a new endpoint. The silos
 * response already carries every input, under a grant that already
 * admits failure kinds; adding a route would re-serve the same facts
 * under the same grant. `worstFreshness` in `shell-api/api.ts` is the
 * precedent -- a severity judgement derived client-side from data the
 * client already holds. What a route WOULD be needed for is a
 * judgement that must not be re-derivable, and this is not one.
 */

/** As the silos payload has it. Declared here rather than imported so
 *  this module can be tested without a component. */
export interface SiloForHealth {
  name: string
  /** Everything it backs, primarily or as additional storage. */
  object_types: string[]
  /** Of those, the ones it is the PRIMARY storage for. Absent on a
   *  response from a server that predates the field, which reads as
   *  "nothing is primary here" -- see `frozenTypes`. */
  primary_for?: string[]
  fields: Array<{ object_type: string; field: string; is_identifier: boolean }>
  reachable: boolean
}

/** What an outage costs ONE object type. */
export interface FrozenType {
  objectType: string
  /** The unreachable silos it depends on, named. The kind of failure
   *  stays on the silo row; repeating it per type would put the same
   *  word on screen once per dependent type. */
  silos: string[]
  /**
   * WHOLE, as against PARTLY. True when a silo that is the type's
   * primary storage is down, so nothing about the object refreshes --
   * not even its identifier, which is why a half-refreshed object is
   * not a thing that can happen. False when only additional storage
   * is down and `fields` names exactly what stopped.
   */
  whole: boolean
  /** The fields that stopped refreshing. Empty when `whole`, because
   *  listing every field of a type that is entirely frozen is a wall
   *  of names that says less than the one word does. */
  fields: string[]
}

/**
 * Every type with an unreachable silo behind it, worst first.
 *
 * A TYPE APPEARS ONCE however many of its silos are down, because the
 * reader's question is about the type. Two dead silos behind one
 * Customer is one row naming both.
 *
 * A MISSING `primary_for` IS TREATED AS "NOT PRIMARY" rather than
 * guessed at. An older server does not send it; inferring primacy
 * from which silo holds the most fields would be a guess that reads
 * as a fact, and the failure mode of guessing wrong is telling
 * somebody their whole type is frozen when one field is. Under-
 * claiming is recoverable; over-claiming costs trust.
 */
export function frozenTypes(silos: SiloForHealth[]): FrozenType[] {
  const down = silos.filter((silo) => !silo.reachable)
  const byType = new Map<string, FrozenType>()

  for (const silo of down) {
    const primary = new Set(silo.primary_for ?? [])
    for (const objectType of silo.object_types) {
      const existing = byType.get(objectType) ?? { objectType, silos: [], whole: false, fields: [] }
      if (!existing.silos.includes(silo.name)) existing.silos.push(silo.name)
      if (primary.has(objectType)) existing.whole = true
      for (const field of silo.fields) {
        if (field.object_type !== objectType) continue
        // THE IDENTIFIER IS NOT A FIELD THAT STOPPED. It is emitted
        // once per storage holding the type, including additional
        // storage, so counting it would make every partial outage
        // look like it took the join key with it. When the PRIMARY
        // storage is down the type is `whole` anyway and this list is
        // not read.
        if (field.is_identifier) continue
        if (!existing.fields.includes(field.field)) existing.fields.push(field.field)
      }
      byType.set(objectType, existing)
    }
  }

  return [...byType.values()]
    .map((frozen) => ({
      ...frozen,
      silos: [...frozen.silos].sort(),
      // A WHOLE-TYPE OUTAGE CARRIES NO FIELD LIST, decided here rather
      // than at the call site so no caller can render both.
      fields: frozen.whole ? [] : [...frozen.fields].sort(),
    }))
    .sort((a, b) => Number(b.whole) - Number(a.whole) || a.objectType.localeCompare(b.objectType))
}

/**
 * The types that cannot be read AND cannot be fixed by waiting.
 *
 * NEVER PUBLISHED IS ALREADY REPORTED on this screen, and a dead
 * source is already reported on this screen, and the pair is worse
 * than either. A never-published type is normally a sync away from
 * working; one whose source is also down is not, and the two
 * notices side by side do not say so.
 */
export function unfixableTypes(frozen: FrozenType[], neverPublished: string[]): string[] {
  const whole = new Set(frozen.filter((entry) => entry.whole).map((entry) => entry.objectType))
  return neverPublished.filter((type) => whole.has(type)).sort()
}
