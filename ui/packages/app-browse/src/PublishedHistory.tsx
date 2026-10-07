/**
 * What changed in the SOURCE, as the mirror saw it.
 *
 * THE ENDPOINT HAD NO CALLER AT ALL. `/published-history` is built,
 * authorised, documented and reached by nothing -- one of three routes
 * out of fifty-five that no screen calls, and the only one of those
 * three that is not operational plumbing.
 *
 * WHY IT IS NOT THE SAME AS EDIT HISTORY, which is the whole reason it
 * exists. The route's own words: edit history answers "who changed
 * this through Elysium"; this answers "what changed in the SOURCE
 * between publications". A row somebody edited directly in the
 * customer's own database appears HERE and never there.
 *
 * That gap is the one a reader most needs closed. An object whose
 * values are not what they expect, with an empty edit history, is
 * either a mystery or an answer depending on whether this panel
 * exists.
 *
 * AN EMPTY LIST IS NOT AN ERROR, and has three ordinary causes worth
 * distinguishing in the copy rather than in the code: nothing has
 * changed since publication, the deployment reads live and publishes
 * nothing, or the caller may not read this object -- the route returns
 * an empty list rather than a 403, so a response never distinguishes
 * "no such object" from "not yours". The panel therefore says what it
 * knows and does not guess which case it is in.
 */

import { HTMLTable } from '@blueprintjs/core'

import { getPublishedHistory, type PublishedChange } from '@elysium/shell-api/api'
import AsyncPanel from '@elysium/shell-api/components/AsyncPanel'
import Notice from '@elysium/shell-api/components/Notice'
import StatusTag from '@elysium/shell-api/components/StatusTag'
import { useFetchOnce } from '@elysium/shell-api/useFetchOnce'

/** An insert, an update, a delete -- as a tag state. */
const CHANGE_STATE = {
  insert: 'granted',
  update: 'active',
  delete: 'refused',
} as const

function changeState(change: string) {
  return CHANGE_STATE[change.toLowerCase() as keyof typeof CHANGE_STATE] ?? 'neutral'
}

export default function PublishedHistory({
  objectType,
  objectId,
  onSessionExpired,
}: {
  objectType: string
  objectId: string
  onSessionExpired: () => void
}) {
  const { data, error } = useFetchOnce<PublishedChange[]>(
    () => getPublishedHistory(objectType, objectId),
    onSessionExpired,
  )

  return (
    <AsyncPanel error={error} data={data}>
      {(changes) =>
        changes.length === 0 ? (
          <Notice state="neutral">Nothing recorded since this object was last published.</Notice>
        ) : (
          <HTMLTable compact striped className="published-history">
            <thead>
              <tr>
                <th>When</th>
                <th>What</th>
                <th>Fields</th>
              </tr>
            </thead>
            <tbody>
              {changes.map((change, index) => (
                <tr key={`${change.changed_at}-${index}`}>
                  {/* The raw timestamp, as the edit history does. A
                      relative time reads well and is useless when the
                      question is "was this before or after X". */}
                  <td className="published-history__when">{change.changed_at}</td>
                  <td>
                    <StatusTag state={changeState(change.change)}>{change.change}</StatusTag>
                    {change.publication && (
                      <>
                        {' '}
                        <span className="published-history__publication">in {change.publication}</span>
                      </>
                    )}
                  </td>
                  <td>
                    {/* NAMES, NOT VALUES. The route returns only fields
                        this caller may read, so the values are safe to
                        show -- but a history table is read to find WHAT
                        moved, and a row of values makes that harder, not
                        easier. Opening the object shows the values. */}
                    {Object.keys(change.values).length > 0 ? (
                      Object.keys(change.values).join(', ')
                    ) : (
                      <span className="published-history__withheld">fields you cannot read</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </HTMLTable>
        )
      }
    </AsyncPanel>
  )
}
