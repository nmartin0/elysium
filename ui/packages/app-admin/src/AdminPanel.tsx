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

export interface User {
  username: string
  role_name: string
  mac_value: string | null
  disabled: boolean
}

interface AdminPanelProps {
  onSessionExpired: () => void
}

// Every action here is gated server-side by manage:users -- this
// component never decides who's allowed to do what, it just calls the
// real endpoint and shows whatever the backend actually decides. A
// non-admin landing here simply sees the real 403 from GET /users,
// same as any other error -- no separate "am I an admin" check exists
// or is needed client-side.
export default function AdminPanel({ onSessionExpired }: AdminPanelProps) {
  const [users, setUsers] = useState<User[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [schemaByUsername, setSchemaByUsername] = useState<Record<string, unknown>>({})

  async function loadUsers() {
    setError(null)
    try {
      // listUsers() itself returns Promise<unknown> (see api.ts's own
      // header comment on why) -- asserted to the real, known
      // response shape here, matching api/routes.py's own documented
      // contract for GET /users.
      const data = (await listUsers()) as User[]
      setUsers(data)
    } catch (err) {
      if (handleIfSessionExpired(err, onSessionExpired)) return
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  useEffect(() => {
    loadUsers()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function handleAction(action: (username: string) => Promise<void>, username: string) {
    setError(null)
    try {
      await action(username)
      await loadUsers()
    } catch (err) {
      if (handleIfSessionExpired(err, onSessionExpired)) return
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  async function handleToggleSchema(username: string) {
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
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  function handleDelete(username: string) {
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
                {/* !== undefined, not a bare truthy check -- schemaByUsername's
                    own values are typed unknown (Record<string, unknown>),
                    and `unknown && <jsx>` is not assignable to ReactNode
                    (confirmed directly via tsc, not assumed): TypeScript
                    needs the left side of && to be a real boolean. !==
                    undefined preserves the exact same real behavior as the
                    original bare truthy check -- a stored schema value is
                    always a real, truthy object from the backend, never
                    null/0/''/false, so the only two real states are
                    "absent" (undefined) or "a real object" either way. */}
                {schemaByUsername[user.username] !== undefined && (
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

interface CreateUserFormProps {
  onCreated: () => Promise<void>
  onError: (error: string | null) => void
  onSessionExpired: () => void
}

function CreateUserForm({ onCreated, onError, onSessionExpired }: CreateUserFormProps) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [macValue, setMacValue] = useState('')
  const [roleName, setRoleName] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
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
      onError(err instanceof Error ? err.message : String(err))
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
