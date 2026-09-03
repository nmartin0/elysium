import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'

// document.getElementById('root')! -- genuinely non-null by
// construction, not assumed: index.html (this project's own, single
// source of truth for the DOM this mounts into) always declares
// <div id="root"></div>, and this file is the only thing that ever
// queries for it, immediately, synchronously, before anything else
// could remove it.
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
