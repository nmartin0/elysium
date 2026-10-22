/**
 * ADD-ON SERVERS (BLOCKING.md item 3, step 2.2): each module that brings a
 * server of its own -- the simulator's, one day Heliograph's -- and how it
 * is doing. Elysium starts these, watches them and restarts one that
 * fails (api/addon_servers.py); this is where a person sees that
 * happening, reads the server's log, and restarts one by hand.
 *
 * ELYSIUM'S, NOT THE SHELL'S: the shell knows modules and their pages;
 * that a module may have a server is Elysium's contract with its add-ons.
 * So this page sits in the System sub-app (ui/src/system) beside the
 * shell's own Modules page rather than in @shell/core.
 *
 * LIVE WHILE OPEN: read again every POLL_MS, because the states it shows
 * -- starting, backing off, restarted -- change in seconds, and a person
 * who just pressed Restart is watching for exactly that.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Button, HTMLTable } from '@blueprintjs/core'
import {
  getAddonServerLog,
  getAddonServers,
  getErrorMessage,
  handleIfSessionExpired,
  restartAddonServer,
  type AddonServer,
} from '@elysium/shell-api/api'
import AsyncPanel from '@elysium/shell-api/components/AsyncPanel'
import EmptyState from '@elysium/shell-api/components/EmptyState'
import Page from '@elysium/shell-api/components/Page'
import StatusTag, { type TagState } from '@elysium/shell-api/components/StatusTag'
import { formatTimestamp } from '@elysium/shell-api/format'

const POLL_MS = 2000

const TAG: Record<AddonServer['state'], TagState> = {
  running: 'granted',
  starting: 'pending',
  'backing-off': 'refused',
  stopping: 'pending',
  stopped: 'neutral',
  'not started': 'neutral',
}

/** What a state means, said to someone deciding whether to act. */
function explain(addon: AddonServer, now: Date): string {
  if (!addon.enabled) return 'Its module is turned off, so its server is not run.'
  switch (addon.state) {
    case 'running':
      return addon.restarts > 0
        ? `Running, after ${addon.restarts} restart${addon.restarts === 1 ? '' : 's'}.`
        : 'Running.'
    case 'starting':
      return 'Started, and not yet answering its health check.'
    case 'backing-off': {
      const exit = addon.last_exit === null ? 'It stopped answering' : `It exited with status ${addon.last_exit}`
      const wait =
        addon.next_start_at === null
          ? ''
          : `; started again in ${Math.max(0, Math.round(addon.next_start_at - now.getTime() / 1000))} s`
      return `${exit}${wait}. Its log says why.`
    }
    case 'stopping':
      return 'Being stopped.'
    case 'stopped':
      return 'Stopped.'
    default:
      return 'Not started yet: Elysium starts it within a second of loading.'
  }
}

function since(addon: AddonServer, now: Date): string {
  return addon.since === null ? '' : formatTimestamp(new Date(addon.since * 1000).toISOString(), now)
}

function Log({ id }: { id: string }) {
  const [lines, setLines] = useState<string[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const box = useRef<HTMLPreElement>(null)
  // THE END IS THE NEWS: each read shows the latest lines, as `tail -f`.
  useEffect(() => {
    if (box.current !== null) box.current.scrollTop = box.current.scrollHeight
  }, [lines])
  useEffect(() => {
    let live = true
    const read = () =>
      getAddonServerLog(id).then(
        (got) => live && (setLines(got), setError(null)),
        (err: unknown) => live && setError(getErrorMessage(err)),
      )
    void read()
    const timer = window.setInterval(() => void read(), POLL_MS)
    return () => {
      live = false
      window.clearInterval(timer)
    }
  }, [id])
  return (
    <AsyncPanel error={error} data={lines}>
      {(shown) =>
        shown.length === 0 ? (
          <p className="addon-servers__log-empty">Nothing in its log yet.</p>
        ) : (
          <pre ref={box} className="addon-servers__log" aria-label={`Log of ${id}`}>
            {shown.join('\n')}
          </pre>
        )
      }
    </AsyncPanel>
  )
}

export default function AddonServersPage({ onSessionExpired }: { onSessionExpired: () => void }) {
  const [addons, setAddons] = useState<AddonServer[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const [asked, setAsked] = useState<Record<string, string>>({})
  const [now, setNow] = useState(() => new Date())

  const read = useCallback(
    () =>
      getAddonServers().then(
        (got) => {
          setAddons(got)
          setError(null)
          setNow(new Date())
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

  const restart = (id: string) => {
    setAsked((before) => ({ ...before, [id]: 'Restarting…' }))
    restartAddonServer(id).then(
      () => void read(),
      (err: unknown) => setAsked((before) => ({ ...before, [id]: getErrorMessage(err) })),
    )
  }

  return (
    <Page
      title="Add-on servers"
      description="Modules that bring a server of their own. Elysium starts each, restarts one that fails, and stops them when it stops."
    >
      <AsyncPanel error={error} data={addons}>
        {(shown) =>
          shown.length === 0 ? (
            <EmptyState
              icon="console"
              title="No add-on servers"
              reason="No module this deployment lists declares a server of its own."
            />
          ) : (
            <HTMLTable className="addon-servers" compact>
              <thead>
                <tr>
                  <th>Add-on</th>
                  <th>State</th>
                  <th>Since</th>
                  <th>What it means</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {shown.map((addon) => (
                  <AddonRow
                    key={addon.id}
                    addon={addon}
                    now={now}
                    asked={asked[addon.id]}
                    logOpen={open === addon.id}
                    onLog={() => setOpen(open === addon.id ? null : addon.id)}
                    onRestart={() => restart(addon.id)}
                  />
                ))}
              </tbody>
            </HTMLTable>
          )
        }
      </AsyncPanel>
    </Page>
  )
}

function AddonRow({
  addon,
  now,
  asked,
  logOpen,
  onLog,
  onRestart,
}: {
  addon: AddonServer
  now: Date
  asked: string | undefined
  logOpen: boolean
  onLog: () => void
  onRestart: () => void
}) {
  return (
    <>
      <tr>
        <td>{addon.name}</td>
        <td>
          <StatusTag state={TAG[addon.state] ?? 'neutral'}>{addon.state}</StatusTag>
        </td>
        <td>{since(addon, now)}</td>
        <td>
          {explain(addon, now)}
          {asked === undefined ? null : <div className="addon-servers__asked">{asked}</div>}
        </td>
        <td className="addon-servers__actions">
          <Button small variant="minimal" icon="document" onClick={onLog} aria-expanded={logOpen}>
            {logOpen ? 'Hide log' : 'Log'}
          </Button>
          <Button small variant="minimal" icon="refresh" disabled={!addon.enabled} onClick={onRestart}>
            Restart
          </Button>
        </td>
      </tr>
      {logOpen ? (
        <tr>
          <td colSpan={5}>
            <Log id={addon.id} />
          </td>
        </tr>
      ) : null}
    </>
  )
}
