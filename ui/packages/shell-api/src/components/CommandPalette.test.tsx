import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import CommandPalette from './CommandPalette'
import type { Command } from '../commands'

/**
 * WHAT IS WORTH TESTING HERE, and what is not.
 *
 * `matching` has its own tests beside it in commands.test.ts, which
 * cover subsequence matching and the sort. This file covers the things
 * only the component decides: what the keyboard does, that a command
 * runs exactly once, that an unavailable one does NOT run and says why,
 * and that opening fresh does not inherit the last query.
 *
 * It deliberately does not assert on layout. jsdom computes none, and
 * the rules that matter -- the row not jittering under a held arrow
 * key, the first hit not moving as the list grows -- are in index.css
 * with the reasoning, not reachable from here.
 */

function commands(run: () => void = vi.fn()): Command[] {
  // THE UNAVAILABLE ONE FIRST, so the sort has work to do. Declared
  // last it had none, and "sorts it after the ones that can be run"
  // passed with the sort deleted. Every index-based assertion below
  // therefore reads against the SORTED order, not this one.
  return [
    { id: 'go:/admin', label: 'Users', group: 'Settings', unavailable: 'Needs manage:users', run },
    { id: 'go:/browse', label: 'Browse', group: 'Objects', run },
    { id: 'go:/schema', label: 'Ontology', group: 'Ontology', run },
  ]
}

function hits() {
  return screen.getAllByRole('option').map((node) => node.textContent)
}

describe('CommandPalette -- open and closed', () => {
  it('renders nothing while closed, rather than a hidden dialog', () => {
    render(<CommandPalette commands={commands()} isOpen={false} onClose={vi.fn()} />)
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('lists every command when open and nothing has been typed', () => {
    render(<CommandPalette commands={commands()} isOpen onClose={vi.fn()} />)
    expect(hits()).toHaveLength(3)
  })

  it('focuses the query field on open, so the first keystroke is the search', () => {
    render(<CommandPalette commands={commands()} isOpen onClose={vi.fn()} />)
    expect(screen.getByLabelText('Search commands')).toHaveFocus()
  })
})

describe('CommandPalette -- typing', () => {
  it('narrows to the matches, on a subsequence rather than a prefix', () => {
    render(<CommandPalette commands={commands()} isOpen onClose={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('Search commands'), { target: { value: 'ont' } })
    expect(hits()).toEqual(['OntologyOntology'])
  })

  it('says so plainly when nothing matches, instead of an empty list', () => {
    render(<CommandPalette commands={commands()} isOpen onClose={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('Search commands'), { target: { value: 'zzzz' } })
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(screen.getByText('Nothing matches that.')).toBeInTheDocument()
  })

  /**
   * THE BUG THIS GUARDS, and it is the reason the reset exists. Arrow
   * down to row three, then type -- without the reset the highlight is
   * still on index 2, which is now a different command. Enter then runs
   * something nobody looked at.
   */
  it('puts the highlight back on the first hit when the query changes', () => {
    render(<CommandPalette commands={commands()} isOpen onClose={vi.fn()} />)
    const query = screen.getByLabelText('Search commands')
    fireEvent.keyDown(query, { key: 'ArrowDown' })
    expect(screen.getAllByRole('option')[1]).toHaveAttribute('aria-selected', 'true')

    fireEvent.change(query, { target: { value: 'o' } })
    expect(screen.getAllByRole('option')[0]).toHaveAttribute('aria-selected', 'true')
  })
})

describe('CommandPalette -- the keyboard', () => {
  it('moves the highlight down and back up', () => {
    render(<CommandPalette commands={commands()} isOpen onClose={vi.fn()} />)
    const query = screen.getByLabelText('Search commands')

    fireEvent.keyDown(query, { key: 'ArrowDown' })
    fireEvent.keyDown(query, { key: 'ArrowDown' })
    expect(screen.getAllByRole('option')[2]).toHaveAttribute('aria-selected', 'true')

    fireEvent.keyDown(query, { key: 'ArrowUp' })
    expect(screen.getAllByRole('option')[1]).toHaveAttribute('aria-selected', 'true')
  })

  it('stops at both ends rather than wrapping, so a held key settles somewhere', () => {
    render(<CommandPalette commands={commands()} isOpen onClose={vi.fn()} />)
    const query = screen.getByLabelText('Search commands')

    for (let press = 0; press < 6; press += 1) fireEvent.keyDown(query, { key: 'ArrowDown' })
    expect(screen.getAllByRole('option')[2]).toHaveAttribute('aria-selected', 'true')

    for (let press = 0; press < 6; press += 1) fireEvent.keyDown(query, { key: 'ArrowUp' })
    expect(screen.getAllByRole('option')[0]).toHaveAttribute('aria-selected', 'true')
  })

  it('runs the highlighted command on Enter, and closes first so the next screen is not behind a dialog', () => {
    const run = vi.fn()
    const onClose = vi.fn()
    render(<CommandPalette commands={commands(run)} isOpen onClose={onClose} />)

    fireEvent.keyDown(screen.getByLabelText('Search commands'), { key: 'Enter' })
    expect(run).toHaveBeenCalledTimes(1)
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('does nothing on Enter when nothing matches, rather than throwing on an absent hit', () => {
    const run = vi.fn()
    render(<CommandPalette commands={commands(run)} isOpen onClose={vi.fn()} />)
    const query = screen.getByLabelText('Search commands')

    fireEvent.change(query, { target: { value: 'zzzz' } })
    fireEvent.keyDown(query, { key: 'Enter' })
    expect(run).not.toHaveBeenCalled()
  })
})

describe('CommandPalette -- a command that cannot be run', () => {
  /**
   * DEV_UI.md 10.1: unavailable is "shown disabled WITH THE REASON
   * rather than hidden". Both halves are load-bearing -- hiding it is
   * the easier code and the worse interface, and greying it without the
   * sentence tells somebody they are stuck without telling them why.
   */
  it('lists it, with its reason beside it', () => {
    render(<CommandPalette commands={commands()} isOpen onClose={vi.fn()} />)
    expect(screen.getByText('Needs manage:users')).toBeInTheDocument()
  })

  it('marks it disabled to a screen reader as well as to the eye', () => {
    render(<CommandPalette commands={commands()} isOpen onClose={vi.fn()} />)
    const users = screen.getAllByRole('option').find((node) => node.textContent?.includes('Users'))
    expect(users).toHaveAttribute('aria-disabled', 'true')
  })

  it('sorts it after the ones that can be run', () => {
    render(<CommandPalette commands={commands()} isOpen onClose={vi.fn()} />)
    expect(hits()[2]).toContain('Users')
  })

  it('does not run it on Enter, and does not close either -- the palette stays up for a second try', () => {
    const run = vi.fn()
    const onClose = vi.fn()
    render(<CommandPalette commands={commands(run)} isOpen onClose={onClose} />)
    const query = screen.getByLabelText('Search commands')

    fireEvent.keyDown(query, { key: 'ArrowDown' })
    fireEvent.keyDown(query, { key: 'ArrowDown' })
    fireEvent.keyDown(query, { key: 'Enter' })

    expect(run).not.toHaveBeenCalled()
    expect(onClose).not.toHaveBeenCalled()
  })

  it('does not run it on a click either', () => {
    const run = vi.fn()
    render(<CommandPalette commands={commands(run)} isOpen onClose={vi.fn()} />)
    const users = screen.getAllByRole('option').find((node) => node.textContent?.includes('Users'))!

    fireEvent.click(users)
    expect(run).not.toHaveBeenCalled()
  })
})

describe('CommandPalette -- the mouse', () => {
  it('runs a command on a click', () => {
    const run = vi.fn()
    render(<CommandPalette commands={commands(run)} isOpen onClose={vi.fn()} />)
    const browse = screen.getAllByRole('option').find((node) => node.textContent?.includes('Browse'))!

    fireEvent.click(browse)
    expect(run).toHaveBeenCalledTimes(1)
  })

  /**
   * HOVER MOVES THE HIGHLIGHT, which is not decoration: without it the
   * mouse and the keyboard disagree about what Enter would do, and a
   * person who hovers one row and presses Enter runs another.
   */
  it('moves the highlight to whatever the pointer is over', () => {
    render(<CommandPalette commands={commands()} isOpen onClose={vi.fn()} />)
    fireEvent.mouseEnter(screen.getAllByRole('option')[1]!)
    expect(screen.getAllByRole('option')[1]).toHaveAttribute('aria-selected', 'true')
  })
})

describe('CommandPalette -- reopening', () => {
  /**
   * THE PALETTE IS FOR THE NEXT THING, NOT THE LAST ONE. Reopening to a
   * stale query makes the first keystroke a correction, which is the
   * sort of friction that stops people reaching for it at all.
   */
  it('comes back empty rather than holding the previous query', async () => {
    const { rerender } = render(<CommandPalette commands={commands()} isOpen onClose={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('Search commands'), { target: { value: 'ont' } })
    expect(hits()).toHaveLength(1)

    rerender(<CommandPalette commands={commands()} isOpen={false} onClose={vi.fn()} />)
    await waitFor(() => expect(screen.queryByRole('listbox')).not.toBeInTheDocument())

    rerender(<CommandPalette commands={commands()} isOpen onClose={vi.fn()} />)
    expect(screen.getByLabelText('Search commands')).toHaveValue('')
    expect(hits()).toHaveLength(3)
  })
})
