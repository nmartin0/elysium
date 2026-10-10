/**
 * The set on screen, as a file.
 *
 * DEV_UI.md section 5 item 1 lists "exported" among what makes a set a
 * real thing, and section 3 records what the prior art's object
 * explorer does: "search, filter, work with the resulting set, and
 * export it. Needs no pre-configuration."
 *
 * BESIDE THE SET'S NAME, where "Ask about this set" already is. Both
 * act on the subject rather than on a row, and a toolbar somewhere
 * else would make a person look for them in two places.
 *
 * IT EXPORTS THE SET, NOT THE SELECTION, and the distinction is worth
 * stating because the Actions menu next to it does the opposite. An
 * action is something you do TO chosen objects, so defaulting to the
 * page is a safety property. An export is a copy of what you are
 * looking at, and "I filtered to 300 and got 50" is the surprise that
 * matters here.
 *
 * THE SERVER REFUSES RATHER THAN TRUNCATES above its ceiling, so this
 * does not need its own limit -- and must not invent one, because two
 * places deciding how many rows is too many is how they disagree. The
 * refusal arrives as an ordinary error with the real count in it.
 */

import { useState } from 'react'
import { Button } from '@blueprintjs/core'

import { exportObjects, getErrorMessage, handleIfSessionExpired } from '@elysium/shell-api/api'

export default function ExportSet({
  objectType,
  queryText,
  conditions,
  onSessionExpired,
}: {
  objectType: string | null
  queryText: string
  conditions: unknown[]
  onSessionExpired: () => void
}) {
  // WHAT THE LAST PRESS DID, or null. Not a boolean "exporting": the
  // only thing worth saying is why one did not work, and a spinner
  // for a request that finishes in a moment is noise.
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (!objectType) return null

  async function run() {
    setProblem(null)
    setBusy(true)
    try {
      await exportObjects(objectType as string, queryText, conditions)
    } catch (error) {
      if (handleIfSessionExpired(error, onSessionExpired)) return
      // THE SERVER'S OWN WORDS. It knows the real count and the
      // ceiling; a message written here would have to guess at both
      // and would drift from the one the route enforces.
      setProblem(getErrorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <Button className="export-set" minimal small icon="download" loading={busy} onClick={() => void run()}>
        Export
      </Button>
      {problem !== null && (
        <span className="export-set__problem" role="alert">
          {problem}
        </span>
      )}
    </>
  )
}
