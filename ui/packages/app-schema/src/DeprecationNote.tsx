/**
 * The sentence that goes beside a deprecated name wherever it appears
 * (the removal design, 28 October): why, what to use instead, and the
 * day removal is planned. A name marked deprecated with no reason shows
 * only the tag, because there is nothing honest to add.
 *
 * A LINK THAT TOOK ITS STATUS FROM A TYPE says which: "deprecated because
 * Customer is", so nobody hunts for a reason the link itself never gave.
 */

import type { Deprecation } from '@elysium/shell-api/types'

export default function DeprecationNote({
  status,
  deprecation,
  inheritedFrom,
}: {
  status: string | undefined
  deprecation: Deprecation | null | undefined
  inheritedFrom?: string | null
}) {
  if (status !== 'deprecated') return null
  if (inheritedFrom) {
    return <div className="schema-panel__deprecation">{`Deprecated because ${inheritedFrom} is.`}</div>
  }
  if (!deprecation?.reason) return null
  return (
    <div className="schema-panel__deprecation">
      {`Deprecated: ${deprecation.reason}`}
      {deprecation.replaced_by && ` Use ${deprecation.replaced_by} instead.`}
      {deprecation.remove_after && ` Removal planned after ${deprecation.remove_after}.`}
    </div>
  )
}
