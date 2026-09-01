import { useState } from 'react'
import LoginForm from './components/LoginForm'
import QueryPanel from './components/QueryPanel'
import ObjectSearchPanel from './components/ObjectSearchPanel'
import AdminPanel from './components/AdminPanel'
import { getToken, logout } from './api'
import './index.css'

// A plain state toggle, not react-router-dom -- still reasonable for
// three flat screens with no deep-linkable state of their own. Worth
// reaching for real routing once a screen needs a URL a person could
// bookmark or share -- e.g. a future individual Object View page
// (/objects/Customer/cust_001), which a plain toggle genuinely
// couldn't represent -- not before. Browse (ObjectSearchPanel) itself
// doesn't need one yet: nothing about "which type, what I typed" is
// meant to survive a reload or be shareable today.
export default function App() {
  const [isLoggedIn, setIsLoggedIn] = useState(!!getToken())
  const [view, setView] = useState('query')

  function handleLoginSuccess() {
    setIsLoggedIn(true)
  }

  async function handleLogout() {
    await logout()
    setIsLoggedIn(false)
  }

  function handleSessionExpired() {
    setIsLoggedIn(false)
  }

  return (
    <div className="app">
      <header className="app__header">
        <h1>Elysium</h1>
        {isLoggedIn && (
          <nav className="app__nav">
            <button className={view === 'query' ? '' : 'secondary'} onClick={() => setView('query')}>
              Query
            </button>
            <button className={view === 'browse' ? '' : 'secondary'} onClick={() => setView('browse')}>
              Browse
            </button>
            <button className={view === 'admin' ? '' : 'secondary'} onClick={() => setView('admin')}>
              Admin
            </button>
            <button className="secondary" onClick={handleLogout}>
              Log out
            </button>
          </nav>
        )}
      </header>

      <main>
        {!isLoggedIn ? (
          <LoginForm onSuccess={handleLoginSuccess} />
        ) : view === 'admin' ? (
          <AdminPanel onSessionExpired={handleSessionExpired} />
        ) : view === 'browse' ? (
          <ObjectSearchPanel onSessionExpired={handleSessionExpired} />
        ) : (
          <QueryPanel onSessionExpired={handleSessionExpired} />
        )}
      </main>
    </div>
  )
}
