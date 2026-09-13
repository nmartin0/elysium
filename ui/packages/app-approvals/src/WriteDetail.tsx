/**
 * WriteDetail -- what a pending write would actually change.
 *
 * THE REDACTION IS THE POINT OF THIS COMPONENT. A field the reviewer
 * may not read is SHOWN, named, and marked -- never omitted. Omitting
 * leaks less and is worse: a reviewer seeing three fields cannot tell
 * whether that is the whole change or a fragment, so they approve
 * believing they saw everything. That is the rubber-stamp problem in
 * its worst form, because it produces MORE confidence rather than
 * less.
 *
 * Following Foundry, whose review surface "redacts certain resources
 * or users contained in a record if you do not have the necessary
 * permissions to view that item".
 */

import { Callout, HTMLTable, Spinner, Tag } from '@blueprintjs/core'
import { useEffect, useState } from 'react'

import {
  type WriteDetailResponse,
  getErrorMessage,
  getWriteDetail,
  handleIfSessionExpired,
} from '@elysium/shell-api/api'
import { formatValue } from '@elysium/shell-api/format'

interface WriteDetailProps {
  writeId: string
  onSessionExpired: () => void
}

export default function WriteDetail({ writeId, onSessionExpired }: WriteDetailProps) {
  const [detail, setDetail] = useState<WriteDetailResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    getWriteDetail(writeId)
      .then((loaded) => {
        if (!cancelled) setDetail(loaded)
      })
      .catch((caught) => {
        if (handleIfSessionExpired(caught, onSessionExpired)) return
        if (!cancelled) setError(getErrorMessage(caught))
      })
    // Cancelled rather than left to resolve into an unmounted
    // component: a reviewer opening and closing rows faster than the
    // fetches return would otherwise show the wrong diff.
    return () => {
      cancelled = true
    }
  }, [writeId, onSessionExpired])

  if (error !== null) return <Callout intent="danger">{error}</Callout>
  if (detail === null) return <Spinner size={20} />

  return (
    <div className="write-detail">
      {detail.has_redacted_fields && (
        // SAID ONCE, PROMINENTLY, as well as marked per row. A
        // reviewer scanning a table can miss a tag; the one thing they
        // must not miss is that they are deciding on a partial view.
        <Callout intent="warning" title="You cannot see all of this change">
          Some fields below are hidden by your permissions. Approving applies every change, including the ones you
          cannot read.
        </Callout>
      )}

      {detail.objects.map((object) => (
        <div key={`${object.object_type}:${object.object_id}`} className="write-detail__object">
          <p className="write-detail__object-title">
            {object.operation} {object.object_type} {object.object_id}
          </p>
          <HTMLTable compact striped className="write-detail__changes">
            <thead>
              <tr>
                <th>Field</th>
                <th>Current</th>
                <th>Proposed</th>
              </tr>
            </thead>
            <tbody>
              {object.changes.map((change) => (
                <tr key={change.field_name}>
                  <td>{change.field_name}</td>
                  {change.readable ? (
                    <>
                      <td>{formatValue(change.current_value)}</td>
                      <td>{formatValue(change.proposed_value)}</td>
                    </>
                  ) : (
                    // ONE CELL SPANNING BOTH, not two empty ones.
                    // Empty cells read as "no value"; this reads as
                    // "withheld", which is a different fact.
                    <td colSpan={2}>
                      <Tag minimal intent="warning">
                        Hidden by your permissions
                      </Tag>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </HTMLTable>
        </div>
      ))}
    </div>
  )
}
