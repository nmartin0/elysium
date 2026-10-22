import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { RailTabsDialog, type RailTab } from './RailTabsDialog'

const TABS: RailTab[] = [
  { title: 'Query', path: '/query', pinned: false },
  { title: 'Schema', path: '/schema', pinned: false },
  { title: 'Modules', path: '/system/modules', pinned: true },
]

function open(hidden: string[] = [], onChange = vi.fn()) {
  render(<RailTabsDialog isOpen onClose={() => {}} tabs={TABS} hidden={new Set(hidden)} onChange={onChange} />)
  return onChange
}

describe('choosing your rail tabs', () => {
  it('shows each tab ticked unless hidden', () => {
    open(['/schema'])
    expect(screen.getByRole('checkbox', { name: 'Query' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'Schema' })).not.toBeChecked()
  })

  it('hides and shows as ticked', () => {
    const onChange = open(['/schema'])
    fireEvent.click(screen.getByRole('checkbox', { name: 'Query' }))
    expect([...onChange.mock.calls[0]![0]].sort()).toEqual(['/query', '/schema'])
    fireEvent.click(screen.getByRole('checkbox', { name: 'Schema' }))
    expect([...onChange.mock.calls[1]![0]]).toEqual([])
  })

  it('cannot hide a pinned tab', () => {
    open(['/system/modules'])
    const pinned = screen.getByRole('checkbox', { name: /Modules/ })
    expect(pinned).toBeChecked()
    expect(pinned).toBeDisabled()
  })
})
