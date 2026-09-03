import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import UserMenu, { type CurrentUser } from './UserMenu'

const REAL_USER: CurrentUser = { username: 'alice', role_name: 'customer_service', mac_value: 'us-west' }

function openMenu(triggerName: string | RegExp = /./) {
  fireEvent.click(screen.getByRole('button', { name: triggerName }))
}

describe('UserMenu -- the trigger, before opening', () => {
  it('shows the real username as the trigger label once currentUser has loaded', () => {
    render(<UserMenu currentUser={REAL_USER} onLogout={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'alice' })).toBeInTheDocument()
  })

  it('shows a generic "Account" placeholder while currentUser is still null -- the brief window before GET /me resolves, not a crash', () => {
    render(<UserMenu currentUser={null} onLogout={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Account' })).toBeInTheDocument()
  })

  it('the menu panel does not exist in the DOM at all before the trigger is clicked', () => {
    render(<UserMenu currentUser={REAL_USER} onLogout={vi.fn()} />)
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })
})

describe('UserMenu -- opening and closing', () => {
  it('clicking the trigger opens the menu', () => {
    render(<UserMenu currentUser={REAL_USER} onLogout={vi.fn()} />)
    openMenu('alice')
    expect(screen.getByRole('menu')).toBeInTheDocument()
  })

  it('clicking the trigger again closes it', () => {
    render(<UserMenu currentUser={REAL_USER} onLogout={vi.fn()} />)
    openMenu('alice')
    openMenu('alice')
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('aria-expanded on the trigger reflects the real open/closed state', () => {
    render(<UserMenu currentUser={REAL_USER} onLogout={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'alice' })).toHaveAttribute('aria-expanded', 'false')
    openMenu('alice')
    expect(screen.getByRole('button', { name: 'alice' })).toHaveAttribute('aria-expanded', 'true')
  })

  it('clicking outside the menu closes it', () => {
    render(
      <div>
        <p>outside content</p>
        <UserMenu currentUser={REAL_USER} onLogout={vi.fn()} />
      </div>,
    )
    openMenu('alice')
    expect(screen.getByRole('menu')).toBeInTheDocument()

    fireEvent.mouseDown(screen.getByText('outside content'))

    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('clicking INSIDE the open menu -- on the profile info, not a real interactive item -- does NOT close it', () => {
    render(<UserMenu currentUser={REAL_USER} onLogout={vi.fn()} />)
    openMenu('alice')

    fireEvent.mouseDown(screen.getByText('alice', { selector: '.user-menu__username' }))

    expect(screen.getByRole('menu')).toBeInTheDocument()
  })

  it('pressing Escape closes the menu', () => {
    render(<UserMenu currentUser={REAL_USER} onLogout={vi.fn()} />)
    openMenu('alice')
    expect(screen.getByRole('menu')).toBeInTheDocument()

    fireEvent.keyDown(document, { key: 'Escape' })

    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('a different key -- not Escape -- does not close the menu', () => {
    render(<UserMenu currentUser={REAL_USER} onLogout={vi.fn()} />)
    openMenu('alice')

    fireEvent.keyDown(document, { key: 'Enter' })

    expect(screen.getByRole('menu')).toBeInTheDocument()
  })
})

describe('UserMenu -- the open panel contents', () => {
  it('shows the real username and role_name when currentUser is populated', () => {
    render(<UserMenu currentUser={REAL_USER} onLogout={vi.fn()} />)
    openMenu('alice')
    expect(screen.getByText('alice', { selector: '.user-menu__username' })).toBeInTheDocument()
    expect(screen.getByText('customer_service')).toBeInTheDocument()
  })

  it('shows no role line at all when role_name is null -- not a blank or "null" line', () => {
    render(<UserMenu currentUser={{ username: 'carol', role_name: null, mac_value: 'eu' }} onLogout={vi.fn()} />)
    openMenu('carol')
    expect(screen.queryByText('null')).not.toBeInTheDocument()
    expect(document.querySelector('.user-menu__role')).not.toBeInTheDocument()
  })

  it('shows no profile section at all while currentUser is still null -- only Log out is available', () => {
    render(<UserMenu currentUser={null} onLogout={vi.fn()} />)
    openMenu('Account')
    expect(document.querySelector('.user-menu__profile')).not.toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: 'Log out' })).toBeInTheDocument()
  })

  it('Log out is always present regardless of currentUser', () => {
    render(<UserMenu currentUser={REAL_USER} onLogout={vi.fn()} />)
    openMenu('alice')
    expect(screen.getByRole('menuitem', { name: 'Log out' })).toBeInTheDocument()
  })
})

describe('UserMenu -- logging out', () => {
  it('clicking Log out calls onLogout', () => {
    const onLogout = vi.fn()
    render(<UserMenu currentUser={REAL_USER} onLogout={onLogout} />)
    openMenu('alice')

    fireEvent.click(screen.getByRole('menuitem', { name: 'Log out' }))

    expect(onLogout).toHaveBeenCalledTimes(1)
  })

  it('clicking Log out also closes the menu', () => {
    render(<UserMenu currentUser={REAL_USER} onLogout={vi.fn()} />)
    openMenu('alice')

    fireEvent.click(screen.getByRole('menuitem', { name: 'Log out' }))

    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })
})
