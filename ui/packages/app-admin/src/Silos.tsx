/**
 * Which silos are configured, what they back, and whether they answer.
 *
 * Today a silo being down is something you learn from a failed query.
 * health_check() has existed per adapter since the beginning and
 * nothing showed it.
 *
 * REPORTS THE FAILURE KIND, NEVER THE MESSAGE -- FileNotFoundError
 * rather than the path it could not find. That distinguishes "the file
 * is gone" from "the credentials are wrong" without putting a host or
 * a path on a screen that might end up in a screenshot or a bug
 * report.
 */

import { useEffect, useState } from 'react'
import { Callout, HTMLTable, Spinner, Tag } from '@blueprintjs/core'
import { getErrorMessage, getSilos, handleIfSessionExpired } from '@elysium/shell-api/api'

interface SiloStatus {
  name: string
  adapter: string
  object_types: string[]
  reachable: boolean
  failure: string | null
}

export default function Silos({ onSessionExpired }: { onSessionExpired: () => void }) {
  const [silos, setSilos] = useState<SiloStatus[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    getSilos()
      .then((body) => {
        if (!cancelled) setSilos(body as SiloStatus[])
      })
      .catch((err: unknown) => {
        if (cancelled) return
        if (handleIfSessionExpired(err, onSessionExpired)) return
        setError(getErrorMessage(err))
      })
    return () => {
      cancelled = true
    }
  }, [onSessionExpired])

  if (error) return <Callout intent="danger">{error}</Callout>
  if (silos === null) return <Spinner />

  const unreachable = silos.filter((silo) => !silo.reachable)

  return (
    <div className="silos">
      {/* The summary first, because "is anything wrong" is the question
          this screen is opened to answer. A table of green rows makes
          you read every one to find that out. */}
      {unreachable.length > 0 ? (
        <Callout intent="danger" title="Some silos are not answering">
          {unreachable.map((silo) => silo.name).join(', ')}
        </Callout>
      ) : (
        <Callout intent="success">All {silos.length} silos are reachable.</Callout>
      )}

      <HTMLTable compact striped className="silos__table">
        <thead>
          <tr>
            <th>Silo</th>
            <th>Adapter</th>
            <th>Status</th>
            <th>Object types</th>
          </tr>
        </thead>
        <tbody>
          {silos.map((silo) => (
            <tr key={silo.name}>
              <td>{silo.name}</td>
              <td><Tag minimal>{silo.adapter}</Tag></td>
              <td>
                {silo.reachable ? (
                  <Tag minimal intent="success">reachable</Tag>
                ) : (
                  <>
                    <Tag minimal intent="danger">unreachable</Tag>{' '}
                    <span className="silos__failure">{silo.failure}</span>
                  </>
                )}
              </td>
              <td>{silo.object_types.join(', ') || '—'}</td>
            </tr>
          ))}
        </tbody>
      </HTMLTable>
    </div>
  )
}
