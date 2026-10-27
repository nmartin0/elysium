import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import Logo from './Logo'

describe('Logo', () => {
  it('is decorative unless given a title, so the name is heard once', () => {
    const { container } = render(<Logo />)

    expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
    expect(screen.queryByRole('img')).toBeNull()
  })

  it('is an image with a name when it stands alone', () => {
    render(<Logo title="Elysium" />)

    expect(screen.getByRole('img', { name: 'Elysium' })).toBeInTheDocument()
  })

  it('draws nine bands and a crown, with the entrance cut out rather than painted', () => {
    const { container } = render(<Logo />)

    expect(container.querySelectorAll('g rect')).toHaveLength(9)
    expect(container.querySelectorAll('g path')).toHaveLength(1)
    // A hole shows whatever is behind; a painted arch would be the
    // wrong colour on a sidebar, a card or a tab strip.
    const group = container.querySelector('g')
    const maskId = /url\(#(.+)\)/.exec(group?.getAttribute('mask') ?? '')?.[1]
    expect(maskId).toBeDefined()
    expect(container.querySelector(`mask[id="${maskId}"] path`)).toHaveAttribute('fill', 'black')
  })

  it('keeps its proportions as it grows', () => {
    const { container } = render(<Logo size={58} />)
    const svg = container.querySelector('svg')

    expect(svg).toHaveAttribute('height', '58')
    expect(Number(svg?.getAttribute('width'))).toBeCloseTo(56, 5)
  })

  it('takes its colour from the text around it, so it follows the theme', () => {
    const { container } = render(<Logo />)

    expect(container.querySelector('g')).toHaveAttribute('fill', 'currentColor')
  })
})
