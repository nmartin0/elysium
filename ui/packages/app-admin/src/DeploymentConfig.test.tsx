import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'

const getDeploymentConfig = vi.fn()
const getConfigHistory = vi.fn()
const getConfigDiff = vi.fn()
const previewRestore = vi.fn()
const restoreGeneration = vi.fn()

vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return {
    ...actual,
    getDeploymentConfig: () => getDeploymentConfig(),
    getConfigHistory: () => getConfigHistory(),
    getConfigDiff: (older: number, newer: number) => getConfigDiff(older, newer),
    previewRestore: (generation: number) => previewRestore(generation),
    restoreGeneration: (generation: number, digest: string, reason: string | null) =>
      restoreGeneration(generation, digest, reason),
    // The waiting-changes list fetches on mount; not what these are about.
    getConfigProposals: () => new Promise(() => {}),
  }
})

const { default: DeploymentConfig } = await import('./DeploymentConfig')

const BODY = {
  loaded_at: new Date(Date.now() - 3 * 60 * 60_000).toISOString(),
  source_digest: 'a1b2c3d4e5f60718293a4b5c6d7e8f90',
  llm_provider: 'ollama',
  step_model: 'qwen',
  synthesis_model: 'qwen',
  max_hops: 8,
  max_consecutive_duplicates: 2,
  max_consecutive_invalid_steps: 2,
  max_concurrent_requests: 4,
  security_attribute: 'region',
  read_from_mirror: false,
  enabled_tools: ['calculator'],
  silo_names: ['primary_sql', 'support_crm'],
  object_type_count: 5,
  action_type_count: 3,
  role_names: ['admin', 'customer_service'],
}

beforeEach(() => {
  vi.clearAllMocks()
  getDeploymentConfig.mockResolvedValue(BODY)
  getConfigHistory.mockResolvedValue({ current_generation: 0, generations: [] })
  getConfigDiff.mockReset()
})

describe('DeploymentConfig', () => {
  it('answers the question it exists for', async () => {
    // "Why did that query stop after eight steps" had no answer short
    // of reading a YAML file on the server.
    render(<DeploymentConfig onSessionExpired={() => {}} />)

    expect(await screen.findByText('Max hops')).toBeInTheDocument()
    expect(screen.getByText('8')).toBeInTheDocument()
  })

  it('says whether step replies are constrained (AR-5)', async () => {
    // A query that behaves differently once the grammar is on has to be
    // explainable from this screen, not from config.yaml.
    render(<DeploymentConfig onSessionExpired={() => {}} />)

    const label = await screen.findByText('Steps constrained to the schema')
    expect(label.parentElement).toHaveTextContent(/no$/)
  })

  it('names the agent switches that are on', async () => {
    // Four switches wait on a bench (core/llm/agent_features.py); which
    // are on decides what the model may do, so it is shown here.
    getDeploymentConfig.mockResolvedValue({
      ...BODY,
      agent_features: ['filter_operators', 'search_result_cap=20'],
    })
    render(<DeploymentConfig onSessionExpired={() => {}} />)

    const label = await screen.findByText('Agent switches on')
    expect(label.parentElement).toHaveTextContent(/filter_operators, search_result_cap=20$/)
  })

  it('says none when no agent switch is on', async () => {
    getDeploymentConfig.mockResolvedValue({ ...BODY, agent_features: [] })
    render(<DeploymentConfig onSessionExpired={() => {}} />)

    const label = await screen.findByText('Agent switches on')
    expect(label.parentElement).toHaveTextContent(/none$/)
  })

  it('names silos and roles without describing them', async () => {
    /**
     * The endpoint deliberately sends NAMES only -- no silo connection
     * details, no role grants. Names answer "what is configured";
     * contents would answer "what could I attack".
     *
     * This asserts the view does not invent a place to show what it
     * was never given.
     */
    render(<DeploymentConfig onSessionExpired={() => {}} />)
    await screen.findByText('Max hops')

    expect(screen.getByText('primary_sql, support_crm')).toBeInTheDocument()
    expect(screen.queryByText(/connection/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/allowed_actions/)).not.toBeInTheDocument()
  })

  it('reports a failure rather than an empty screen', async () => {
    getDeploymentConfig.mockRejectedValue(new Error('config unavailable'))

    render(<DeploymentConfig onSessionExpired={() => {}} />)

    expect(await screen.findByText(/config unavailable/)).toBeInTheDocument()
  })

  it('shows nothing is editable', async () => {
    // Runtime editing needs a per-request snapshot first, or a change
    // mid-flight leaves one request disagreeing with itself.
    render(<DeploymentConfig onSessionExpired={() => {}} />)
    await screen.findByText('Max hops')

    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })
})

describe('which configuration this is', () => {
  /**
   * The server has sent loaded_at and source_digest since this
   * endpoint existed; the panel declared neither. "What is this
   * deployment running" could not answer "since when", which is the
   * first question asked when behaviour changed and nobody remembers
   * a deploy.
   */
  it('says when the configuration was loaded', async () => {
    render(<DeploymentConfig onSessionExpired={vi.fn()} />)

    expect(await screen.findByText('Loaded')).toBeInTheDocument()
    expect(screen.getByText('3 hours ago')).toBeInTheDocument()
  })

  it('shows a digest short enough to compare, with the whole one to hand', async () => {
    // A digest is COMPARED, not read. The first characters tell two
    // apart at a glance; the full value is one hover away for when it
    // has to be pasted somewhere.
    render(<DeploymentConfig onSessionExpired={vi.fn()} />)

    const shown = await screen.findByText('a1b2c3d4e5f6')
    expect(shown).toBeInTheDocument()
    expect(shown.closest('[title]')).toHaveAttribute('title', BODY.source_digest)
  })

  it('puts it FIRST, because it identifies what the rest describes', async () => {
    // Every value on this page is true of one generation only. Below
    // the model settings it would read as a footnote about something
    // else.
    render(<DeploymentConfig onSessionExpired={vi.fn()} />)
    await screen.findByText('Loaded')

    const headings = screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent)
    expect(headings[0]).toBe('This configuration')
  })
})

const SAME = 'digest-aaa'
const OTHER = 'digest-bbb'

function historyOf(entries: [number, string][]) {
  return {
    current_generation: entries[0]![0],
    generations: entries.map(([generation, source_digest]) => ({
      generation,
      source_digest,
      loaded_at: new Date(Date.now() - generation * 60_000).toISOString(),
    })),
  }
}

describe('what this deployment has run before', () => {
  /**
   * A FLAT LIST WOULD BE MOSTLY NOISE. Measured on a real deployment:
   * 44 generations carrying TWO distinct digests. Most are restarts,
   * not changes, and rendering them undifferentiated buries the two
   * moments that matter under forty-two that do not.
   */
  it('says which generations were restarts rather than changes', async () => {
    getConfigHistory.mockResolvedValue(
      historyOf([
        [3, SAME],
        [2, SAME],
        [1, OTHER],
      ]),
    )
    render(<DeploymentConfig onSessionExpired={vi.fn()} />)

    const table = await screen.findByRole('table', { name: 'Configurations this deployment has run' })
    expect(within(table).getAllByText(/restarted, same configuration/)).toHaveLength(1)
    expect(within(table).getByRole('button', { name: /which files/i })).toBeInTheDocument()
  })

  it('marks the earliest record as a beginning, not a change', async () => {
    // The oldest row has nothing before it. Calling it a change would
    // invent one; calling it a restart would claim something about a
    // configuration we have no record of.
    getConfigHistory.mockResolvedValue(historyOf([[1, SAME]]))
    render(<DeploymentConfig onSessionExpired={vi.fn()} />)

    expect(await screen.findByText(/earliest recorded/)).toBeInTheDocument()
  })

  it('names which files changed, only when asked', async () => {
    // One request per change, on demand. Fetching all of them on load
    // would be a request per row for information most rows lack.
    getConfigHistory.mockResolvedValue(
      historyOf([
        [2, OTHER],
        [1, SAME],
      ]),
    )
    getConfigDiff.mockResolvedValue({
      older: 1,
      newer: 2,
      changed_files: ['policy.yaml', 'ontology_schema.yaml'],
      unchanged: false,
    })
    render(<DeploymentConfig onSessionExpired={vi.fn()} />)
    await screen.findByRole('table', { name: 'Configurations this deployment has run' })

    expect(getConfigDiff).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: /which files/i }))

    expect(await screen.findByText('policy.yaml, ontology_schema.yaml')).toBeInTheDocument()
    expect(getConfigDiff).toHaveBeenCalledWith(1, 2)
  })

  it('marks which generation is running now', async () => {
    getConfigHistory.mockResolvedValue(
      historyOf([
        [2, OTHER],
        [1, SAME],
      ]),
    )
    render(<DeploymentConfig onSessionExpired={vi.fn()} />)

    expect(await screen.findByText('running now')).toBeInTheDocument()
  })

  it('shows the configuration even when its history cannot be read', async () => {
    // The two fetches are INDEPENDENT. A history failure must not
    // blank the panel above it.
    getConfigHistory.mockRejectedValue(new Error('nope'))
    render(<DeploymentConfig onSessionExpired={vi.fn()} />)

    expect(await screen.findByText('Loaded')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /configuration history/i })).not.toBeInTheDocument()
  })
})

describe('the four operational toggles', () => {
  /**
   * Each was added to DeploymentConfig, then to the config response,
   * and none reached this panel -- the one that exists to answer "why
   * is it behaving like that". The response model's own comment says
   * the omission "was silent four times running"; this is the other
   * end of that.
   */

  it('shows which silos a confirmed write may reach', async () => {
    getDeploymentConfig.mockResolvedValue({ ...BODY, write_targets: ['primary_sql'] })
    render(<DeploymentConfig onSessionExpired={() => {}} />)

    expect(await screen.findByText('Write targets')).toBeInTheDocument()
    expect(screen.getByText('primary_sql')).toBeInTheDocument()
  })

  it('says "none" rather than nothing when writes reach no silo', async () => {
    /** A deployment that answers questions and cannot change anything
     *  is a real and deliberate configuration. An empty cell would read
     *  as a missing value. */
    getDeploymentConfig.mockResolvedValue({ ...BODY, write_targets: [] })
    render(<DeploymentConfig onSessionExpired={() => {}} />)

    await screen.findByText('Write targets')
    expect(screen.getByText('none')).toBeInTheDocument()
  })

  it('says what an empty proxy list MEANS, not just that it is empty', async () => {
    /** Empty is not an absence here: it means the TCP peer is used for
     *  rate-limit bucketing, which is correct unless something sits in
     *  front. "none" alone would leave a reader guessing. */
    getDeploymentConfig.mockResolvedValue({ ...BODY, trusted_proxies: [] })
    render(<DeploymentConfig onSessionExpired={() => {}} />)

    await screen.findByText('Trusted proxies')
    expect(screen.getByText('none (TCP peer)')).toBeInTheDocument()
  })

  it('shows the mismatch policy and the undeclared-column setting', async () => {
    getDeploymentConfig.mockResolvedValue({
      ...BODY,
      on_type_mismatch: 'quarantine',
      on_suspected_rename: 'serve_empty',
      ingest_undeclared_columns: false,
    })
    render(<DeploymentConfig onSessionExpired={() => {}} />)

    expect(await screen.findByText('On type mismatch')).toBeInTheDocument()
    expect(screen.getByText('quarantine')).toBeInTheDocument()
    expect(screen.getByText('On suspected rename')).toBeInTheDocument()
    expect(screen.getByText('serve_empty')).toBeInTheDocument()
    expect(screen.getByText('Ingest undeclared columns')).toBeInTheDocument()
  })

  it('distinguishes "not set" from a value', async () => {
    /** THE DISTINCTION THAT MATTERS. A deployment that never set these
     *  sends nothing. Rendering absent as "no" would assert a setting
     *  nobody chose -- and for `ingest_undeclared_columns` the two
     *  answers have opposite consequences for what reaches bronze. */
    getDeploymentConfig.mockResolvedValue(BODY)
    render(<DeploymentConfig onSessionExpired={() => {}} />)

    await screen.findByText('Write targets')
    expect(screen.getAllByText('not reported').length).toBeGreaterThanOrEqual(3)
  })
})

describe('where the freshness windows come from', () => {
  /**
   * Browse now tells a reader "Overdue -- this deployment expects one
   * every 26 hours". 26 is the declared interval times a constant, and
   * without it on this panel the only honest answer to "where did 26
   * come from" is to read the source.
   */
  it('shows the expected sync interval', async () => {
    getDeploymentConfig.mockResolvedValue({ ...BODY, sync_interval_hours: 24 })
    render(<DeploymentConfig onSessionExpired={() => {}} />)

    expect(await screen.findByText('Expected sync interval')).toBeInTheDocument()
    expect(screen.getByText('every 24 hours')).toBeInTheDocument()
  })

  it('says so rather than guessing when the server did not report one', async () => {
    // An older server. "not reported" is the panel's standing word for
    // a setting it cannot see, and inventing 24 would make a
    // deployment look configured when it is only defaulted.
    render(<DeploymentConfig onSessionExpired={() => {}} />)

    expect(await screen.findByText('Expected sync interval')).toBeInTheDocument()
    expect(screen.queryByText(/every \d+ hours/)).toBeNull()
  })

  it('says whether classification labels decide field access', async () => {
    getDeploymentConfig.mockResolvedValue({ ...BODY, label_enforcement: true })
    render(<DeploymentConfig onSessionExpired={() => {}} />)

    const label = await screen.findByText('Classification labels decide field access')
    expect(label.parentElement).toHaveTextContent(/yes$/)
  })

  it('says where lineage events go, and never the service URL (R15)', async () => {
    getDeploymentConfig.mockResolvedValue({ ...BODY, lineage_service: true, lineage_namespace: 'acme' })
    render(<DeploymentConfig onSessionExpired={() => {}} />)

    const label = await screen.findByText('Lineage events')
    expect(label.parentElement).toHaveTextContent('lineage.jsonl and a lineage service (namespace acme)')
  })

  it('shows the per-question token budget, and none when unset (AL-10)', async () => {
    getDeploymentConfig.mockResolvedValue({ ...BODY, max_tokens_per_query: 50000 })
    const { unmount } = render(<DeploymentConfig onSessionExpired={() => {}} />)
    expect((await screen.findByText('Token budget per question')).parentElement).toHaveTextContent('50,000 tokens')
    unmount()

    getDeploymentConfig.mockResolvedValue({ ...BODY, max_tokens_per_query: null })
    render(<DeploymentConfig onSessionExpired={() => {}} />)
    expect((await screen.findByText('Token budget per question')).parentElement).toHaveTextContent(/none$/)
  })

  it('says how each silo writes numbers and dates (DEP-1)', async () => {
    getDeploymentConfig.mockResolvedValue({
      ...BODY,
      source_locales: { primary_sql: 'pt_BR', support_crm: null },
    })
    render(<DeploymentConfig onSessionExpired={() => {}} />)

    const label = await screen.findByText('Source number and date formats')
    expect(label.parentElement).toHaveTextContent('primary_sql: pt_BR, support_crm: machine formats only')
  })

  it('says which silos read Excel date serials (ZOO-22)', async () => {
    getDeploymentConfig.mockResolvedValue({
      ...BODY,
      source_locales: { primary_sql: null },
      excel_date_silos: ['primary_sql'],
    })
    render(<DeploymentConfig onSessionExpired={() => {}} />)

    const label = await screen.findByText('Source number and date formats')
    expect(label.parentElement).toHaveTextContent('primary_sql: machine formats only and Excel date serials')
  })

  it('says which tables are read by changed rows (R2)', async () => {
    getDeploymentConfig.mockResolvedValue({
      ...BODY,
      incremental_tables: { 'primary_sql.transactions': 'updated_at; full read every 7 days' },
    })
    render(<DeploymentConfig onSessionExpired={() => {}} />)

    const label = await screen.findByText('Tables read by changed rows')
    expect(label.parentElement).toHaveTextContent('primary_sql.transactions by updated_at; full read every 7 days')
  })

  it('says every table is read in full when none is declared (R2)', async () => {
    getDeploymentConfig.mockResolvedValue({ ...BODY, incremental_tables: {} })
    render(<DeploymentConfig onSessionExpired={() => {}} />)

    const label = await screen.findByText('Tables read by changed rows')
    expect(label.parentElement).toHaveTextContent('none (every table is read in full)')
  })

  it('says the file alone when no service is named', async () => {
    getDeploymentConfig.mockResolvedValue({ ...BODY, lineage_service: false })
    render(<DeploymentConfig onSessionExpired={() => {}} />)

    const label = await screen.findByText('Lineage events')
    expect(label.parentElement).toHaveTextContent('lineage.jsonl only (namespace elysium)')
  })
})

describe('putting an earlier version back (DEV_UI 13.7)', () => {
  /** Shaped as GET /admin/config-restore/{n} returns it. */
  const PREVIEW = {
    generation: 1,
    loaded_at: new Date().toISOString(),
    digest: 'now-digest',
    files: [
      { name: 'ontology_schema.yaml', diff: ['--- a', '+++ b', '-    group: People'] },
      {
        name: 'data_silos.yaml',
        diff: ['data_silos.yaml changes too. Its lines are not shown here: it holds where each source is.'],
      },
    ],
    impact: { widens: false, roles: [] },
    needs_approval: false,
    roles_in_store: true,
  }

  it('is offered once per configuration that differs from what runs now', async () => {
    // 3 runs now; 2 is the same files; 1 and 0 are one earlier
    // configuration, loaded twice -- offered once, on its newest row.
    getConfigHistory.mockResolvedValue(
      historyOf([
        [3, OTHER],
        [2, OTHER],
        [1, SAME],
        [0, SAME],
      ]),
    )
    render(<DeploymentConfig onSessionExpired={vi.fn()} />)
    const table = await screen.findByRole('table', { name: 'Configurations this deployment has run' })

    const offered = within(table).getAllByRole('button', { name: 'Put this version back' })
    expect(offered).toHaveLength(1)
    expect(offered[0]!.closest('tr')).toHaveTextContent(/^1/)
  })

  it('shows what goes back and says roles stay, then puts it back', async () => {
    getConfigHistory.mockResolvedValue(
      historyOf([
        [2, OTHER],
        [1, SAME],
      ]),
    )
    previewRestore.mockResolvedValue(PREVIEW)
    restoreGeneration.mockResolvedValue({ status: 'applied', to_generation: 9 })
    render(<DeploymentConfig onSessionExpired={vi.fn()} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Put this version back' }))

    expect(await screen.findByText('- group: People')).toBeInTheDocument()
    expect(screen.getByText(/data_silos.yaml changes too/)).toBeInTheDocument()
    expect(screen.getByText('Roles stay as they are')).toBeInTheDocument()
    expect(screen.getByText('No change to what anyone can see or do.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Put it back and reload' }))

    expect(await screen.findByText(/reloaded as generation 9/)).toBeInTheDocument()
    expect(restoreGeneration).toHaveBeenCalledWith(1, 'now-digest', null)
  })

  it('a widening one asks why and is proposed', async () => {
    getConfigHistory.mockResolvedValue(
      historyOf([
        [2, OTHER],
        [1, SAME],
      ]),
    )
    previewRestore.mockResolvedValue({ ...PREVIEW, impact: { widens: true, roles: [] }, needs_approval: true })
    restoreGeneration.mockResolvedValue({ status: 'waiting', proposal_id: 'p1' })
    render(<DeploymentConfig onSessionExpired={vi.fn()} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Put this version back' }))
    const propose = await screen.findByRole('button', { name: 'Propose for approval' })

    expect(propose).toBeDisabled()
    fireEvent.change(screen.getByLabelText(/Why/), { target: { value: 'the old labels were right' } })
    fireEvent.click(propose)

    expect(await screen.findByText('Waiting for approval')).toBeInTheDocument()
    expect(restoreGeneration).toHaveBeenCalledWith(1, 'now-digest', 'the old labels were right')
  })

  it('a refusal is said, with nothing to press', async () => {
    getConfigHistory.mockResolvedValue(
      historyOf([
        [2, OTHER],
        [1, SAME],
      ]),
    )
    const { ApiError } = await import('@elysium/shell-api/api')
    previewRestore.mockRejectedValue(new ApiError(400, 'A restore does not change a data type.'))
    render(<DeploymentConfig onSessionExpired={vi.fn()} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Put this version back' }))

    expect(await screen.findByText(/does not change a data type/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Put it back|Propose/ })).not.toBeInTheDocument()
  })
})
