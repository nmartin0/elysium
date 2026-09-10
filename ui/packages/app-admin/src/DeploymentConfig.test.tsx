import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

const getDeploymentConfig = vi.fn()

vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return { ...actual, getDeploymentConfig: () => getDeploymentConfig() }
})

const { default: DeploymentConfig } = await import('./DeploymentConfig')

const BODY = {
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
