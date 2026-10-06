/**
 * What this deployment is actually running.
 *
 * READ-ONLY, and the screen you want when something behaves
 * unexpectedly -- "why did that query stop after eight steps" has no
 * answer today short of reading a YAML file on the server.
 *
 * It lives in Admin because the endpoint is gated on manage:users:
 * configuration discloses deployment shape, and while none of it is
 * object data, it is what an attacker maps a system with.
 *
 * NOTHING HERE IS EDITABLE, deliberately. Runtime config editing needs
 * a per-request snapshot first, or a change mid-flight leaves one
 * request disagreeing with itself.
 */

import { Button, HTMLTable, Tag } from '@blueprintjs/core'
import StatusTag from '@elysium/shell-api/components/StatusTag'
import {
  getConfigDiff,
  getConfigHistory,
  getDeploymentConfig,
  type ConfigDiff,
  handleIfSessionExpired,
  type ConfigHistory,
} from '@elysium/shell-api/api'
import { formatTimestamp } from '@elysium/shell-api/format'
import { useEffect, useRef, useState } from 'react'
import AsyncPanel from '@elysium/shell-api/components/AsyncPanel'
import { useFetchOnce } from '@elysium/shell-api/useFetchOnce'

interface DeploymentConfigBody {
  /** WHEN this configuration was loaded, and a digest over the four
   *  config files' bytes. The server has sent both since the endpoint
   *  existed and this panel declared neither, so "what is this
   *  deployment running" could not answer "since when" -- which is the
   *  first question when behaviour changed and nobody remembers a
   *  deploy. The digest discloses WHETHER the files changed, never
   *  what is in them. */
  loaded_at: string
  source_digest: string
  llm_provider: string
  step_model: string
  synthesis_model: string
  max_hops: number
  max_consecutive_duplicates: number
  max_consecutive_invalid_steps: number
  max_concurrent_requests: number
  security_attribute: string
  read_from_mirror: boolean
  enabled_tools: string[]
  silo_names: string[]
  object_type_count: number
  action_type_count: number
  role_names: string[]
}

/**
 * What this deployment has run before, and when it actually CHANGED.
 *
 * A FLAT LIST WOULD BE MOSTLY NOISE. Measured on a real deployment: 44
 * generations carrying TWO distinct digests. A generation whose digest
 * matches its predecessor is the same configuration loaded again --
 * a restart, not a change -- and rendering them undifferentiated
 * buries the two moments that matter under forty-two that do not.
 *
 * So each row says which it is, and only a CHANGE offers a diff. The
 * server returns WHICH FILES differ, never their contents, and this
 * asks for nothing more: the page is visible to anyone holding
 * manage:deployment, and file names answer "what moved" without
 * disclosing configuration.
 */
function ConfigHistorySection({ onSessionExpired }: { onSessionExpired: () => void }) {
  const [history, setHistory] = useState<ConfigHistory | null>(null)
  const [diffs, setDiffs] = useState<Record<number, ConfigDiff>>({})
  const latestSessionExpired = useRef(onSessionExpired)
  useEffect(() => {
    latestSessionExpired.current = onSessionExpired
  })

  useEffect(() => {
    let cancelled = false
    getConfigHistory()
      .then((next) => {
        if (!cancelled) setHistory(next)
      })
      .catch((caught: unknown) => {
        if (cancelled) return
        // AN EXPIRED SESSION IS NOT A HISTORY FAILURE. Swallowing it
        // here would leave someone on a page that has quietly stopped
        // being able to load anything -- caught by
        // sessionExpiry.test.ts, which exists because ObjectNotes did
        // exactly this.
        if (handleIfSessionExpired(caught, latestSessionExpired.current)) return
        // Anything else: a history failure must not blank the
        // configuration above it, which is the part of this page that
        // answers the urgent question. Nothing is rendered instead.
        setHistory(null)
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (history === null || history.generations.length === 0) return null

  // Oldest last, as the server sends them; a generation is a CHANGE
  // when its digest differs from the one loaded before it. The last
  // row has nothing before it, so it is where the record begins rather
  // than a change.
  const rows = history.generations.map((entry, index) => {
    const previous = history.generations[index + 1]
    return {
      ...entry,
      changed: previous !== undefined && previous.source_digest !== entry.source_digest,
      comparableWith: previous?.generation,
    }
  })

  return (
    <section className="deployment-config__history">
      <h3>Configuration history</h3>
      <HTMLTable compact striped aria-label="Configurations this deployment has run">
        <thead>
          <tr>
            <th>Generation</th>
            <th>Loaded</th>
            <th>Change</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.generation}>
              <td>
                {row.generation}
                {row.generation === history.current_generation && (
                  <StatusTag state="active" style={{ marginInlineStart: '0.5rem' }}>
                    running now
                  </StatusTag>
                )}
              </td>
              <td>{formatTimestamp(row.loaded_at)}</td>
              <td>
                {row.comparableWith === undefined ? (
                  <span className="bp6-text-muted">earliest recorded</span>
                ) : row.changed ? (
                  diffs[row.generation] ? (
                    <span>{diffs[row.generation]?.changed_files.join(', ') || 'no files differ'}</span>
                  ) : (
                    <Button
                      minimal
                      small
                      onClick={() => {
                        const older = row.comparableWith
                        if (older === undefined) return
                        getConfigDiff(older, row.generation)
                          .then((diff) => setDiffs((now) => ({ ...now, [row.generation]: diff })))
                          .catch(() => {
                            /* the row stays as it was; nothing to say */
                          })
                      }}
                    >
                      Which files?
                    </Button>
                  )
                ) : (
                  // NOT A CHANGE, and saying so is the point of the
                  // column. The same configuration was loaded again.
                  <span className="bp6-text-muted">restarted, same configuration</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </HTMLTable>
    </section>
  )
}

export default function DeploymentConfig({ onSessionExpired }: { onSessionExpired: () => void }) {
  const { data: config, error } = useFetchOnce<DeploymentConfigBody>(() => getDeploymentConfig(), onSessionExpired)

  return (
    <AsyncPanel error={error} data={config}>
      {(config) => {
        // Grouped by what a reader is looking for, not by the order the
        // config happens to declare them.
        const groups: [string, [string, React.ReactNode][]][] = [
          [
            // FIRST, because it identifies WHICH configuration the rest
            // of this page describes. Every value below is only true of
            // one generation, and without this the page reads as
            // timeless.
            'This configuration',
            [
              ['Loaded', formatTimestamp(config.loaded_at)],
              [
                // SHORTENED for reading, full value in the title. A
                // digest is compared, not read: the first characters
                // are enough to tell two apart at a glance, and the
                // whole thing is one hover away when it has to be
                // pasted somewhere.
                'Source digest',
                <span key="source-digest" title={config.source_digest}>
                  <code>{config.source_digest.slice(0, 12)}</code>
                </span>,
              ],
            ],
          ],
          [
            'Model',
            [
              ['Provider', config.llm_provider],
              ['Step model', config.step_model],
              ['Synthesis model', config.synthesis_model],
            ],
          ],
          [
            'Agent bounds',
            [
              ['Max hops', config.max_hops],
              ['Max consecutive duplicates', config.max_consecutive_duplicates],
              ['Max consecutive invalid steps', config.max_consecutive_invalid_steps],
              ['Max concurrent requests', config.max_concurrent_requests],
            ],
          ],
          [
            'Ontology',
            [
              ['Object types', config.object_type_count],
              ['Action types', config.action_type_count],
              ['Security attribute', config.security_attribute],
              ['Reading from mirror', config.read_from_mirror ? 'yes' : 'no'],
            ],
          ],
          [
            'Configured',
            [
              // NAMES only. The endpoint deliberately does not send silo
              // connection details or role grants -- names answer "what is
              // configured", contents would answer "what could I attack".
              ['Silos', config.silo_names.join(', ') || '—'],
              ['Roles', config.role_names.join(', ') || '—'],
              [
                'Tools',
                config.enabled_tools.length > 0
                  ? config.enabled_tools.map((tool) => (
                      <Tag key={tool} minimal>
                        {tool}
                      </Tag>
                    ))
                  : '—',
              ],
            ],
          ],
        ]
        return (
          <div className="deployment-config">
            {groups.map(([heading, rows]) => (
              <section key={heading}>
                <h3>{heading}</h3>
                <HTMLTable compact striped className="deployment-config__table">
                  <tbody>
                    {rows.map(([label, value]) => (
                      <tr key={label}>
                        <td className="deployment-config__label">{label}</td>
                        <td>{value}</td>
                      </tr>
                    ))}
                  </tbody>
                </HTMLTable>
              </section>
            ))}
            <ConfigHistorySection onSessionExpired={onSessionExpired} />
          </div>
        )
      }}
    </AsyncPanel>
  )
}
