import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'

import Action from './Action'

/**
 * The point of this wrapper is CONSISTENCY, not swappability, so the
 * tests check that the defaults are applied -- not that Blueprint is
 * hidden. A test asserting "no Blueprint class appears" would be
 * testing the weak argument and would fail the moment somebody uses a
 * legitimate escape hatch.
 */

describe('the house default', () => {
  it('is small and minimal without being asked', () => {
    render(<Action text="Edit" />)
    const button = screen.getByRole('button', { name: 'Edit' })

    expect(button.className).toContain('bp6-minimal')
    expect(button.className).toContain('bp6-small')
  })

  it('still renders its text and stays a button', () => {
    render(<Action text="Edit" />)

    expect(screen.getByRole('button', { name: 'Edit' })).toBeTruthy()
  })
})

describe('the variants that genuinely differ', () => {
  it('a primary action is not minimal', () => {
    render(<Action tone="primary" text="Save" />)
    const button = screen.getByRole('button', { name: 'Save' })

    expect(button.className).toContain('bp6-intent-primary')
    expect(button.className).not.toContain('bp6-minimal')
  })

  it('a destructive action says so', () => {
    render(<Action tone="danger" text="Revoke" />)

    expect(screen.getByRole('button', { name: 'Revoke' }).className).toContain('bp6-intent-danger')
  })
})

describe('what it does not take', () => {
  it("passes through the props that are the caller's business", () => {
    render(<Action text="Edit" disabled />)

    expect(screen.getByRole('button', { name: 'Edit' })).toHaveProperty('disabled', true)
  })
})
