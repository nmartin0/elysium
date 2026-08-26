import { useState } from 'react'
import LoginForm from './components/LoginForm'
import QueryPanel from './components/QueryPanel'
import AdminPanel from './components/AdminPanel'
import { getToken, logout } from './api'
import './index.css'

// A plain state toggle, not react-router-dom -- reasonable for two
// screens; worth reaching for real routing once a third screen
// (e.g. a future graph/relationship view) makes hand-rolled toggling
// awkward, not before.
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
        ) : (
          <QueryPanel onSessionExpired={handleSessionExpired} />
        )}
      </main>
    </div>
  )
}
