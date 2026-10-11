/**
 * What a frozen set on screen is, said on its face.
 *
 * DEV_UI 11.3: "THE TWO FAILURE MODES ARE FAQ ENTRIES, which is how
 * much the naming matters: 'why are contacts dropping off my list?' (it
 * is active) and 'why isn't my list updating?' (it is static).
 * Whichever a person is looking at must say so on its face."
 *
 * THREE FACTS, each only when true:
 *
 *   WHEN IT WAS FROZEN, and from which publication -- 11.4's "frozen
 *   14:22 · publication 7".
 *
 *   HOW MANY MEMBERS ARE NOT SHOWN, and deliberately not why. A member
 *   that was deleted and one that left this reader's compartment look
 *   the same; saying which would tell the reader something about an
 *   object they may not see. Counted, so the set never silently looks
 *   smaller than it was.
 *
 *   WHETHER ITS PUBLICATION HAS BEEN FORGOTTEN. Gold retains a bounded
 *   number of publications by design. A frozen set does not depend on
 *   its publication -- membership is keys, values are read live -- so
 *   this is information, not an error, and the values on screen are
 *   current either way.
 */

import { Button } from '@blueprintjs/core'
import Notice from '@elysium/shell-api/components/Notice'
import { getFrozenSet, handleIfSessionExpired, type FrozenSetDetail } from '@elysium/shell-api/api'
import { formatTimestamp } from '@elysium/shell-api/format'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { asChartFilters } from './aggregateCharts'

/** The live set of this type, with nothing narrowing it. */
function urlForLive(objectType: string): string {
  return `/browse?${new URLSearchParams({ type: objectType }).toString()}`
}

/**
 * The criteria a set was frozen from, as a LIVE set again -- DEV_UI
 * 11.3's "conversion both ways".
 *
 * ONE URL, ONE NAVIGATION. ObjectSearchPanel records why: "each URL
 * setter navigates rather than queueing, so calling both in sequence
 * made the second discard the first". Leaving the frozen set and
 * restoring its criteria as three setter calls kept only the last.
 */
function urlForCriteria(objectType: string, queryText: string, filters: ReturnType<typeof asChartFilters>): string {
  const params = new URLSearchParams({ type: objectType })
  if (queryText) params.set('q', queryText)
  if (filters.length > 0) params.set('filters', JSON.stringify(filters))
  return `/browse?${params.toString()}`
}

export default function FrozenNotice({
  setId,
  objectType,
  onSessionExpired,
  onLoaded,
}: {
  setId: string
  objectType: string
  onSessionExpired: () => void
  /** Hands the set's name up, so the subject line can say it. */
  onLoaded?: (set: FrozenSetDetail | null) => void
}) {
  const navigate = useNavigate()
  const [set, setSet] = useState<FrozenSetDetail | null>(null)
  const [gone, setGone] = useState(false)

  useEffect(() => {
    let cancelled = false
    getFrozenSet(setId)
      .then((found) => {
        if (cancelled) return
        setSet(found)
        setGone(false)
        onLoaded?.(found)
      })
      .catch((caught: unknown) => {
        if (cancelled) return
        if (handleIfSessionExpired(caught, onSessionExpired)) return
        // NOT YOURS OR NOT THERE, which the server answers identically
        // and so does this.
        setSet(null)
        setGone(true)
        onLoaded?.(null)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the set id IS the dependency
  }, [setId])

  if (gone) {
    return (
      <Notice state="pending" title="This frozen set is not available">
        It may have been deleted, or it belongs to somebody else.{' '}
        <Button small minimal onClick={() => navigate(urlForLive(objectType))}>
          Show the live set
        </Button>
      </Notice>
    )
  }
  if (set === null) return null

  const criteria = set.origin?.conditions ?? []
  const fromCriteria = Object.keys(set.origin ?? {}).length > 0

  return (
    <Notice state="neutral" className="frozen-notice" title={`Frozen set · ${set.name}`}>
      <p className="frozen-notice__line">
        {`${set.size.toLocaleString()} ${set.size === 1 ? 'member' : 'members'}, frozen ${formatTimestamp(set.frozen_at)}`}
        {set.published_at ? ` from the publication of ${formatTimestamp(set.published_at)}` : ''}
        {'. Values shown are current; membership is not.'}
      </p>
      {set.not_shown > 0 && (
        <p className="frozen-notice__line">
          {`${set.not_shown.toLocaleString()} of ${set.size.toLocaleString()} cannot be shown -- deleted since, or not visible to you.`}
        </p>
      )}
      {set.publication_retained === false && (
        <p className="frozen-notice__line">
          The publication it was frozen from has since been forgotten. Membership is unaffected.
        </p>
      )}
      <div className="frozen-notice__actions">
        {fromCriteria && (
          <Button
            small
            icon="refresh"
            onClick={() => navigate(urlForCriteria(objectType, set.origin.q ?? '', asChartFilters(criteria)))}
          >
            Return to its live criteria
          </Button>
        )}
        <Button small minimal onClick={() => navigate(urlForLive(objectType))}>
          Leave frozen set
        </Button>
      </div>
    </Notice>
  )
}
