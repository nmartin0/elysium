import { useState } from 'react'
import { login } from '../api'

interface LoginFormProps {
  onSuccess: () => void
}

export default function LoginForm({ onSuccess }: LoginFormProps) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await login(username, password)
      onSuccess()
    } catch (err) {
      // The backend deliberately returns the SAME generic message for
      // a wrong password, an unknown username, and a disabled account
      // -- shown here exactly as received, not reinterpreted.
      //
      // err instanceof Error, not a narrower ApiError check -- strict
      // mode types a catch binding as unknown (JavaScript allows
      // throwing anything at all, not just Error instances), and
      // while login() only ever really throws ApiError in practice, a
      // genuine network-level failure could in theory throw something
      // else that's still a real Error (with a real, honest .message)
      // before ever reaching ApiError's own construction. The String()
      // fallback covers the true, if practically unreached, case of a
      // non-Error throw.
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form className="login-form" onSubmit={handleSubmit}>
      <label>
        Username
        <input
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          autoComplete="username"
          required
        />
      </label>
      <label>
        Password
        <input
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          autoComplete="current-password"
          required
        />
      </label>
      {error && <p className="error">{error}</p>}
      <button type="submit" disabled={submitting}>
        {submitting ? 'Logging in…' : 'Log in'}
      </button>
    </form>
  )
}
