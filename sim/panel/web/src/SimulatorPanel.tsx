/**
 * THE SIMULATOR'S CONTROL PANEL (BLOCKING.md items 11 and 3, step 2.3):
 * start a world from a pack, or resume the one stopped here; run it at a
 * speed; pause it, move it on, take a database offline and bring it back;
 * change its schema (SchemaChanges.tsx); copy each database's connection
 * details; stop it.
 *
 * EVERYTHING GOES THROUGH THE PANEL'S OWN SERVER (sim/panel/server.py),
 * reached through Elysium's proxy (`addonRequest`). The world itself runs
 * on its own: it carries on when Elysium is offline, and this page finds
 * it again when Elysium is back -- so the page holds nothing about the
 * world but what it last read, and reads again every POLL_MS.
 */
import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { Button, Callout, ControlGroup, FormGroup, HTMLSelect, HTMLTable, NumericInput } from '@blueprintjs/core'
import { addonRequest, getErrorMessage, handleIfSessionExpired } from '@elysium/shell-api/api'
import AsyncPanel from '@elysium/shell-api/components/AsyncPanel'
import Page from '@elysium/shell-api/components/Page'
import StatusTag, { type TagState } from '@elysium/shell-api/components/StatusTag'
import SchemaChanges from './SchemaChanges'

const MODULE = 'simulator'
const POLL_MS = 2000

interface WorldStatus {
  pack: string
  clock: string
  elapsed_days: number
  paused: boolean
  following: boolean
  compression: number | null
  silos: Record<string, { kind: string; state: 'up' | 'down' | 'out' }>
}

export interface PanelState {
  phase: 'running' | 'busy' | 'stopped' | 'not answering'
  world: WorldStatus | null
  problem: string | null
  directory: string
  resumable: boolean
  /** The pack a stopped world here was built from, which resuming needs. */
  pack: string | null
  packs: { name: string; description: string }[]
  connections: { pack: string; silos: Record<string, Record<string, unknown>> } | null
  may_operate: boolean
}

const PHASE_TAG: Record<PanelState['phase'], TagState> = {
  running: 'granted',
  busy: 'pending',
  stopped: 'neutral',
  'not answering': 'refused',
}

const SILO_TAG: Record<string, TagState> = { up: 'granted', down: 'refused', out: 'pending' }

const ADVANCES = ['1h', '6h', '1d', '7d']

function describe(state: PanelState): string {
  switch (state.phase) {
    case 'running': {
      const world = state.world!
      const clock = new Date(world.clock).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
      const pace = world.paused
        ? 'paused'
        : world.following && world.compression !== null
          ? `running at ${world.compression.toLocaleString()} simulated seconds a second`
          : 'running'
      return `${world.pack}: ${clock} in the world, ${world.elapsed_days.toLocaleString()} days in; ${pace}.`
    }
    case 'busy':
      return 'Building, catching up on its first days, or tidying up after a stop. This takes a few seconds to a minute.'
    case 'not answering':
      return `A world was left here without tidying up: ${state.problem ?? 'it does not answer'}. Discard it to clean up what it left running.`
    default:
      return state.resumable
        ? 'Stopped. Resume it where its clock left off, or discard it to start another.'
        : 'No world here. Choose a pack and start one.'
  }
}

export default function SimulatorPanel({ onSessionExpired }: { onSessionExpired: () => void }) {
  const [state, setState] = useState<PanelState | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [refused, setRefused] = useState<string | null>(null)
  const [acting, setActing] = useState(false)

  const read = useCallback(
    () =>
      addonRequest<PanelState>(MODULE, 'state').then(
        (got) => {
          setState(got)
          setError(null)
        },
        (err: unknown) => {
          handleIfSessionExpired(err, onSessionExpired)
          setError(getErrorMessage(err))
        },
      ),
    [onSessionExpired],
  )

  useEffect(() => {
    void read()
    const timer = window.setInterval(() => void read(), POLL_MS)
    return () => window.clearInterval(timer)
  }, [read])

  /** Every change: sent, then the state read again, a refusal said. */
  const act = useCallback(
    (path: string, body: unknown = {}) => {
      setActing(true)
      setRefused(null)
      addonRequest(MODULE, path, { method: 'POST', body })
        .catch((err: unknown) => {
          handleIfSessionExpired(err, onSessionExpired)
          setRefused(getErrorMessage(err))
        })
        .finally(() => {
          setActing(false)
          void read()
        })
    },
    [read, onSessionExpired],
  )

  return (
    <Page
      title="Simulator"
      description="A simulated business, as real databases. It runs on its own: it carries on while Elysium is offline, and this page finds it again."
    >
      <AsyncPanel error={error} data={state}>
        {(shown) => (
          <div className="simulator-panel">
            <p className="simulator-panel__status">
              <StatusTag state={PHASE_TAG[shown.phase]}>{shown.phase}</StatusTag> {describe(shown)}
            </p>
            {refused === null ? null : (
              <Callout intent="danger" className="simulator-panel__refused">
                {refused}
              </Callout>
            )}
            {shown.may_operate ? (
              <Controls state={shown} acting={acting} act={act} />
            ) : (
              <p>You may see the world; changing it needs the Simulator&apos;s operate permission.</p>
            )}
            {shown.phase === 'running' && shown.world !== null ? (
              <>
                <Databases state={shown} acting={acting} act={act} />
                <SchemaChanges
                  mayOperate={shown.may_operate}
                  acting={acting}
                  act={act}
                  onSessionExpired={onSessionExpired}
                />
              </>
            ) : null}
            <Log />
            <p className="simulator-panel__where">The world lives in {shown.directory}.</p>
          </div>
        )}
      </AsyncPanel>
    </Page>
  )
}

type Act = (path: string, body?: unknown) => void

function Controls({ state, acting, act }: { state: PanelState; acting: boolean; act: Act }) {
  if (state.phase === 'running' && state.world !== null)
    return <Running world={state.world} acting={acting} act={act} />
  if (state.phase === 'busy') return null
  if (state.phase === 'not answering') return <Discard acting={acting} act={act} />
  return state.resumable ? (
    <Resume state={state} acting={acting} act={act} />
  ) : (
    <Start packs={state.packs} acting={acting} act={act} />
  )
}

function Row({ children, centred = false }: { children: ReactNode; centred?: boolean }) {
  return (
    <div className={centred ? 'simulator-panel__row simulator-panel__row--centred' : 'simulator-panel__row'}>
      {children}
    </div>
  )
}

function Start({ packs, acting, act }: { packs: PanelState['packs']; acting: boolean; act: Act }) {
  const [pack, setPack] = useState(packs[0]?.name ?? '')
  const [days, setDays] = useState(7)
  const [compression, setCompression] = useState(60)
  const chosen = packs.find((p) => p.name === pack)
  return (
    <section aria-label="Start a world">
      <Row>
        <FormGroup label="Pack" labelFor="simulator-pack" helperText={chosen?.description}>
          <HTMLSelect
            id="simulator-pack"
            value={pack}
            onChange={(event) => setPack(event.currentTarget.value)}
            options={packs.map((p) => p.name)}
          />
        </FormGroup>
        <FormGroup label="Days to build first" labelFor="simulator-days">
          <NumericInput id="simulator-days" min={0} max={366} value={days} onValueChange={setDays} />
        </FormGroup>
        <FormGroup label="Speed (simulated seconds a second)" labelFor="simulator-speed">
          <NumericInput id="simulator-speed" min={1} value={compression} onValueChange={setCompression} />
        </FormGroup>
      </Row>
      <Button
        intent="primary"
        icon="play"
        disabled={acting || pack === ''}
        onClick={() => act('start', { pack, days, compression })}
      >
        Start
      </Button>
    </section>
  )
}

function Resume({ state, acting, act }: { state: PanelState; acting: boolean; act: Act }) {
  const [compression, setCompression] = useState(60)
  const pack = state.pack ?? state.packs[0]?.name ?? ''
  return (
    <section aria-label="Resume the world">
      <p>
        Built from <strong>{pack}</strong>.
      </p>
      <Row>
        <FormGroup label="Speed (simulated seconds a second)" labelFor="simulator-speed">
          <NumericInput id="simulator-speed" min={1} value={compression} onValueChange={setCompression} />
        </FormGroup>
      </Row>
      <Row>
        <Button
          intent="primary"
          icon="play"
          disabled={acting || pack === ''}
          onClick={() => act('start', { pack, resume: true, compression })}
        >
          Resume
        </Button>
        <Discard acting={acting} act={act} />
      </Row>
    </section>
  )
}

/** Two clicks: the first says what it does, the second does it. A world's
 *  databases are gone once discarded. */
function Discard({ acting, act }: { acting: boolean; act: Act }) {
  const [armed, setArmed] = useState(false)
  return armed ? (
    <Button intent="danger" icon="trash" disabled={acting} onClick={() => act('discard')}>
      Discard its databases for good
    </Button>
  ) : (
    <Button variant="minimal" icon="trash" disabled={acting} onClick={() => setArmed(true)}>
      Discard…
    </Button>
  )
}

function Running({ world, acting, act }: { world: WorldStatus; acting: boolean; act: Act }) {
  const [advance, setAdvance] = useState('1d')
  const [compression, setCompression] = useState(world.compression ?? 60)
  return (
    <section aria-label="Run the world">
      <Row centred>
        {world.paused ? (
          <Button icon="play" disabled={acting} onClick={() => act('command', { command: 'resume' })}>
            Resume the clock
          </Button>
        ) : (
          <Button icon="pause" disabled={acting} onClick={() => act('command', { command: 'pause' })}>
            Pause
          </Button>
        )}
        <HTMLSelect
          aria-label="How far to move on"
          value={advance}
          onChange={(event) => setAdvance(event.currentTarget.value)}
          options={ADVANCES}
        />
        <Button
          icon="fast-forward"
          disabled={acting}
          onClick={() => act('command', { command: 'advance', duration: advance })}
        >
          Move on
        </Button>
        {world.following ? (
          <ControlGroup>
            <NumericInput
              aria-label="Speed, in simulated seconds a second"
              buttonPosition="none"
              min={1}
              value={compression}
              onValueChange={setCompression}
            />
            <Button disabled={acting} onClick={() => act('command', { command: 'speed', compression })}>
              Set speed
            </Button>
          </ControlGroup>
        ) : null}
        <Button intent="danger" icon="stop" disabled={acting} onClick={() => act('stop')}>
          Stop
        </Button>
      </Row>
    </section>
  )
}

function details(silo: Record<string, unknown>): [string, string][] {
  return Object.entries(silo)
    .filter(([key]) => key !== 'kind')
    .map(([key, value]) => [key, typeof value === 'string' ? value : JSON.stringify(value)])
}

function Databases({ state, acting, act }: { state: PanelState; acting: boolean; act: Act }) {
  const silos = state.world!.silos
  const [copied, setCopied] = useState<string | null>(null)
  const copy = (name: string, text: string) => {
    void navigator.clipboard?.writeText(text).then(() => setCopied(name))
  }
  return (
    <section aria-label="Databases">
      <h2 className="simulator-panel__heading">Its databases</h2>
      <HTMLTable compact className="simulator-panel__silos" aria-label="Its databases">
        <thead>
          <tr>
            <th>Database</th>
            <th>Kind</th>
            <th>State</th>
            <th>How to connect</th>
            <th aria-label="Actions" />
          </tr>
        </thead>
        <tbody>
          {Object.entries(silos).map(([name, silo]) => {
            const connection = state.connections?.silos[name] ?? {}
            const pairs = details(connection)
            return (
              <tr key={name}>
                <td>{name}</td>
                <td>{silo.kind}</td>
                <td>
                  <StatusTag state={SILO_TAG[silo.state] ?? 'neutral'}>{silo.state}</StatusTag>
                </td>
                <td>
                  <dl className="simulator-panel__connection">
                    {pairs.map(([key, value]) => (
                      <div key={key}>
                        <dt>{key}</dt>
                        <dd>{value}</dd>
                      </div>
                    ))}
                  </dl>
                  <Button
                    small
                    variant="minimal"
                    icon="duplicate"
                    onClick={() => copy(name, JSON.stringify(connection, null, 2))}
                  >
                    {copied === name ? 'Copied' : 'Copy'}
                  </Button>
                </td>
                <td>
                  {state.may_operate ? (
                    silo.state === 'out' ? (
                      <Button
                        small
                        disabled={acting}
                        onClick={() => act('command', { command: 'restore', silo: name })}
                      >
                        Restore
                      </Button>
                    ) : (
                      <Button small disabled={acting} onClick={() => act('command', { command: 'outage', silo: name })}>
                        Take offline
                      </Button>
                    )
                  ) : null}
                </td>
              </tr>
            )
          })}
        </tbody>
      </HTMLTable>
    </section>
  )
}

function Log() {
  const [open, setOpen] = useState(false)
  const [lines, setLines] = useState<string[]>([])
  useEffect(() => {
    if (!open) return
    let live = true
    const read = () =>
      addonRequest<{ lines: string[] }>(MODULE, 'log').then(
        (got) => live && setLines(got.lines),
        () => undefined,
      )
    void read()
    const timer = window.setInterval(() => void read(), POLL_MS)
    return () => {
      live = false
      window.clearInterval(timer)
    }
  }, [open])
  return (
    <section aria-label="Run log">
      <Button variant="minimal" icon="document" aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? 'Hide its log' : 'Its log'}
      </Button>
      {open ? (
        <pre className="simulator-panel__log" aria-label="Log of the run">
          {lines.length === 0 ? 'Nothing logged yet.' : lines.join('\n')}
        </pre>
      ) : null}
    </section>
  )
}
