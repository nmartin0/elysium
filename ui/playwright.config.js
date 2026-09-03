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
// shell.spec.js's own header comment for the exact setup this
// expects.
export default defineConfig({
  testDir: './e2e',
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://localhost:5173',
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
