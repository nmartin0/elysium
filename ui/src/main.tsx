// FIRST, before anything else runs: the page's copies of the shared
// libraries, registered for every module built apart from it
// (@shell/build/sharedLibraries).
import 'virtual:shared-registry'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { OverlaysProvider } from '@blueprintjs/core'
import App from './App'
// IBM PLEX, SELF-HOSTED (DEV_UI 9.1). The tokens named it for weeks and
// no font file existed, so every screen rendered in the system sans.
// Bundled from @fontsource (SIL OFL 1.1, which permits bundling): no CDN,
// because Elysium runs inside customer networks "sometimes with no
// outbound internet". THREE WEIGHTS -- 400, 500, 600 -- "because each one
// is bytes an operator waits for", and mono at 400 for identifiers. Each
// file is split by unicode-range, so a browser fetches only the scripts
// a page actually shows. The licence ships at /licenses/.
import '@fontsource/ibm-plex-sans/400.css'
import '@fontsource/ibm-plex-sans/500.css'
import '@fontsource/ibm-plex-sans/600.css'
import '@fontsource/ibm-plex-mono/400.css'

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
