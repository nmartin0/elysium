/**
 * What has changed about this object, and who changed it.
 *
 * The write log has recorded every mutation -- operation, changed
 * fields, user and timestamp -- since before the UI existed, and the
 * endpoint to read it has existed too. Nothing called it.
 *
 * AUTHORIZATION IS THE SERVER'S, NOT THIS FILE'S, and its rule is
 * more subtle than "filter what you cannot read".
 *
 * Changed fields are filtered PER FIELD -- a caller granted
 * read:Customer but not read:Customer.email must not learn the email
 * changed, which would be a way around field-level RBAC. But an entry
 * whose changes are ENTIRELY ungranted still appears, with no fields
 * listed, "because the FACT that someone edited this object at a given
 * time is exactly what an audit trail is for".
 *
 * So an entry with no fields is not a bug and must not be hidden. This
 * file renders what it is given; adding a filter here would be a
 * second place for that rule to live, and it would suppress precisely
 * the entry the rule exists to preserve.
 */

import { Callout, HTMLTable, Tag } from '@blueprintjs/core'
import AsyncPanel from '@elysium/shell-api/components/AsyncPanel'
import { getObjectHistory } from '@elysium/shell-api/api'
import { useFetchOnce } from '@elysium/shell-api/useFetchOnce'
import { formatFieldName } from '@elysium/shell-api/format'

interface HistoryEntry {
  id: string
  operation: string
  changes: Record<string, unknown>
  user_id: string
  description: string
  created_at: string
}

interface HistoryBody {
  entries: HistoryEntry[]
}

export default function ObjectHistory({ objectType, objectId, onSessionExpired }: {
  objectType: string
  objectId: string
  onSessionExpired: () => void
}) {
  const { data, error } = useFetchOnce<HistoryBody>(
    () => getObjectHistory(objectType, objectId),
    onSessionExpired,
  )

  return (
    <AsyncPanel error={error} data={data}>
      {(body) => (
        body.entries.length === 0 ? (
          // An object nobody has edited is the ordinary case, and it
          // deserves a sentence rather than an empty table.
          <Callout intent="none">No recorded changes to this object.</Callout>
        ) : (
          <HTMLTable compact striped className="object-history">
            <thead>
              <tr>
                <th>When</th>
                <th>Who</th>
                <th>What</th>
              </tr>
            </thead>
            <tbody>
              {body.entries.map((entry) => (
                <tr key={entry.id}>
                  {/* The raw timestamp, deliberately. A relative time
                      ("2 hours ago") reads well and is useless in an
                      audit context, where the question is usually
                      "was this before or after X". */}
                  <td className="object-history__when">{entry.created_at}</td>
                  <td>{entry.user_id}</td>
                  <td>
                    <Tag minimal>{entry.operation}</Tag>{' '}
                    {Object.keys(entry.changes).length > 0
                      ? Object.keys(entry.changes).map(formatFieldName).join(', ')
                      : (
                        // Said plainly rather than left blank. An empty
                        // cell reads as a rendering fault; this is a
                        // deliberate disclosure boundary.
                        <span className="object-history__withheld">
                          fields you cannot read
                        </span>
                      )}
                  </td>
                </tr>
              ))}
            </tbody>
          </HTMLTable>
        )
      )}
    </AsyncPanel>
  )
}
