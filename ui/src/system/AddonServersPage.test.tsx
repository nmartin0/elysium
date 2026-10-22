import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AddonServer } from '@elysium/shell-api/api'

const getAddonServers = vi.fn<() => Promise<AddonServer[]>>()
const getAddonServerLog = vi.fn<(id: string) => Promise<string[]>>()
const restartAddonServer = vi.fn<(id: string) => Promise<void>>()
vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return {
    ...actual,
    getAddonServers: () => getAddonServers(),
    getAddonServerLog: (id: string) => getAddonServerLog(id),
    restartAddonServer: (id: string) => restartAddonServer(id),
  }
})
import AddonServersPage from './AddonServersPage'

const NOW = Date.now() / 1000
const server = (over: Partial<AddonServer> = {}): AddonServer => ({
  id: 'simulator',
  name: 'Simulator',
  enabled: true,
  state: 'running',
  since: NOW - 30,
  restarts: 0,
  last_exit: null,
  next_start_at: null,
  ...over,
})

beforeEach(() => {
  getAddonServers.mockReset()
  getAddonServerLog.mockReset()
  restartAddonServer.mockReset()
})

describe('AddonServersPage', () => {
  it('shows each server, its state as a word, and what that means', async () => {
    getAddonServers.mockResolvedValue([
      server(),
      server({
        id: 'helio',
        name: 'Heliograph',
        state: 'backing-off',
        restarts: 3,
        last_exit: 2,
        next_start_at: NOW + 8,
      }),
    ])

    render(<AddonServersPage onSessionExpired={() => {}} />)

    const [, first, second] = await screen.findAllByRole('row')
    expect(within(first!).getByText('Simulator')).toBeInTheDocument()
    expect(within(first!).getByText('running')).toBeInTheDocument()
    expect(within(first!).getByText('just now')).toBeInTheDocument()
    expect(within(second!).getByText('backing-off')).toBeInTheDocument()
    expect(
      within(second!).getByText(/exited with status 2; started again in [78] s\. Its log says why\./),
    ).toBeInTheDocument()
  })

  it('says a turned-off module is not run, and offers no restart for it', async () => {
    getAddonServers.mockResolvedValue([server({ enabled: false, state: 'stopped' })])

    render(<AddonServersPage onSessionExpired={() => {}} />)

    expect(await screen.findByText('Its module is turned off, so its server is not run.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Restart' })).toBeDisabled()
  })

  it('restarts one when asked, and reads the states again', async () => {
    getAddonServers.mockResolvedValue([server()])
    restartAddonServer.mockResolvedValue()
    render(<AddonServersPage onSessionExpired={() => {}} />)

    fireEvent.click(await screen.findByRole('button', { name: 'Restart' }))

    expect(restartAddonServer).toHaveBeenCalledWith('simulator')
    expect(screen.getByText('Restarting…')).toBeInTheDocument()
    await waitFor(() => expect(getAddonServers.mock.calls.length).toBeGreaterThanOrEqual(2))
  })

  it('says why a restart was refused', async () => {
    getAddonServers.mockResolvedValue([server()])
    restartAddonServer.mockRejectedValue(new Error('Needs manage:deployment'))
    render(<AddonServersPage onSessionExpired={() => {}} />)

    fireEvent.click(await screen.findByRole('button', { name: 'Restart' }))

    expect(await screen.findByText('Needs manage:deployment')).toBeInTheDocument()
  })

  it("opens a server's log beneath it, and closes it again", async () => {
    getAddonServers.mockResolvedValue([server()])
    getAddonServerLog.mockResolvedValue(['[elysium] started, pid 7, port 8123', 'listening'])
    render(<AddonServersPage onSessionExpired={() => {}} />)

    fireEvent.click(await screen.findByRole('button', { name: 'Log' }))

    expect(await screen.findByLabelText('Log of simulator')).toHaveTextContent('started, pid 7, port 8123')
    expect(getAddonServerLog).toHaveBeenCalledWith('simulator')
    fireEvent.click(screen.getByRole('button', { name: 'Hide log' }))
    expect(screen.queryByLabelText('Log of simulator')).not.toBeInTheDocument()
  })

  it('says plainly when no module has a server', async () => {
    getAddonServers.mockResolvedValue([])

    render(<AddonServersPage onSessionExpired={() => {}} />)

    expect(await screen.findByText('No add-on servers')).toBeInTheDocument()
  })

  it('reads the states again while it is open', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    getAddonServers.mockResolvedValue([server()])
    render(<AddonServersPage onSessionExpired={() => {}} />)
    await screen.findByText('Simulator')
    const before = getAddonServers.mock.calls.length

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100)
    })

    expect(getAddonServers.mock.calls.length).toBe(before + 1)
    vi.useRealTimers()
  })
})
