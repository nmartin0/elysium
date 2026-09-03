import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { OverlaysProvider } from '@blueprintjs/core'
import App from './App'

// document.getElementById('root')! -- genuinely non-null by
// construction, not assumed: index.html (this project's own, single
// source of truth for the DOM this mounts into) always declares
// <div id="root"></div>, and this file is the only thing that ever
// queries for it, immediately, synchronously, before anything else
// could remove it.
//
// <OverlaysProvider> wraps the whole app, at the true root -- required
// (not optional) by Blueprint v6 for every overlay-based component
// (Popover, Dialog, Drawer, Alert), confirmed directly against
// Blueprint's own migration wiki before adding it, not assumed. Must
// wrap EVERYTHING, since any screen -- not just the ones already
// planned to use Blueprint first -- could reach for an overlay-based
// component later; this is genuinely a one-time, whole-app setup
// step, not something to add per-screen as each one migrates.
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <OverlaysProvider>
      <App />
    </OverlaysProvider>
  </StrictMode>,
)
