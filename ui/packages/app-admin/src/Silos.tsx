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

import { useState } from 'react'
import { Button, Callout, HTMLTable, Tag } from '@blueprintjs/core'
import { getSilos } from '@elysium/shell-api/api'
import AsyncPanel from '@elysium/shell-api/components/AsyncPanel'
import { useFetchOnce } from '@elysium/shell-api/useFetchOnce'

interface SiloBackedField {
  object_type: string
  field: string
  column: string
  table: string
  is_identifier: boolean
}

interface SiloStatus {
  name: string
  adapter: string
  object_types: string[]
  fields: SiloBackedField[]
  reachable: boolean
  failure: string | null
}

export default function Silos({ onSessionExpired }: { onSessionExpired: () => void }) {
  const { data: silos, error } = useFetchOnce<SiloStatus[]>(() => getSilos(), onSessionExpired)

  /**
   * Which silos are expanded, by name.
   *
   * GROUPING rather than colour carries the silo-to-field mapping.
   * Current research puts the limit for distinguishing categories by
   * colour at SIX, so a palette cannot serve a deployment with many
   * silos -- adjacency can, at any number, and scrolling is a
   * navigation problem rather than a perception one.
   */
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  function toggle(name: string) {
    const next = new Set(expanded)
    if (!next.delete(name)) next.add(name)
    setExpanded(next)
  }

  return (
    <AsyncPanel error={error} data={silos}>
      {(silos) => {
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
                {silos.flatMap((silo) => [
                  <tr key={silo.name}>
                    <td>
                      <Button
                        minimal
                        small
                        icon={expanded.has(silo.name) ? 'chevron-down' : 'chevron-right'}
                        onClick={() => toggle(silo.name)}
                        aria-expanded={expanded.has(silo.name)}
                        aria-label={`${expanded.has(silo.name) ? 'Hide' : 'Show'} fields backed by ${silo.name}`}
                      />
                      {silo.name}
                    </td>
                    <td>
                      <Tag minimal>{silo.adapter}</Tag>
                    </td>
                    <td>
                      {silo.reachable ? (
                        <Tag minimal intent="success">
                          reachable
                        </Tag>
                      ) : (
                        <>
                          <Tag minimal intent="danger">
                            unreachable
                          </Tag>{' '}
                          <span className="silos__failure">{silo.failure}</span>
                        </>
                      )}
                    </td>
                    <td>{silo.object_types.join(', ') || '—'}</td>
                  </tr>,
                  ...(expanded.has(silo.name)
                    ? [
                        <tr key={`${silo.name}-fields`} className="silos__fields-row">
                          <td colSpan={4}>
                            {silo.fields.length === 0 ? (
                              <span className="silos__failure">No fields are backed by this silo.</span>
                            ) : (
                              <HTMLTable compact className="silos__fields">
                                <thead>
                                  <tr>
                                    <th>Object type</th>
                                    <th>Field</th>
                                    <th>Table</th>
                                    <th>Column</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {silo.fields.map((field) => (
                                    <tr key={`${field.object_type}.${field.field}`}>
                                      <td>{field.object_type}</td>
                                      <td>
                                        {field.field}
                                        {/* The join key, tagged in place. A wrong
                                      one returns nothing or another
                                      object's row rather than a wrong
                                      value, so it belongs where someone is
                                      already scanning for mismatches. */}
                                        {/* A REAL space, not a CSS margin. Margin
                                      separates it visually and leaves the
                                      DOM text as "customer_ididentifier"
                                      -- which is what a screen reader
                                      announces and what a copy-paste
                                      produces. */}
                                        {field.is_identifier && (
                                          <>
                                            {' '}
                                            <Tag minimal className="silos__id-tag">
                                              identifier
                                            </Tag>
                                          </>
                                        )}
                                      </td>
                                      <td>{field.table}</td>
                                      <td>
                                        {/* Marked when it differs from the field
                                      name, because that is the case worth
                                      noticing: Customer.risk_score reads a
                                      column called score_val. */}
                                        {field.column}
                                        {field.column !== field.field && (
                                          <span className="silos__renamed"> (renamed)</span>
                                        )}
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </HTMLTable>
                            )}
                          </td>
                        </tr>,
                      ]
                    : []),
                ])}
              </tbody>
            </HTMLTable>
          </div>
        )
      }}
    </AsyncPanel>
  )
}
