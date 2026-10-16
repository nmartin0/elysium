import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import FileDiff from './FileDiff'

describe('FileDiff', () => {
  it('colours added and removed lines, and not the file headers', () => {
    render(<FileDiff label="Changes" lines={['--- a (now)', '+++ a (after)', '-old: 1', '+new: 2', ' same']} />)

    expect(screen.getByText('+new: 2')).toHaveClass('config-editor__added')
    expect(screen.getByText('-old: 1')).toHaveClass('config-editor__removed')
    expect(screen.getByText('+++ a (after)')).not.toHaveClass('config-editor__added')
    expect(screen.getByLabelText('Changes')).toBeInTheDocument()
  })
})
