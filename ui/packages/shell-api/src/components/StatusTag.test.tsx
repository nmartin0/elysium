import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'

import StatusTag from './StatusTag'

/**
 * BLUEPRINT PUTS THE TEXT IN A CHILD SPAN. `getByText` returns that
 * span, whose class list is `bp6-text-overflow-ellipsis bp6-fill` --
 * so asserting against it tests the wrong element and fails on every
 * intent. The tag itself is the nearest `.bp6-tag` ancestor.
 */
const tagFor = (text: string) => {
  const element = screen.getByText(text).closest('.bp6-tag')
  if (!element) throw new Error(`no tag around ${text}`)
  return element
}

describe('the house default', () => {
  it('is minimal, which 40 of 43 existing tags already were', () => {
    render(<StatusTag>us-east</StatusTag>)

    expect(tagFor('us-east').className).toContain('bp6-minimal')
  })

  it('a neutral tag carries no intent', () => {
    render(<StatusTag>us-east</StatusTag>)
    const tag = tagFor('us-east')

    for (const intent of ['primary', 'success', 'warning', 'danger']) {
      expect(tag.className).not.toContain(`bp6-intent-${intent}`)
    }
  })
})

describe('states map to one intent each', () => {
  /** The question this removes: "is a rejected write danger or
   *  warning?" Answered once, here, rather than differently on each
   *  screen. */
  it.each([
    ['pending', 'warning'],
    ['active', 'primary'],
    ['granted', 'success'],
    ['refused', 'danger'],
  ] as const)('%s is %s', (state, intent) => {
    render(<StatusTag state={state}>label</StatusTag>)

    expect(tagFor('label').className).toContain(`bp6-intent-${intent}`)
  })
})
