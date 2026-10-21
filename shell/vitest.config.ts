import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['core/src/**/*.test.{ts,tsx}'],
    setupFiles: ['./vitest.setup.ts'],
  },
})
