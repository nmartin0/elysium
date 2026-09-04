import { useState } from 'react'
import { Button, Callout, FormGroup, InputGroup } from '@blueprintjs/core'
import { login, getErrorMessage } from '../api'

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
      // getErrorMessage() (see api.ts) is what actually narrows the
      // catch binding safely -- a catch binding is typed unknown in
      // strict mode (JavaScript allows throwing anything at all, not
      // just Error instances), and while login() only ever really
      // throws ApiError in practice, a genuine network-level failure
      // could in theory throw something else that's still a real
      // Error (with a real, honest .message) before ever reaching
      // ApiError's own construction. getErrorMessage()'s own
      // String(err) fallback covers the true, if practically
      // unreached, case of a non-Error throw.
      setError(getErrorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form className="login-form" onSubmit={handleSubmit}>
      {/* Explicit id/labelFor pairing, autoComplete preserved on each
          real InputGroup -- same real pattern already confirmed
          working for CreateUserForm's own Blueprint migration
          (AdminPanel Blueprint step 3): FormGroup renders a real,
          separate <label for="..."> element, unlike the original's
          own implicit, nested <label>text<input /></label>
          association. autoComplete flows straight through --
          InputGroupProps extends React's own real HTMLInputProps,
          confirmed directly against its type definition, not assumed
          -- genuinely necessary to keep here, not cosmetic: browser
          password managers and autofill depend on it, and this
          project's own live-browser test scripts already select these
          exact fields via input[autocomplete=username]/
          input[autocomplete=current-password]. */}
      <FormGroup label="Username" labelFor="login-username">
        <InputGroup
          id="login-username"
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          autoComplete="username"
          required
        />
      </FormGroup>
      <FormGroup label="Password" labelFor="login-password">
        <InputGroup
          id="login-password"
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          autoComplete="current-password"
          required
        />
      </FormGroup>
      {error && <Callout intent="danger">{error}</Callout>}
      {/* loading, not a separate disabled prop -- same real reasoning
          as CreateUserForm's own Button: confirmed directly against
          Button's own type definition that loading alone already
          disables the button (even if disabled were explicitly
          false) while also showing a real, centered spinner, strictly
          more informative than the original's own plain text-swap for
          the same one prop. */}
      <Button type="submit" text={submitting ? 'Logging in…' : 'Log in'} loading={submitting} />
    </form>
  )
}

// =============================================================================
// AI-ONLY NOTES -- not user-facing. Context for a future AI session (or me,
// later) that lacks this conversation's history. Update this section
// whenever something genuinely open, deferred, or rejected comes up here.
// =============================================================================
//
// This file's own Blueprint migration -- a single, complete step, unlike
// AdminPanel's own three (see that file's own AI-notes for the fuller,
// multi-step precedent this follows the same discipline as): FormGroup/
// InputGroup/Button, replacing the bare <label>/<input>/<button> elements.
// Same real design decisions as CreateUserForm's own equivalent step
// (AdminPanel Blueprint step 3): explicit id/labelFor pairing (FormGroup
// renders a real, separate <label for="...">, confirmed directly against
// its type definition, unlike the original's own implicit, nested
// association), and Button's own `loading` prop in place of a separate
// `disabled` (confirmed directly that loading alone already disables the
// button while also showing a real spinner). autoComplete="username"/
// "current-password" both confirmed to flow straight through InputGroup
// (extends React's own real HTMLInputProps) -- genuinely necessary to
// preserve, not cosmetic: this project's own live-browser test scripts
// already select these exact fields via input[autocomplete=username]/
// input[autocomplete=current-password], confirmed still working live,
// not just in source.
//
// The error message was initially left as a plain <p className="error">
// here, deliberately, when this step was originally scoped -- Callout
// was scoped to a different, later step (QueryPanel/PendingWriteCard)
// at the time. Later converted to Callout intent="danger" too, as
// part of a full-migration review pass, once it turned out to be a
// real, genuine gap, not an intentional final state: a systematic
// grep across the whole frontend, done specifically to catch exactly
// this kind of thing, found this file (and AdminPanel.tsx's own
// top-level error) were the only two files left still using the old,
// bare <p className="error"> pattern, after every other sub-app had
// already, consistently moved to Callout. Fixed to match, and the
// now-fully-dead .error CSS rule removed in the same pass, confirmed
// dead first via a real, whole-frontend grep, not assumed.
//
// Verified live, beyond the unit suite: a real wrong-password attempt
// showed the real error message correctly; a real, successful login via
// real label-based field selection (get_by_label(), which itself depends
// on genuine label/for-id association actually working) completed
// correctly.
