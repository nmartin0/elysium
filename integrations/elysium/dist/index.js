// Heliograph's page in Elysium's shell (decision D50).
//
// Hand-written, no build step: an ES module whose bare imports are the page's
// own shared libraries (Elysium's import map; docs of its module API list
// them), so Heliograph carries no Node packages. Every call goes through the
// module API's addonRequest, to the engine process Elysium started and proxies.
// The engine answers only for a signed identity; this page is read-only.
import { createElement as h, useCallback, useEffect, useRef, useState } from 'react'
import { Button, Callout, HTMLTable, Spinner, Tag } from '@blueprintjs/core'
import { addonRequest, getErrorMessage, handleIfSessionExpired } from '@elysium/shell-api/api'
import { useHostValues } from '@elysium/shell-api/host'
import Page from '@elysium/shell-api/components/Page'

const MODULE = 'heliograph'
const POLL_MS = 5000
const BUSY = new Set(['queued', 'running'])

/** Tag intent for a backtest's status. */
export function intentOf(status) {
  if (status === 'complete') return 'success'
  if (BUSY.has(status)) return 'primary'
  return status.startsWith('failed') || status.startsWith('unreadable') ? 'danger' : 'none'
}

const number = (value, digits = 2) =>
  value === null || value === undefined ? '-' : Number(value).toLocaleString(undefined, { maximumFractionDigits: digits })

const when = (iso) => {
  if (!iso) return '-'
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

/** Reads `path` of the engine; `null` while loading. A refusal is said, an expired session handed back. */
function useEngine(path, onSessionExpired, refreshMs) {
  const [state, setState] = useState({ data: null, error: null })
  const [again, setAgain] = useState(0)
  // The latest handler, read when an answer arrives: a page that is handed a new function
  // on every render must not fetch again on every render.
  const expired = useRef(onSessionExpired)
  expired.current = onSessionExpired
  useEffect(() => {
    if (path === null) return undefined
    let alive = true
    addonRequest(MODULE, path).then(
      (data) => alive && setState({ data, error: null }),
      (error) => {
        if (!alive || handleIfSessionExpired(error, expired.current)) return
        setState({ data: null, error: getErrorMessage(error) })
      },
    )
    return () => {
      alive = false
    }
  }, [path, again])
  useEffect(() => {
    if (!refreshMs) return undefined
    const timer = setInterval(() => setAgain((n) => n + 1), refreshMs)
    return () => clearInterval(timer)
  }, [refreshMs])
  const reload = useCallback(() => setAgain((n) => n + 1), [])
  return { ...state, reload }
}

function Failure({ message }) {
  return h(Callout, { intent: 'danger', title: 'Heliograph could not answer', role: 'alert' }, message)
}

function Report({ id, onSessionExpired }) {
  const { data, error } = useEngine(`api/backtests/${encodeURIComponent(id)}/report`, onSessionExpired)
  if (error) return h(Failure, { message: error })
  if (!data) return h(Spinner, { size: 24 })
  return h(
    'section',
    { className: 'heliograph-report', 'aria-label': `Report of ${id}` },
    h(
      HTMLTable,
      { compact: true, striped: true },
      h(
        'thead',
        null,
        h('tr', null, ['Strategy', 'Instrument', 'Signals', 'Refused', 'Fills', 'Result', 'Drawdown'].map((c) => h('th', { key: c }, c))),
      ),
      h(
        'tbody',
        null,
        data.strategies.map((s) =>
          h(
            'tr',
            { key: s.strategy },
            h('td', null, s.strategy),
            h('td', null, s.instrument),
            h('td', null, s.signals),
            h('td', null, s.refused),
            h('td', null, s.fills),
            h('td', null, number(s.result)),
            h('td', null, number(s.drawdown)),
          ),
        ),
      ),
    ),
    h('pre', { className: 'heliograph-report-text' }, data.text),
  )
}

function Workspace() {
  const { onSessionExpired } = useHostValues()
  const [chosen, choose] = useState(null)
  const [busy, setBusy] = useState(false)
  const { data, error, reload } = useEngine('api/backtests', onSessionExpired, busy ? POLL_MS : 0)
  const runs = data ? data.backtests : null
  useEffect(() => {
    setBusy(runs !== null && runs.some((r) => BUSY.has(r.status)))
  }, [runs])
  const action = h(Button, { icon: 'refresh', minimal: true, onClick: reload }, 'Refresh')
  let body
  if (error) body = h(Failure, { message: error })
  else if (runs === null) body = h(Spinner, { size: 24 })
  else if (runs.length === 0) body = h('p', null, 'No backtests yet. Submit one to the engine and it appears here.')
  else
    body = h(
      HTMLTable,
      { interactive: true, compact: true, className: 'heliograph-runs' },
      h('thead', null, h('tr', null, ['Backtest', 'Status', 'From', 'To'].map((c) => h('th', { key: c }, c)))),
      h(
        'tbody',
        null,
        runs.map((run) =>
          h(
            'tr',
            { key: run.id, 'aria-selected': run.id === chosen, onClick: () => choose(run.id) },
            h('td', null, h('button', { type: 'button', className: 'heliograph-run', onClick: () => choose(run.id) }, run.id)),
            h('td', null, h(Tag, { intent: intentOf(run.status), minimal: true }, run.status)),
            h('td', null, when(run.start)),
            h('td', null, when(run.end)),
          ),
        ),
      ),
    )
  return h(
    Page,
    { title: 'Heliograph', description: 'Backtests of the strategy engine, and their reports.', action },
    body,
    chosen === null ? null : h(Report, { key: chosen, id: chosen, onSessionExpired }),
  )
}

/** The pages by the ids module.json declares. */
export function activate() {
  return { pages: { workspace: Workspace } }
}

export function deactivate() {}
