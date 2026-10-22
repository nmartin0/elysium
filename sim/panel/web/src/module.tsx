/**
 * The simulator's control panel as a module of Elysium's shell (BLOCKING.md
 * item 3, step 2.3): the entry of its bundle, built by Elysium's UI build
 * (ui/addons/simulator.vite.config.ts) into sim/panel/dist and served by
 * Elysium from there, like any module's.
 */
import { useHostValues } from '@elysium/shell-api/host'
import type { ModuleActivation } from '@shell/core/moduleLoader'
import SimulatorPanel from './SimulatorPanel'
import './panel.css'

function PanelPage() {
  const { onSessionExpired } = useHostValues()
  return <SimulatorPanel onSessionExpired={onSessionExpired} />
}

/** The pages by the ids module.json declares. */
export function activate(): ModuleActivation {
  return { pages: { panel: PanelPage } }
}
