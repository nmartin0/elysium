import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

const getDeploymentConfig = vi.fn()

vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return { ...actual, getDeploymentConfig: () => getDeploymentConfig() }
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
