/**
 * Unusual values, shown where the record is read (R51; the owner, 19
 * October: everyone who may read the fields involved is told).
 *
 * THE PRECEDENT: Power BI marks an anomaly on the chart a viewer is
 * reading, with its explanation; Datadog's Watchdog puts its insights in
 * a banner on the logs being viewed, within the viewer's role; Atlan
 * shows quality results on the asset "so they can judge whether data is
 * trustworthy before using it". So the marker is on the row and on the
 * field, in words, not in a queue nobody but a reviewer opens.
 *
 * A SUGGESTION, NEVER A VERDICT: "unusual for its kind" -- the largest
 * order of the year is unusual and the most important row in the table.
 * A person who knows it is right marks it expected in the Inbox, and the
 * marker goes for everyone until the value changes.
 *
 * ABSENT RATHER THAN WRONG: a failure to ask shows no marker, as the
 * pending markers do -- nothing about the record itself is in doubt.
 */

import { getUnusualFor, type UnusualValue } from '@elysium/shell-api/api'
import StatusTag from '@elysium/shell-api/components/StatusTag'
import { useEffect, useState } from 'react'

export function useUnusualFor(objectType: string | null, ids: string[]): Record<string, UnusualValue[]> {
  const key = objectType ? `${objectType}|${ids.join(',')}` : ''
  const [found, setFound] = useState<{ key: string; unusual: Record<string, UnusualValue[]> }>({
    key: '',
    unusual: {},
  })

  useEffect(() => {
    if (!key) return
    const [type = '', joined = ''] = key.split('|')
    let cancelled = false
    getUnusualFor(type, joined ? joined.split(',') : [])
      .then((unusual) => {
        if (!cancelled) setFound({ key, unusual })
      })
      .catch(() => {
        // Absent rather than wrong; see the header.
      })
    return () => {
      cancelled = true
    }
  }, [key])

  return found.key === key ? found.unusual : {}
}

/** The row's marker: one word, the reasons on hover and in the record. */
export function UnusualTag({ values }: { values: UnusualValue[] | undefined }) {
  if (!values || values.length === 0) return null
  return (
    <StatusTag state="active" title={values.map((value) => value.reason).join('\n')}>
      unusual
    </StatusTag>
  )
}
