import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'

const getDeploymentConfig = vi.fn()
const getConfigHistory = vi.fn()
const getConfigDiff = vi.fn()

vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return {
    ...actual,
    getDeploymentConfig: () => getDeploymentConfig(),
    getConfigHistory: () => getConfigHistory(),
    getConfigDiff: (older: number, newer: number) => getConfigDiff(older, newer),
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
      ingest_undeclared_columns: false,
    })
    render(<DeploymentConfig onSessionExpired={() => {}} />)

    expect(await screen.findByText('On type mismatch')).toBeInTheDocument()
    expect(screen.getByText('quarantine')).toBeInTheDocument()
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
})
