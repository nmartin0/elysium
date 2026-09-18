import { defineConfig } from '@playwright/test'

// Deliberately NOT auto-starting a backend server here -- unlike the
// frontend (which Playwright's own webServer option COULD start),
// the real backend needs a specific, known deployment (fixtures
// config, real test users created ahead of time) that only a human
// or a real setup script can provide -- matches this project's own
// existing pattern for its Ollama-requiring backend e2e tests
// (tests/integration/, marked @pytest.mark.integration): real,
// persisted, re-runnable tests, but requiring a manually-started
// real server, not a fully self-orchestrating pipeline. See e2e/
// shell.spec.ts's own header comment for the exact setup this
// expects.
export default defineConfig({
  testDir: './e2e',
  use: {
    // THE UVICORN SERVER, not Vite's dev server.
    //
    // uvicorn already serves the built UI and the API on one port, so
    // pointing here means the only setup is the server a developer is
    // already running. Defaulting to :5173 required a SECOND process
    // that nobody remembered to start -- every one of these tests
    // failed with ERR_CONNECTION_REFUSED the first time they were run,
    // which is setup, not a fault in the tests.
    //
    // It also tests the BUILT bundle, which is what a person actually
    // sees. The dev server serves a different one.
    baseURL: process.env.E2E_BASE_URL || 'http://localhost:8000',
    // Normally unset -- Playwright finds its own, normally-installed
    // browser (via `npx playwright install`) automatically. Exists
    // ONLY for environments with restricted network egress that
    // can't download Playwright's own default browser build but
    // already have a compatible chromium on disk from elsewhere (the
    // exact situation this test was first verified in) -- never
    // needed on a normal machine with ordinary network access.
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_PATH ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH } : {},
  },
})
