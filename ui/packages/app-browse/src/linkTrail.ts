/**
 * Where a filtered Browse view came from, when it came by a link.
 *
 * VERTEX-LITE'S SECOND HALF. Following a link from an object's Related
 * section landed in Browse with a filter and no memory of how you got
 * there -- "Transactions where customer_id is cust_001" rather than
 * "Ada Okafor's 47 transactions".
 *
 * FOUNDRY'S ANSWER, and the shape here: "how you got here" is a LINK
 * FILTER carried in the URL, distinct from a property filter -- "you
 * can have many PROPERTY filters, but only 1 LINK filter" -- and linked
 * objects are "displayed by their title". One origin, not a chain,
 * which matches ExploreRelated's deliberate one hop at a time.
 *
 * THE TRAIL DESCRIBES THE CURRENT FILTER, NOT HISTORY. Remove or change
 * that filter and "Ada Okafor's transactions" would be a lie about what
 * is on screen. So it is shown only while the exact filter it came with
 * is still there, and it cannot disagree with the results.
 */

import type { ChartFilter } from './aggregateCharts'

export interface LinkOrigin {
  /** The object type the link was followed FROM. */
  type: string
  id: string
  /** The field on the listed type that points back at the origin. */
  field: string
}

function isOrigin(value: unknown): value is LinkOrigin {
  if (typeof value !== 'object' || value === null) return false
  const candidate = value as Record<string, unknown>
  return typeof candidate.type === 'string' && typeof candidate.id === 'string' && typeof candidate.field === 'string'
}

/** The origin, but only while the filter it describes is untouched.
 *
 *  UNTOUCHED MEANS EXACTLY: a keep filter on that field holding that
 *  one id and nothing else. Add a second value, flip it to exclude, or
 *  remove it, and the trail goes -- because it would no longer be true.
 *
 *  ANYTHING MALFORMED IS NO TRAIL. The URL is editable by hand, and a
 *  trail built from a guess would be worse than none. */
export function activeTrail(origin: unknown, filters: ChartFilter[]): LinkOrigin | null {
  if (!isOrigin(origin)) return null
  const describes = filters.some(
    (filter) =>
      filter.field === origin.field &&
      filter.mode === 'keep' &&
      filter.values.length === 1 &&
      filter.values[0] === origin.id,
  )
  return describes ? origin : null
}
