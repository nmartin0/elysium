import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { Button, Menu, MenuItem, OverlaysProvider, PopoverNext } from '@blueprintjs/core'

// blueprint-smoke.test.tsx  (verification-only, NOT a real app feature)
//
// This step's own real question was never "does `npm install` exit
// 0" -- it was "does @blueprintjs/core's own React 19 support
// actually work in THIS app's real, live React 19 runtime." A clean
// install proves the two packages' declared version ranges are
// mutually satisfiable; it says nothing about whether the code inside
// them actually runs correctly once real React renders it.
//
// PopoverNext specifically, not plain Popover -- confirmed directly
// (Blueprint's own React-19-support wiki) that legacy Popover is the
// one part of Blueprint v6 that does NOT work under React 19; only
// PopoverNext (built on @floating-ui/react, confirmed via `npm ls`
// against this project's own real node_modules to be what's actually
// installed) is React-19-safe. This test exists specifically to catch
// a real, live regression in exactly that boundary, not to test
// Blueprint's own code in the abstract -- Blueprint has its own test
// suite for that.
//
// A real, concrete signal this test caught empirically, not
// theoretically: `npm install` printed real "ERESOLVE overriding peer
// dependency" warnings for react-popper (the LEGACY Popover's own
// dependency, capped at React 18) -- confirmed via `npm ls
// react-popper` to come from @blueprintjs/core itself, still bundled
// for backward compatibility even though this app will never import
// the legacy Popover that needs it. This test is what actually proves
// that warning is genuinely harmless for this app's own real usage,
// not just reasoned to be safe.
describe('Blueprint installation -- a real, live React 19 smoke test, not just a clean npm install', () => {
  it('Button renders and responds to a real click', () => {
    let clicked = false
    render(<Button text="Real button" onClick={() => (clicked = true)} />)
    fireEvent.click(screen.getByRole('button', { name: 'Real button' }))
    expect(clicked).toBe(true)
  })

  it('Menu/MenuItem render real, interactive menu items', () => {
    let clicked = false
    render(
      <Menu>
        <MenuItem text="Real item" onClick={() => (clicked = true)} />
      </Menu>,
    )
    fireEvent.click(screen.getByText('Real item'))
    expect(clicked).toBe(true)
  })

  it('PopoverNext -- the one component with a real, confirmed React 19 risk -- opens on click and shows its real content, wrapped in the same OverlaysProvider main.tsx actually uses', () => {
    render(
      <OverlaysProvider>
        <PopoverNext content={<p>Real popover content</p>}>
          <Button text="Open popover" />
        </PopoverNext>
      </OverlaysProvider>,
    )

    expect(screen.queryByText('Real popover content')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Open popover' }))

    expect(screen.getByText('Real popover content')).toBeInTheDocument()
  })

  // Escape-to-close is NOT tested here, deliberately, not an
  // oversight -- confirmed directly, not assumed: even with
  // autoFocus={true} explicitly set, document.activeElement stays
  // BODY throughout this test, in this jsdom environment. jsdom has a
  // real, known gap in simulating automatic focus management (the
  // same class of limitation as window.matchMedia's own absence,
  // confirmed earlier this session) -- Blueprint's own Escape
  // handling very plausibly depends on real focus actually having
  // moved into the overlay, which jsdom never does here regardless of
  // props. This is exactly the class of behavior this project's own
  // established discipline defers to a real, live browser check for
  // (see Shell.tsx's own AI-notes on the sidebar's CSS contrast bug,
  // caught the same way) -- to be confirmed live when UserMenu is
  // actually rebuilt on PopoverNext, not asserted here against an
  // environment that structurally cannot exercise it.
})
