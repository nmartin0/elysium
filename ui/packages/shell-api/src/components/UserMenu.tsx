import { Button, Menu, MenuItem, PopoverNext } from '@blueprintjs/core'

// UserMenu.tsx  (#3 of the shell/launcher upgrade plan, rebuilt on
// Blueprint -- see the Blueprint migration's own roadmap discussion)
//
// Backed by a real, minimal "who am I" endpoint (GET /me, see api.ts's
// own comment on it) -- confirmed directly against how established
// identity platforms do this (OpenID Connect's own UserInfo endpoint;
// Palantir Foundry's own real, documented GET .../admin/users/
// getCurrent) before building this, not invented from scratch.
//
// Deliberately does NOT include a "Settings" item -- there is no real
// settings feature anywhere in this app yet; adding a menu entry that
// opens nothing would be exactly the kind of speculative UI this
// project has consistently avoided elsewhere.
//
// UNCONTROLLED, deliberately -- no isOpen/onInteraction wiring, no own
// `open` state at all. PopoverNext manages its own open/closed state
// internally, and a real, documented default already does everything
// this file used to hand-roll: MenuItem's own click dismisses its
// parent Popover automatically (confirmed directly, not assumed),
// PopoverNext itself already applies aria-expanded and aria-haspopup
// to its own target element (confirmed directly against Blueprint's
// own changelog -- "apply aria-expanded and aria-haspopup a11y
// attributes to child target element"), and click-outside/Escape-to-
// close are both real, built-in PopoverNext behavior, not something
// this file needs to reimplement. The entire hand-rolled useEffect
// (click-outside listener, Escape listener, a containerRef, an open
// state) that used to live here is gone -- not replaced by different
// code, genuinely no longer needed.
//
// The profile section (username, role) is deliberately NOT a
// MenuItem -- it isn't an interactive, clickable action, it's static
// information, so it renders as plain content alongside the real
// <Menu> inside the popover's own content, not forced into a menu
// item shape it doesn't actually have.

export interface CurrentUser {
  username: string
  role_name: string | null
  mac_value: string | null
}

interface UserMenuProps {
  currentUser: CurrentUser | null
  onLogout: () => void
}

export default function UserMenu({ currentUser, onLogout }: UserMenuProps) {
  // currentUser starts null for the brief window before GET /me
  // resolves (matching visibleApps'/visibleSchema's own established
  // "safe default while loading, no spinner" convention elsewhere in
  // this app) -- the trigger shows a generic placeholder rather than
  // blocking on it, and the profile section simply doesn't render
  // yet, while "Log out" itself is always available regardless.
  const initial = currentUser ? currentUser.username.charAt(0).toUpperCase() : '…'
  const triggerLabel = currentUser ? currentUser.username : 'Account'

  return (
    <PopoverNext
      placement="top-start"
      content={
        <>
          {currentUser && (
            <div className="user-menu__profile">
              <p className="user-menu__username">{currentUser.username}</p>
              {currentUser.role_name && <p className="user-menu__role">{currentUser.role_name}</p>}
            </div>
          )}
          <Menu>
            <MenuItem text="Log out" onClick={onLogout} />
          </Menu>
        </>
      }
    >
      <Button className="user-menu__trigger" alignText="left" fill minimal>
        <span className="user-menu__avatar" aria-hidden="true">
          {initial}
        </span>
        {triggerLabel}
      </Button>
    </PopoverNext>
  )
}
