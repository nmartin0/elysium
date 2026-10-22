// The Schema graph's tests, configured as every module's are: the shared
// preset (@shell/build/testPreset) with the provider's setup file. Run by
// `npx vitest run` from ui/ as a project of its own (ui/vite.config.ts),
// or alone: `npx vitest run --project app-schema`.
import { moduleTestConfig } from '@shell/build/testPreset'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  // One React, as the page has (ui/vite.config.ts): @shell/core carries
  // its own copy for its own tests.
  resolve: { dedupe: ['react', 'react-dom', 'react-router-dom', '@blueprintjs/core'] },
  test: { name: 'app-schema', ...moduleTestConfig({ setupFiles: ['@elysium/testing/setup'] }) },
})
