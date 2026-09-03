import { useEffect, useRef, useState } from 'react'

// UserMenu.tsx  (#3 of the shell/launcher upgrade plan -- a real
// dropdown replacing the bare "Log out" button)
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
// project has consistently avoided elsewhere (see e.g. Shell.tsx's
// own reasoning against a real icon-strip collapsed sidebar before
// icon data exists). Add it here the moment a real settings feature
// exists, not before.

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
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  // Click-outside-to-close and Escape-to-close -- both real, standard
  // dropdown-menu expectations, not decoration. Both listeners are
  // only ever attached while the menu is actually open, and both
  // clean up correctly on close/unmount -- a listener left attached
  // after close would keep firing on every click anywhere in the app
  // for no reason.
  useEffect(() => {
    if (!open) return

    function handlePointerDown(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false)
    }

    document.addEventListener('mousedown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('mousedown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [open])

  function handleLogoutClick() {
    setOpen(false)
    onLogout()
  }

  // currentUser starts null for the brief window before GET /me
  // resolves (matching visibleApps'/visibleSchema's own established
  // "safe default while loading, no spinner" convention elsewhere in
  // this app) -- the trigger shows a generic placeholder rather than
  // blocking on it, and the dropdown's own profile section simply
  // doesn't render yet, while "Log out" itself is always available
  // regardless.
  const initial = currentUser ? currentUser.username.charAt(0).toUpperCase() : '…'
  const triggerLabel = currentUser ? currentUser.username : 'Account'

  return (
    <div className="user-menu" ref={containerRef}>
      {/* No .secondary class here, deliberately -- that global class
          is styled for the light page background every OTHER
          secondary button/link sits on (see index.css's own
          button.secondary rule); it read as dark, near-invisible text
          the first time this exact mistake was made on this same dark
          sidebar (see Shell.tsx's own AI-notes on the sidebar's own
          Log-out contrast bug). .user-menu__trigger below is fully
          self-contained instead -- its own complete style, not an
          override fighting a shared selector's own specificity. */}
      <button
        type="button"
        className="user-menu__trigger"
        onClick={() => setOpen((prev) => !prev)}
        aria-haspopup="true"
        aria-expanded={open}
      >
        <span className="user-menu__avatar" aria-hidden="true">
          {initial}
        </span>
        {triggerLabel}
      </button>

      {open && (
        <div className="user-menu__panel" role="menu">
          {currentUser && (
            <div className="user-menu__profile">
              <p className="user-menu__username">{currentUser.username}</p>
              {currentUser.role_name && <p className="user-menu__role">{currentUser.role_name}</p>}
            </div>
          )}
          <button type="button" className="user-menu__item" role="menuitem" onClick={handleLogoutClick}>
            Log out
          </button>
        </div>
      )}
    </div>
  )
}
