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

import { HTMLTable } from '@blueprintjs/core'
import Notice from '@elysium/shell-api/components/Notice'
import StatusTag from '@elysium/shell-api/components/StatusTag'
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
  /**
   * Set when this edit was part of a MULTI-OBJECT ACTION.
   *
   * The server sends it for a stated reason -- "so a UI can group the
   * writes that happened together; Foundry links a single action log
   * to every object it edited for the same reason" -- and no UI did.
   * `getObjectHistory` returns `Promise<unknown>`, so this interface
   * is the only declaration of the shape, and it simply omitted the
   * field.
   *
   * WITHOUT IT ONE ACTION READS AS MANY. A bulk change touching fifty
   * objects left fifty unrelated-looking rows in fifty histories, and
   * a reader asking "why did this change" could not tell a deliberate
   * sweep from somebody editing records one at a time.
   */
  batch_id?: string | null
}

interface HistoryBody {
  entries: HistoryEntry[]
}

export default function ObjectHistory({
  objectType,
  objectId,
  onSessionExpired,
}: {
  objectType: string
  objectId: string
  onSessionExpired: () => void
}) {
  const { data, error } = useFetchOnce<HistoryBody>(() => getObjectHistory(objectType, objectId), onSessionExpired)

  return (
    <AsyncPanel error={error} data={data}>
      {(body) =>
        body.entries.length === 0 ? (
          // An object nobody has edited is the ordinary case, and it
          // deserves a sentence rather than an empty table.
          <Notice state="neutral">No recorded changes to this object.</Notice>
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
                    <StatusTag>{entry.operation}</StatusTag>{' '}
                    {entry.batch_id && (
                      <>
                        {/* MARKED, NOT EXPANDED. This row cannot say how many other
                            objects the action touched -- the history endpoint
                            answers for ONE object, and asking it to count the rest
                            would mean counting objects this reader may not be
                            allowed to see. Saying the edit was part of a bulk
                            action is the honest half and the useful half. */}
                        <StatusTag state="active">part of a bulk action</StatusTag>{' '}
                      </>
                    )}
                    {Object.keys(entry.changes).length > 0 ? (
                      Object.keys(entry.changes).map(formatFieldName).join(', ')
                    ) : (
                      // Said plainly rather than left blank. An empty
                      // cell reads as a rendering fault; this is a
                      // deliberate disclosure boundary.
                      <span className="object-history__withheld">fields you cannot read</span>
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
