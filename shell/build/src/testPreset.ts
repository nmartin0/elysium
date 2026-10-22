/**
 * The test configuration every module inherits (BLOCKING.md item 3,
 * "COMMON BEHAVIOUR IS TESTED ONCE, BY DEFAULT, UNTIL OVERRIDDEN").
 *
 * INHERITED, NEVER COPIED: a module's `vitest.config.ts` is a few lines
 * calling this, and the host page's own config calls it too, so a fix
 * here reaches every module and the page at once. Vitest's own projects
 * are the shape -- options "are merged with the project's own options",
 * and `setupFiles` "are concatenated, not overridden" -- and Backstage's
 * CLI the precedent: "a default configuration included in the CLI".
 *
 * GENERIC: nothing here knows Elysium. A provider passes its own setup
 * file (Elysium's: `@elysium/testing/setup`).
 *
 * EVERY VALUE BELOW WAS MEASURED ON ELYSIUM'S SUITE, which is where they
 * were set before this preset existed (ui/vite.config.ts); the history
 * moved here with them.
 */

export interface ModuleTestOptions {
  /** The provider's setup file(s), then any of the module's own. */
  setupFiles: string[]
  /** Which files are tests, relative to the module's root. */
  include?: string[]
  /** See `timezone` below; override only to test another zone. */
  timezone?: string
}

/** Vitest's `test` options for a module, or for the host page itself. */
export function moduleTestConfig(options: ModuleTestOptions) {
  return {
    environment: 'jsdom' as const,
    /**
     * A TIME ZONE THAT IS NOT UTC, deliberately. The container runs in
     * UTC, where every time-zone bug is invisible: `new Date('2026-01-01')`
     * renders as 1 January, and a formatter that wrongly converts a date
     * looks correct. In New York the same expression renders as 31
     * DECEMBER 2025 -- somebody's birthday, moved a day. Two controls on
     * Elysium's formatTemporal failed to fire because of this.
     *
     * New York because it is behind UTC, so date slippage shows, and
     * observes daylight saving, so a fixed-offset mistake shows too.
     */
    env: { TZ: options.timezone ?? 'America/New_York' },
    globals: true,
    setupFiles: options.setupFiles,
    /**
     * THREADS, NOT FORKS: 208 s against 215 s on the same tree and
     * machine. A thread shares the process, so standing up a jsdom per
     * file -- most of the run -- costs less.
     *
     * Tried and rejected, so nobody spends the afternoon again:
     * `isolate: false` timed out past 285 s (the tests that lean on a
     * clean DOM are why isolation is there); `deps.optimizer` failed to
     * start.
     */
    pool: 'threads' as const,
    /**
     * SIZED FOR THE SLOWEST MACHINE THAT RUNS THIS. The owner's full run
     * took 1,942 s where the development container's takes about 280,
     * and at that speed the 5 s default failed a SYNCHRONOUS render
     * test that passed alone in ten seconds. A genuine hang now takes
     * 30 s to say so instead of 5 -- the price of a suite that does not
     * fail differently on different machines. Raising it further must
     * never be the first move when something goes red. Testing
     * Library's own `waitFor` timeout is set in the provider's setup
     * file, being its knob and not Vitest's.
     */
    testTimeout: 30_000,
    hookTimeout: 30_000,
    include: options.include ?? ['src/**/*.test.{ts,tsx}'],
  }
}
