/**
 * What names a type, a field or a link (the ontology's shape, designed
 * and agreed 27 October): the list that answers "what happens if I touch
 * this?" before touching it, and that removing anything will be gated on.
 *
 * PLAIN WORDS, GROUPED BY WHO OWNS THE REFERENCE. A role's grants belong
 * to whoever manages roles, an action to whoever wrote it, a rule to the
 * type's author. Grouping them that way is what lets each person see
 * their own part of the list and fix it.
 *
 * AN EMPTY LIST IS NEVER "NOTHING ANYWHERE". The server says what the
 * report does not look at (things stored beside the configuration), and
 * this always shows it.
 */

import { Button, Dialog, DialogBody, DialogFooter } from '@blueprintjs/core'
import { getErrorMessage, getUsedBy, handleIfSessionExpired, type UsedBy, type UsedByRow } from '@elysium/shell-api/api'
import DataTable from '@elysium/shell-api/components/DataTable'
import ErrorState from '@elysium/shell-api/components/ErrorState'
import LoadingState from '@elysium/shell-api/components/LoadingState'
import Notice from '@elysium/shell-api/components/Notice'
import { useEffect, useRef, useState } from 'react'

export type UsedByTarget = { objectType: string; field?: string } | { link: string }

/** Which owner a row belongs to, in the words a screen uses; anything new falls under "Inside the type". */
const GROUPS: [string, string[]][] = [
  ['Roles', ['grant']],
  ['Actions', ['action']],
  ['Links', ['link']],
  ['Row security', ['security']],
  ['Triggers', ['trigger']],
]
const INSIDE = 'Inside the type'

function groupOf(kind: string): string {
  return GROUPS.find(([, kinds]) => kinds.includes(kind))?.[0] ?? INSIDE
}

function describeTarget(target: UsedByTarget): string {
  if ('link' in target) return `link ${target.link}`
  return target.field === undefined ? target.objectType : `${target.objectType}.${target.field}`
}

export default function UsedByDialog({
  target,
  onClose,
  onSessionExpired,
}: {
  target: UsedByTarget
  onClose: () => void
  onSessionExpired: () => void
}) {
  const [report, setReport] = useState<UsedBy | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const latestSessionExpired = useRef(onSessionExpired)
  useEffect(() => {
    latestSessionExpired.current = onSessionExpired
  })

  useEffect(() => {
    let current = true
    getUsedBy(target)
      .then((found) => current && setReport(found))
      .catch((caught) => {
        if (!current || handleIfSessionExpired(caught, latestSessionExpired.current)) return
        setProblem(getErrorMessage(caught))
      })
    return () => {
      current = false
    }
    // The target is fixed for the life of the dialog.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const name = describeTarget(target)
  const groups = new Map<string, UsedByRow[]>()
  for (const row of report?.referrers ?? []) {
    const group = groupOf(row.kind)
    groups.set(group, [...(groups.get(group) ?? []), row])
  }
  const ordered = [...GROUPS.map(([label]) => label), INSIDE].filter((label) => groups.has(label))

  return (
    <Dialog isOpen onClose={onClose} title={`Used by: ${name}`} style={{ width: 640, maxWidth: '95vw' }}>
      <DialogBody>
        {problem !== null && <ErrorState>{problem}</ErrorState>}
        {problem === null && report === null && <LoadingState label="Looking for what names it…" />}
        {report !== null && (
          <>
            {report.referrers.length === 0 ? (
              <Notice>
                Nothing in the configuration names {name}. Taking it out would not break anything listed here.
              </Notice>
            ) : (
              <p>
                {report.referrers.length === 1
                  ? `One place in the configuration names ${name}.`
                  : `${report.referrers.length} places in the configuration name ${name}.`}{' '}
                Each must be changed by its owner before it can be removed.
              </p>
            )}
            {ordered.map((label) => (
              <section key={label} data-testid={`used-by-${label}`}>
                <h4>{label}</h4>
                <DataTable className="used-by__table">
                  <tbody>
                    {(groups.get(label) ?? []).map((row) => (
                      <tr key={`${row.kind}|${row.place}|${row.says}`}>
                        <td>
                          <strong>{row.place}</strong>
                        </td>
                        <td>{row.says}</td>
                      </tr>
                    ))}
                  </tbody>
                </DataTable>
              </section>
            ))}
            <p className="bp6-text-muted used-by__note">{report.not_listed}</p>
          </>
        )}
      </DialogBody>
      <DialogFooter actions={<Button onClick={onClose}>Close</Button>} />
    </Dialog>
  )
}
