/**
 * THE SERVER (BLOCKING.md item 3, step 3): Elysium's own server controls
 * -- its configuration and reload, the silos it reads, its metrics, the
 * mirror, and the cleaning rules waiting on a decision. They were five
 * views of Admin; they are the System sub-app's now, as BLOCKING.md's
 * "THE SHELL AND THE SERVER EACH HAVE A SYSTEM SUB-APP" planned: "much
 * of today's Admin, which splits into the server and people-and-roles".
 *
 * WHO SEES IT: whoever may run the server, manage:deployment -- the
 * System sub-app's permission (ui/src/system/module.json). The owner's
 * decision, 24 October. Before, these sat in Admin, offered on
 * manage:users, so an account administrator was shown Metrics, Mirror
 * and Cleaning and refused by the server, while an operator holding
 * manage:deployment was not shown them at all. The server's own checks
 * are unchanged: /config and /silos still answer manage:users, which
 * they took in August, when it was the only administrative grant.
 *
 * PINNED, AS THE REST OF SYSTEM: loaded in safe mode, which is when
 * someone most needs to see the configuration and reload it.
 *
 * THE VIEW IS IN THE URL (`?view=`), so a link to the mirror is a link.
 * Laid out as Admin laid them out: the views in the configuration pane,
 * the chosen one beside it.
 */
import ViewSelector, { type ViewOption } from '@elysium/shell-api/components/ViewSelector'
import Workspace from '@elysium/shell-api/components/Workspace'
import { useUrlValue } from '@elysium/shell-api/useUrlState'
import DeploymentConfig from './server/DeploymentConfig'
import MetricsPanel from './server/MetricsPanel'
import MirrorPanel from './server/MirrorPanel'
import RuleSuggestions from './server/RuleSuggestions'
import Silos from './server/Silos'

const SERVER_VIEWS: readonly ViewOption[] = [
  { id: 'deployment', label: 'Deployment', icon: 'cog' },
  { id: 'silos', label: 'Silos', icon: 'database' },
  { id: 'metrics', label: 'Metrics', icon: 'timeline-line-chart' },
  { id: 'mirror', label: 'Mirror', icon: 'database' },
  { id: 'cleaning', label: 'Cleaning', icon: 'clean' },
]

export default function ServerPage({ onSessionExpired }: { onSessionExpired: () => void }) {
  const [requested, setView] = useUrlValue('view', 'deployment')
  // An unknown view is the first, not an empty page.
  const view = SERVER_VIEWS.some((option) => option.id === requested) ? requested : 'deployment'

  return (
    <Workspace config={<ViewSelector views={SERVER_VIEWS} selected={view} onSelect={setView} />}>
      {view === 'deployment' && <DeploymentConfig onSessionExpired={onSessionExpired} />}
      {view === 'silos' && <Silos onSessionExpired={onSessionExpired} />}
      {view === 'metrics' && <MetricsPanel onSessionExpired={onSessionExpired} />}
      {view === 'mirror' && <MirrorPanel onSessionExpired={onSessionExpired} />}
      {view === 'cleaning' && <RuleSuggestions onSessionExpired={onSessionExpired} />}
    </Workspace>
  )
}
