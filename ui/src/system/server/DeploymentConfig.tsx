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
 * THE FIGURES ARE READ-ONLY; SOME SETTINGS CAN BE CHANGED BELOW them,
 * by someone holding manage:deployment (ConfigSettingsEditor). This
 * panel once said nothing could be, because "runtime config editing
 * needs a per-request snapshot first, or a change mid-flight leaves one
 * request disagreeing with itself". Each request now pins its
 * generation, and an edit reloads as a new one, so that reason is met.
 */

import { Button, Tag } from '@blueprintjs/core'
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
import DataTable from '@elysium/shell-api/components/DataTable'
import ConfigProposals from '@elysium/shell-api/components/ConfigProposals'
import RestoreDialog, { type RestoreOutcome } from './RestoreDialog'
import Notice from '@elysium/shell-api/components/Notice'
import ConfigSettingsEditor, { AppliedNotice } from './ConfigSettingsEditor'

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
  /** Search by meaning (R45); null when no type declares it. Absent from
   *  a server older than 17 October. */
  embedding_model?: string | null
  embedding_budget_seconds?: number
  /** Numbers per vector; null for the model's own size. */
  embedding_dimensions?: number | null
  /** Task prefixes as configured; null for the model family's own. */
  embedding_prefixes?: { document?: string; query?: string } | null
  max_hops: number
  max_consecutive_duplicates: number
  max_consecutive_invalid_steps: number
  /** AR-5: step replies constrained to the step schema. */
  constrain_steps?: boolean
  /** The agent switches turned on (core/llm/agent_features.py). */
  agent_features?: string[]
  /** AL-10: the per-query token budget; null for none. */
  max_tokens_per_query?: number | null
  /** Formerly BLOCKING 6: classification labels decide field access. */
  label_enforcement?: boolean
  /** R15: whether lineage events also go to a service (never its URL). */
  lineage_service?: boolean
  lineage_namespace?: string
  /** DEP-1: each silo's number and date locale; null = machine formats. */
  source_locales?: Record<string, string | null>
  /** ZOO-22: silos whose date columns may hold Excel serials. */
  excel_date_silos?: string[]
  /** BLOCKING item 3: the modules loaded, by id, in rail order. */
  modules?: string[]
  incremental_tables?: Record<string, string>
  max_concurrent_requests: number
  security_attribute: string
  read_from_mirror: boolean
  /**
   * THE FOUR OPERATIONAL TOGGLES. Each was added to DeploymentConfig
   * and then to the config response, and none reached this panel --
   * the one that answers "why is it behaving like that".
   *
   * OPTIONAL because a deployment that never set them sends nothing.
   * Absent means "this deployment does not say", which is not the same
   * as a value and must not render as one.
   */
  write_targets?: string[] | null
  trusted_proxies?: string[]
  on_type_mismatch?: string | null
  /** What a suspected source rename costs: 'hold' or 'serve_empty'. */
  on_suspected_rename?: string
  /** How often this deployment expects to sync, in hours. Every
   *  freshness threshold a reader is judged against derives from it. */
  sync_interval_hours?: number | null
  ingest_undeclared_columns?: boolean | null
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
function ConfigHistorySection({
  onSessionExpired,
  onRestored,
}: {
  onSessionExpired: () => void
  onRestored: (generation: number, outcome: RestoreOutcome) => void
}) {
  const [history, setHistory] = useState<ConfigHistory | null>(null)
  const [diffs, setDiffs] = useState<Record<number, ConfigDiff>>({})
  // PUTTING ONE BACK (DEV_UI 13.7): offered on a version whose files
  // differ from what runs now -- the same files would be nothing to do.
  const [restoring, setRestoring] = useState<number | null>(null)
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
  const runningDigest = history.generations.find(
    (entry) => entry.generation === history.current_generation,
  )?.source_digest
  // ONE OFFER PER CONFIGURATION, on its newest row. The first browser
  // check offered it on 47 rows, nearly all restarts of a handful of
  // configurations; putting back any of them puts back the same files.
  const offered = new Set<string>()
  const rows = history.generations.map((entry, index) => {
    const previous = history.generations[index + 1]
    const restorable =
      runningDigest !== undefined && entry.source_digest !== runningDigest && !offered.has(entry.source_digest)
    offered.add(entry.source_digest)
    return {
      ...entry,
      changed: previous !== undefined && previous.source_digest !== entry.source_digest,
      comparableWith: previous?.generation,
      restorable,
    }
  })

  return (
    <section className="deployment-config__history">
      <h3>Configuration history</h3>
      <DataTable aria-label="Configurations this deployment has run">
        <thead>
          <tr>
            <th>Generation</th>
            <th>Loaded</th>
            <th>Change</th>
            <th>
              <span className="bp6-text-muted">Put back</span>
            </th>
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
              <td>
                {row.restorable && (
                  <Button minimal small icon="undo" onClick={() => setRestoring(row.generation)}>
                    Put this version back
                  </Button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </DataTable>
      {restoring !== null && (
        <RestoreDialog
          generation={restoring}
          onClose={() => setRestoring(null)}
          onDone={(outcome) => {
            const from = restoring
            setRestoring(null)
            onRestored(from, outcome)
          }}
          onSessionExpired={onSessionExpired}
        />
      )}
    </section>
  )
}

export default function DeploymentConfig({ onSessionExpired }: { onSessionExpired: () => void }) {
  // AN EDIT REMOUNTS THE VIEW, so its figures are the new generation's
  // rather than what was loaded before the change. The notice lives
  // out here, where the remount cannot take it away.
  const [applied, setApplied] = useState<{
    generation: number
    count: number
    /** Put back from this generation, when that is what happened. */
    restoredFrom?: number
    waiting?: boolean
  } | null>(null)
  return (
    <>
      {applied &&
        (applied.waiting ? (
          <Notice state="pending" title="Waiting for approval">
            Putting generation {applied.restoredFrom} back lets people read more than they can now, so it applies once
            someone who manages roles approves it (Admin → Roles).
          </Notice>
        ) : applied.restoredFrom !== undefined ? (
          <Notice state="granted" title="Put back">
            Generation {applied.restoredFrom}’s files are the configuration again; the deployment reloaded as generation{' '}
            {applied.generation}.
          </Notice>
        ) : (
          <AppliedNotice generation={applied.generation} />
        ))}
      <DeploymentConfigView
        key={applied?.count ?? 0}
        onSessionExpired={onSessionExpired}
        onApplied={(generation) => setApplied((current) => ({ generation, count: (current?.count ?? 0) + 1 }))}
        onRestored={(from, outcome) =>
          setApplied((current) => ({
            generation: outcome.status === 'applied' ? outcome.generation : (current?.generation ?? 0),
            count: (current?.count ?? 0) + 1,
            restoredFrom: from,
            waiting: outcome.status === 'waiting',
          }))
        }
      />
    </>
  )
}

function DeploymentConfigView({
  onSessionExpired,
  onApplied,
  onRestored,
}: {
  onSessionExpired: () => void
  onApplied: (generation: number) => void
  onRestored: (generation: number, outcome: RestoreOutcome) => void
}) {
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
              ['Modules', config.modules === undefined ? 'not reported' : config.modules.join(', ') || 'none'],
            ],
          ],
          [
            'Model',
            [
              ['Provider', config.llm_provider],
              ['Step model', config.step_model],
              ['Synthesis model', config.synthesis_model],
              ['Embedding model', config.embedding_model ?? 'none (no search by meaning)'],
              [
                'Embedding size',
                config.embedding_dimensions ? `${config.embedding_dimensions} numbers` : "the model's own",
              ],
              [
                'Embedding prefixes',
                config.embedding_prefixes
                  ? `document "${config.embedding_prefixes.document ?? ''}", query "${config.embedding_prefixes.query ?? ''}"`
                  : "the model family's own",
              ],
              [
                'Embedding budget per sync',
                config.embedding_budget_seconds === undefined ? '—' : `${config.embedding_budget_seconds} s`,
              ],
            ],
          ],
          [
            'Agent bounds',
            [
              ['Max hops', config.max_hops],
              ['Max consecutive duplicates', config.max_consecutive_duplicates],
              ['Max consecutive invalid steps', config.max_consecutive_invalid_steps],
              ['Steps constrained to the schema', config.constrain_steps ? 'yes' : 'no'],
              [
                'Agent switches on',
                config.agent_features === undefined ? 'not reported' : config.agent_features.join(', ') || 'none',
              ],
              [
                'Token budget per question',
                config.max_tokens_per_query === undefined
                  ? 'not reported'
                  : config.max_tokens_per_query === null
                    ? 'none'
                    : `${config.max_tokens_per_query.toLocaleString()} tokens`,
              ],
              ['Max concurrent requests', config.max_concurrent_requests],
            ],
          ],
          [
            'Ontology',
            [
              ['Object types', config.object_type_count],
              ['Action types', config.action_type_count],
              ['Security attribute', config.security_attribute],
              ['Classification labels decide field access', config.label_enforcement ? 'yes' : 'no'],
              [
                'Triggers checked',
                'after each sync, as soon as a change is saved, and for a date filter when a record crosses its window',
              ],
              ['Reading from mirror', config.read_from_mirror ? 'yes' : 'no'],
            ],
          ],
          [
            'Operational',
            [
              // WHAT EACH ANSWERS, because a label alone does not.
              //
              // `write_targets` -- which silos a confirmed write may reach.
              // Empty means none: a deployment that answers questions and
              // cannot change anything.
              //
              // `trusted_proxies` -- whose forwarded-for header is believed
              // when rate-limiting a login. Empty means the TCP peer is
              // used, which is right unless something sits in front.
              //
              // `on_type_mismatch` -- what a bad cell costs. The shipped
              // default quarantines the ROW rather than failing the table.
              //
              // `ingest_undeclared_columns` -- whether a column the ontology
              // never mentioned reaches bronze at all.
              [
                'Write targets',
                config.write_targets === undefined ? 'not reported' : (config.write_targets ?? []).join(', ') || 'none',
              ],
              [
                'Trusted proxies',
                config.trusted_proxies === undefined
                  ? 'not reported'
                  : config.trusted_proxies.join(', ') || 'none (TCP peer)',
              ],
              ['On type mismatch', config.on_type_mismatch ?? 'not reported'],
              // `on_suspected_rename` -- a column gone and a new one arrived:
              // hold the table, or serve the field empty.
              ['On suspected rename', config.on_suspected_rename ?? 'not reported'],
              [
                // HOW EACH SOURCE WRITES NUMBERS AND DATES. The first
                // place to look when a silo's rows are being set aside
                // as type mismatches: `1.234,56` read as en_US is not
                // a number.
                'Source number and date formats',
                config.source_locales === undefined
                  ? 'not reported'
                  : Object.entries(config.source_locales)
                      .map(
                        ([silo, locale]) =>
                          `${silo}: ${locale ?? 'machine formats only'}` +
                          (config.excel_date_silos?.includes(silo) ? ' and Excel date serials' : ''),
                      )
                      .join(', ') || 'none',
              ],
              [
                // WHICH TABLES READ ONLY WHAT CHANGED (R2). The place to
                // look when a deletion took days to reach the mirror:
                // only the scheduled full read can see one.
                'Tables read by changed rows',
                config.incremental_tables === undefined
                  ? 'not reported'
                  : Object.entries(config.incremental_tables)
                      .map(([table, how]) => `${table} by ${how}`)
                      .join(', ') || 'none (every table is read in full)',
              ],
              [
                // THE FILE IS ALWAYS WRITTEN, so the only question is
                // whether a service receives them too.
                'Lineage events',
                config.lineage_service === undefined
                  ? 'not reported'
                  : `lineage.jsonl${config.lineage_service ? ' and a lineage service' : ' only'}` +
                    ` (namespace ${config.lineage_namespace ?? 'elysium'})`,
              ],
              [
                // WHERE THE FRESHNESS WINDOWS COME FROM. Browse now
                // tells a reader "Overdue -- this deployment expects
                // one every 26 hours", and 26 is this number times a
                // constant. Without it on this panel, the only honest
                // answer to "where did 26 come from" is to read the
                // source.
                'Expected sync interval',
                config.sync_interval_hours === undefined || config.sync_interval_hours === null
                  ? 'not reported'
                  : `every ${config.sync_interval_hours} hours`,
              ],
              [
                'Ingest undeclared columns',
                config.ingest_undeclared_columns === undefined || config.ingest_undeclared_columns === null
                  ? 'not reported'
                  : config.ingest_undeclared_columns
                    ? 'yes'
                    : 'no',
              ],
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
                <DataTable className="deployment-config__table">
                  <tbody>
                    {rows.map(([label, value]) => (
                      <tr key={label}>
                        <td className="deployment-config__label">{label}</td>
                        <td>{value}</td>
                      </tr>
                    ))}
                  </tbody>
                </DataTable>
              </section>
            ))}
            <ConfigSettingsEditor onApplied={onApplied} onSessionExpired={onSessionExpired} />
            {/* What this deployment's managers proposed and still waits
                for a role manager -- shown here so its proposer can see
                it, and withdraw it. Nothing when nothing waits. */}
            <ConfigProposals onSessionExpired={onSessionExpired} />
            <ConfigHistorySection onSessionExpired={onSessionExpired} onRestored={onRestored} />
          </div>
        )
      }}
    </AsyncPanel>
  )
}
