/**
 * The simulator's control panel (sim/panel/web, BLOCKING.md item 3, step
 * 2.3): what it shows in each phase, what it sends, and what it says when
 * the panel's server refuses. Here rather than beside its source because
 * it runs with this page's test tools, which the simulator does not carry.
 * The server's side is tests/integration/test_simulator_panel.py.
 */
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const addonRequest = vi.fn()
vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return { ...actual, addonRequest: (...args: unknown[]) => addonRequest(...args) }
})
import SimulatorPanel, { type PanelState } from '@simulator/panel/SimulatorPanel'
import type { WorldSchema } from '@simulator/panel/SchemaChanges'

const PACKS = [
  { name: 'probe', description: "A world built to be read by somebody else's client." },
  { name: 'retail', description: 'An independent homeware shop.' },
]

function state(over: Partial<PanelState> = {}): PanelState {
  return {
    phase: 'stopped',
    world: null,
    problem: null,
    directory: '/srv/sim/world',
    resumable: false,
    pack: null,
    packs: PACKS,
    connections: null,
    may_operate: true,
    ...over,
  }
}

const RUNNING = state({
  phase: 'running',
  world: {
    pack: 'probe',
    clock: '2026-01-02T07:00:00+00:00',
    elapsed_days: 1.29,
    paused: false,
    following: true,
    compression: 3600,
    silos: { ops: { kind: 'postgresql', state: 'up' }, drop: { kind: 'csv_folder', state: 'out' } },
  },
  connections: {
    pack: 'probe',
    silos: {
      ops: { kind: 'postgresql', host: '127.0.0.1', port: 54321, user: 'reader' },
      drop: { kind: 'csv_folder', path: '/srv/sim/world/drop' },
    },
  },
})

/** As the world's `schema` command answers: which changes break is its
 *  word, from each change's class (sim/simulator/control.py). */
const SCHEMA: WorldSchema = {
  silos: {
    ops: {
      kind: 'postgresql',
      tables: {
        readings: [
          { name: 'reading_id', type: 'text', nullable: false, primary_key: true },
          { name: 'quantity', type: 'integer', nullable: false, primary_key: false },
          { name: 'note', type: 'text', nullable: true, primary_key: false },
        ],
        sites: [{ name: 'site_id', type: 'text', nullable: false, primary_key: true }],
      },
      history: [
        {
          at: '2026-01-02T03:00:00+00:00',
          operation: 'AddColumn',
          detail: 'added readings.note (text)',
          breaking: false,
        },
      ],
    },
    shop: { kind: 'mariadb', tables: { orders: [] }, history: [] },
  },
  operations: {
    add_column: false,
    drop_column: true,
    rename_column: true,
    change_column_type: true,
    rescale_column: true,
    add_table: false,
    drop_table: true,
    rename_table: true,
  },
}

/** The state the server answers with, and every POST answered with {}. */
function serve(shown: PanelState, schema: WorldSchema = SCHEMA) {
  addonRequest.mockImplementation((_module: string, path: string, options?: { method?: string }) => {
    if (options?.method === 'POST') return Promise.resolve({})
    if (path === 'log') return Promise.resolve({ lines: ['Following at 3600x.'] })
    if (path === 'schema') return Promise.resolve(schema)
    return Promise.resolve(shown)
  })
}

const sent = () =>
  addonRequest.mock.calls
    .filter(([, , options]) => (options as { method?: string } | undefined)?.method === 'POST')
    .map(([module, path, options]) => [module, path, (options as { body: unknown }).body])

/** Click, then wait for the change to be answered: the panel disables its
 *  buttons while one is under way, so a second press waits for the first. */
async function press(button: HTMLElement) {
  const before = sent().length
  fireEvent.click(button)
  await waitFor(() => expect(sent().length).toBe(before + 1))
  await waitFor(() => expect(button).toBeEnabled())
}

beforeEach(() => addonRequest.mockReset())

describe('the simulator panel', () => {
  it('starts a world from the pack, days and speed chosen', async () => {
    serve(state())
    render(<SimulatorPanel onSessionExpired={() => {}} />)

    expect(await screen.findByText('No world here. Choose a pack and start one.')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Pack'), { target: { value: 'retail' } })
    expect(screen.getByText('An independent homeware shop.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Start' }))

    await waitFor(() => expect(sent()).toEqual([['simulator', 'start', { pack: 'retail', days: 7, compression: 60 }]]))
  })

  it('offers to resume a stopped world, and discards one only on a second click', async () => {
    serve(state({ resumable: true }))
    render(<SimulatorPanel onSessionExpired={() => {}} />)

    fireEvent.click(await screen.findByRole('button', { name: 'Resume' }))
    await waitFor(() =>
      expect(sent()[0]).toEqual(['simulator', 'start', { pack: 'probe', resume: true, compression: 60 }]),
    )

    fireEvent.click(screen.getByRole('button', { name: 'Discard…' }))
    expect(sent()).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: 'Discard its databases for good' }))
    await waitFor(() => expect(sent()[1]).toEqual(['simulator', 'discard', {}]))
  })

  it('runs a world: its clock and pace, pause, move on, speed and stop', async () => {
    serve(RUNNING)
    render(<SimulatorPanel onSessionExpired={() => {}} />)

    expect(
      await screen.findByText(/probe: .* 1\.29 days in; running at 3,600 simulated seconds a second\./),
    ).toBeInTheDocument()
    await press(screen.getByRole('button', { name: 'Pause' }))
    fireEvent.change(screen.getByLabelText('How far to move on'), { target: { value: '6h' } })
    await press(screen.getByRole('button', { name: 'Move on' }))
    await press(screen.getByRole('button', { name: 'Stop' }))

    await waitFor(() =>
      expect(sent()).toEqual([
        ['simulator', 'command', { command: 'pause' }],
        ['simulator', 'command', { command: 'advance', duration: '6h' }],
        ['simulator', 'stop', {}],
      ]),
    )
  })

  it('lists each database with how to connect, and takes one offline or brings it back', async () => {
    serve(RUNNING)
    render(<SimulatorPanel onSessionExpired={() => {}} />)

    const table = within(await screen.findByRole('table', { name: 'Its databases' }))
    const ops = table.getByText('ops').closest('tr')!
    expect(ops).toHaveTextContent('54321')
    expect(ops).toHaveTextContent('reader')
    await press(within(ops).getByRole('button', { name: 'Take offline' }))
    const drop = table.getByText('drop').closest('tr')!
    await press(within(drop).getByRole('button', { name: 'Restore' }))

    await waitFor(() =>
      expect(sent()).toEqual([
        ['simulator', 'command', { command: 'outage', silo: 'ops' }],
        ['simulator', 'command', { command: 'restore', silo: 'drop' }],
      ]),
    )
  })

  it('says what the server refused', async () => {
    serve(state())
    render(<SimulatorPanel onSessionExpired={() => {}} />)
    await screen.findByRole('button', { name: 'Start' })
    addonRequest.mockImplementationOnce(() => Promise.reject(new Error('a world is already busy in /srv/sim/world')))

    fireEvent.click(screen.getByRole('button', { name: 'Start' }))

    expect(await screen.findByText('a world is already busy in /srv/sim/world')).toBeInTheDocument()
  })

  it('shows the world but offers no controls to someone who may not operate it', async () => {
    serve({ ...RUNNING, may_operate: false })
    render(<SimulatorPanel onSessionExpired={() => {}} />)

    expect(await screen.findByText(/changing it needs the Simulator's operate permission/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Stop' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Take offline' })).not.toBeInTheDocument()
  })

  it('lists the schema changes made so far, additive or breaking', async () => {
    serve(RUNNING)
    render(<SimulatorPanel onSessionExpired={() => {}} />)

    const history = within(await screen.findByRole('table', { name: 'Schema changes so far' }))
    const row = history.getByText('added readings.note (text)').closest('tr')!
    expect(row).toHaveTextContent('ops')
    expect(row).toHaveTextContent('additive')
  })

  it("adds a column in one click, sending the change in the pack's own words", async () => {
    serve(RUNNING)
    render(<SimulatorPanel onSessionExpired={() => {}} />)

    fireEvent.change(await screen.findByLabelText('New column'), { target: { value: 'remark' } })
    fireEvent.change(screen.getByLabelText('Length'), { target: { value: '40' } })
    await press(screen.getByRole('button', { name: 'Apply' }))

    expect(sent()).toEqual([
      [
        'simulator',
        'command',
        {
          command: 'drift',
          operation: 'add_column',
          table: 'ops.readings',
          column: 'remark',
          type: 'text',
          length: 40,
        },
      ],
    ])
  })

  it('asks twice before a breaking change, and a different choice disarms it', async () => {
    serve(RUNNING)
    render(<SimulatorPanel onSessionExpired={() => {}} />)

    fireEvent.change(await screen.findByLabelText('Change'), { target: { value: 'drop_column' } })
    fireEvent.change(screen.getByLabelText('Column'), { target: { value: 'note' } })
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }))
    expect(sent()).toEqual([])
    expect(screen.getByText(/Only discarding the world goes back/)).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Column'), { target: { value: 'quantity' } })
    expect(screen.getByRole('button', { name: 'Apply' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }))
    await press(screen.getByRole('button', { name: 'Apply it: this cannot be undone' }))

    expect(sent()).toEqual([
      [
        'simulator',
        'command',
        { command: 'drift', operation: 'drop_column', table: 'ops.readings', column: 'quantity' },
      ],
    ])
  })

  it('rescales only a column that holds numbers, and asks twice', async () => {
    serve(RUNNING)
    render(<SimulatorPanel onSessionExpired={() => {}} />)

    fireEvent.change(await screen.findByLabelText('Change'), { target: { value: 'rescale_column' } })
    const offered = within(screen.getByLabelText('Column'))
      .getAllByRole('option')
      .map((option) => option.textContent)
    expect(offered).toEqual(['quantity (integer)'])

    // Breaking by the world's word, though nothing is removed: every
    // value means something else after it. So it asks twice.
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }))
    expect(sent()).toEqual([])
    await press(screen.getByRole('button', { name: 'Apply it: this cannot be undone' }))
    expect(sent()).toEqual([
      [
        'simulator',
        'command',
        { command: 'drift', operation: 'rescale_column', table: 'ops.readings', column: 'quantity', factor: '100' },
      ],
    ])
  })

  it('adds a table with a text key', async () => {
    serve(RUNNING)
    render(<SimulatorPanel onSessionExpired={() => {}} />)

    fireEvent.change(await screen.findByLabelText('Change'), { target: { value: 'add_table' } })
    fireEvent.change(screen.getByLabelText('New table'), { target: { value: 'visits' } })
    await press(screen.getByRole('button', { name: 'Apply' }))

    expect(sent()).toEqual([
      [
        'simulator',
        'command',
        {
          command: 'drift',
          operation: 'add_table',
          table: 'ops.visits',
          columns: { id: { type: 'text', length: 64, primary_key: true, nullable: false } },
        },
      ],
    ])
  })

  it('shows what has changed, but offers no change, to someone who may not operate it', async () => {
    serve({ ...RUNNING, may_operate: false })
    render(<SimulatorPanel onSessionExpired={() => {}} />)

    expect(await screen.findByRole('table', { name: 'Schema changes so far' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Apply' })).not.toBeInTheDocument()
  })

  it('says a busy world is building or tidying up, and offers nothing to press', async () => {
    serve(state({ phase: 'busy' }))
    render(<SimulatorPanel onSessionExpired={() => {}} />)

    expect(await screen.findByText(/Building, catching up on its first days, or tidying up/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Start' })).not.toBeInTheDocument()
  })

  it('reads the world again while open, so a world found again after Elysium was offline shows', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    serve(state())
    render(<SimulatorPanel onSessionExpired={() => {}} />)
    await screen.findByRole('button', { name: 'Start' })
    serve(RUNNING)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100)
    })

    expect(screen.getByRole('button', { name: 'Stop' })).toBeInTheDocument()
    vi.useRealTimers()
  })
})
