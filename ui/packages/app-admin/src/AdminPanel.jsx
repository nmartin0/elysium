import { Fragment, useEffect, useState } from 'react'
import {
  listUsers,
  createUser,
  disableUser,
  enableUser,
  deleteUser,
  logoutAllForUser,
  getVisibleSchema,
  handleIfSessionExpired,
} from '@elysium/shell-api/api'

// Every action here is gated server-side by manage:users -- this
// component never decides who's allowed to do what, it just calls the
// real endpoint and shows whatever the backend actually decides. A
// non-admin landing here simply sees the real 403 from GET /users,
// same as any other error -- no separate "am I an admin" check exists
// or is needed client-side.
export default function AdminPanel({ onSessionExpired }) {
  const [users, setUsers] = useState(null)
  const [error, setError] = useState(null)
  const [schemaByUsername, setSchemaByUsername] = useState({})

  async function loadUsers() {
    setError(null)
    try {
      const data = await listUsers()
      setUsers(data)
    } catch (err) {
      if (handleIfSessionExpired(err, onSessionExpired)) return
      setError(err.message)
    }
  }

  useEffect(() => {
    loadUsers()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function handleAction(action, username) {
    setError(null)
    try {
      await action(username)
      await loadUsers()
    } catch (err) {
      if (handleIfSessionExpired(err, onSessionExpired)) return
      setError(err.message)
    }
  }

  async function handleToggleSchema(username) {
    if (schemaByUsername[username]) {
      setSchemaByUsername((prev) => {
        const next = { ...prev }
        delete next[username]
        return next
      })
      return
    }
    try {
      const schema = await getVisibleSchema(username)
      setSchemaByUsername((prev) => ({ ...prev, [username]: schema }))
    } catch (err) {
      if (handleIfSessionExpired(err, onSessionExpired)) return
      setError(err.message)
    }
  }

  function handleDelete(username) {
    if (window.confirm(`Delete ${username}? This cannot be undone.`)) {
      handleAction(deleteUser, username)
    }
  }

  return (
    <div className="admin-panel">
      <CreateUserForm onCreated={loadUsers} onError={setError} onSessionExpired={onSessionExpired} />

      {error && <p className="error">{error}</p>}

      {users === null ? (
        <p>Loading…</p>
      ) : (
        <table className="user-table">
          <thead>
            <tr>
              <th>Username</th>
              <th>Role</th>
              <th>MAC value</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map((user) => (
              <Fragment key={user.username}>
                <tr>
                  <td>{user.username}</td>
                  <td>{user.role_name}</td>
                  <td>{user.mac_value ?? '—'}</td>
                  <td>{user.disabled ? 'Disabled' : 'Active'}</td>
                  <td className="user-table__actions">
                    {user.disabled ? (
                      <button onClick={() => handleAction(enableUser, user.username)}>Enable</button>
                    ) : (
                      <button onClick={() => handleAction(disableUser, user.username)}>Disable</button>
                    )}
                    <button onClick={() => handleAction(logoutAllForUser, user.username)}>Log out sessions</button>
                    <button onClick={() => handleToggleSchema(user.username)}>
                      {schemaByUsername[user.username] ? 'Hide schema' : 'View schema'}
                    </button>
                    <button className="danger" onClick={() => handleDelete(user.username)}>
                      Delete
                    </button>
                  </td>
                </tr>
                {schemaByUsername[user.username] && (
                  <tr>
                    <td colSpan={5}>
                      <pre>{JSON.stringify(schemaByUsername[user.username], null, 2)}</pre>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function CreateUserForm({ onCreated, onError, onSessionExpired }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [macValue, setMacValue] = useState('')
  const [roleName, setRoleName] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(event) {
    event.preventDefault()
    setSubmitting(true)
    onError(null)
    try {
      await createUser(username, password, macValue, roleName)
      setUsername('')
      setPassword('')
      setMacValue('')
      setRoleName('')
      await onCreated()
    } catch (err) {
      if (handleIfSessionExpired(err, onSessionExpired)) return
      onError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form className="create-user-form" onSubmit={handleSubmit}>
      <h3>Create user</h3>
      <label>
        Username
        <input value={username} onChange={(e) => setUsername(e.target.value)} required />
      </label>
      <label>
        Password
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
      </label>
      <label>
        MAC value (optional)
        <input value={macValue} onChange={(e) => setMacValue(e.target.value)} />
      </label>
      <label>
        Role
        <input value={roleName} onChange={(e) => setRoleName(e.target.value)} required />
      </label>
      <button type="submit" disabled={submitting}>
        {submitting ? 'Creating…' : 'Create user'}
      </button>
    </form>
  )
}
