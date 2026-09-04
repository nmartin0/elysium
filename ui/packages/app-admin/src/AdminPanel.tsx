import { Fragment, useEffect, useState } from 'react'
import { Alert, Button, Callout, FormGroup, HTMLTable, InputGroup } from '@blueprintjs/core'
import {
  listUsers,
  createUser,
  disableUser,
  enableUser,
  deleteUser,
  logoutAllForUser,
  getVisibleSchema,
  getErrorMessage,
  handleIfSessionExpired,
} from '@elysium/shell-api/api'
import type { SubAppProps } from '@elysium/shell-api/types'

export interface User {
  username: string
  role_name: string
  mac_value: string | null
  disabled: boolean
}

// No additional props beyond the shell's own base contract -- see
// SubAppProps's own header comment for the full reasoning on why this
// is a real, shared, exported interface now, not an independently
// redeclared field.
type AdminPanelProps = SubAppProps

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
      setError(getErrorMessage(err))
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
      setError(getErrorMessage(err))
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
    // setError(null) here too -- a real, genuine inconsistency found
    // during a later, full-migration review pass: every OTHER real
    // attempt in this file (loadUsers, handleAction, confirmDelete)
    // already clears a prior error before its own try block; this one
    // didn't, so a stale error from an earlier, unrelated failure
    // (e.g. a failed delete) could keep showing even after a
    // completely different action, this one, succeeded. Pre-existing,
    // unrelated to Blueprint itself -- found while reviewing this
    // exact file for the review the person asked for.
    setError(null)
    try {
      const schema = await getVisibleSchema(username)
      setSchemaByUsername((prev) => ({ ...prev, [username]: schema }))
    } catch (err) {
      if (handleIfSessionExpired(err, onSessionExpired)) return
      setError(getErrorMessage(err))
    }
  }

  // Tracks WHICH user (if any) has a pending delete confirmation --
  // null means no Alert is open. One, shared Alert instance below is
  // reused for whichever row's own Delete button was clicked, rather
  // than one Alert per row -- the standard, efficient pattern for
  // this exact "confirm THIS row's own destructive action" shape.
  const [pendingDeleteUsername, setPendingDeleteUsername] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)

  async function confirmDelete() {
    if (pendingDeleteUsername === null) return
    setDeleting(true)
    // handleAction() above already catches and reports its own errors
    // (setError, or a real session-expiry redirect) -- it never
    // rethrows, so this always resolves, regardless of whether the
    // delete itself actually succeeded. Closing the Alert either way
    // is the right call here: on success there's nothing left to
    // confirm; on failure, the real error is already visible on the
    // main panel the instant the Alert closes, not silently lost.
    await handleAction(deleteUser, pendingDeleteUsername)
    setDeleting(false)
    setPendingDeleteUsername(null)
  }

  return (
    <div className="admin-panel">
      <CreateUserForm onCreated={loadUsers} onError={setError} onSessionExpired={onSessionExpired} />

      {error && <Callout intent="danger">{error}</Callout>}

      {users === null ? (
        <p>Loading…</p>
      ) : (
        // HTMLTable, not a bare <table> -- Blueprint's own styled
        // wrapper around a real HTML table, confirmed directly against
        // its real type definition before using it: it only wraps the
        // outer <table> element itself (extends React's own real
        // TableHTMLAttributes), so every child below (<thead>,
        // <tbody>, <tr>, <td>) stays exactly what it already was, not
        // rewritten into some other, different table abstraction.
        // interactive: real hover feedback on a genuinely scannable
        // list of rows; striped: alternating row backgrounds, which
        // matters here specifically since each user can also expand a
        // second, full-width schema row directly beneath its own row
        // (see the schemaByUsername block below) -- striping helps
        // keep a user's own two rows visually paired at a glance.
        <HTMLTable className="user-table" interactive striped>
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
                    <button className="danger" onClick={() => setPendingDeleteUsername(user.username)}>
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
        </HTMLTable>
      )}

      {/* One, shared Alert, not one per row -- see pendingDeleteUsername's
          own comment above for why. isOpen is real, controlled state
          (Alert's own isOpen prop is required, not optional -- confirmed
          directly against its real type definition), not a bare truthy
          check on the username itself, since an empty-string username
          would otherwise, incorrectly, never open this. */}
      <Alert
        isOpen={pendingDeleteUsername !== null}
        intent="danger"
        icon="trash"
        confirmButtonText="Delete"
        cancelButtonText="Cancel"
        loading={deleting}
        canEscapeKeyCancel
        canOutsideClickCancel
        onConfirm={confirmDelete}
        onCancel={() => setPendingDeleteUsername(null)}
      >
        <p>
          Delete <strong>{pendingDeleteUsername}</strong>? This cannot be undone.
        </p>
      </Alert>
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
      onError(getErrorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form className="create-user-form" onSubmit={handleSubmit}>
      <h3>Create user</h3>
      {/* Explicit id/labelFor pairing on every field below -- Blueprint's
          own FormGroup+InputGroup are real, separate sibling elements
          (labelFor renders a real HTML <label for="...">), unlike the
          original's own nested <label>text<input /></label>, which
          associated implicitly and needed no id at all. Confirmed
          directly against FormGroup's own real type definition before
          writing this, not assumed from a different component's API. */}
      <FormGroup label="Username" labelFor="create-user-username">
        <InputGroup id="create-user-username" value={username} onChange={(e) => setUsername(e.target.value)} required />
      </FormGroup>
      <FormGroup label="Password" labelFor="create-user-password">
        <InputGroup
          id="create-user-password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
      </FormGroup>
      {/* labelInfo, not "(optional)" baked into the label text itself --
          FormGroup's own real, purpose-built prop for exactly this kind
          of secondary, after-the-label annotation. */}
      <FormGroup label="MAC value" labelFor="create-user-mac" labelInfo="(optional)">
        <InputGroup id="create-user-mac" value={macValue} onChange={(e) => setMacValue(e.target.value)} />
      </FormGroup>
      <FormGroup label="Role" labelFor="create-user-role">
        <InputGroup id="create-user-role" value={roleName} onChange={(e) => setRoleName(e.target.value)} required />
      </FormGroup>
      {/* loading, not a separate disabled prop -- confirmed directly
          against Button's own real type definition: loading ALREADY
          disables the button on its own (even if disabled were
          explicitly false), and additionally shows a real, centered
          spinner in place of the text -- strictly more informative
          than the original's own plain disabled + text-swap, for the
          same one prop. */}
      <Button type="submit" text={submitting ? 'Creating…' : 'Create user'} loading={submitting} />
    </form>
  )
}

// =============================================================================
// AI-ONLY NOTES -- not user-facing. Context for a future AI session (or me,
// later) that lacks this conversation's history. Update this section
// whenever something genuinely open, deferred, or rejected comes up here.
// =============================================================================
//
// Blueprint migration for this sub-app, in progress -- see Shell.tsx's own
// AI-notes for the sidebar's own, now-complete migration; this file follows
// the same discipline (verify a component's real, current type definitions
// directly against node_modules before using it, never assume from memory
// or from how an earlier Blueprint version worked).
//
// RESOLVED (kept for history):
// - HTMLTable for the user list, replacing a bare <table>. Confirmed
//   directly against its real type definition before using it: it only
//   wraps the outer <table> element itself (extends React's own real
//   TableHTMLAttributes), so every child (<thead>, <tbody>, <tr>, <td>)
//   needed zero changes -- a genuinely low-risk, structurally-transparent
//   swap. interactive + striped props added; confirmed live in a real
//   browser that both the real bp6-html-table/bp6-interactive/
//   bp6-html-table-striped classes apply and the table renders correctly.
// - Alert, replacing window.confirm() for the delete-user flow. One,
//   shared, controlled Alert instance (pendingDeleteUsername tracks
//   WHICH row, not one Alert per row), with a real loading state while
//   the delete request is actually in flight -- confirmed directly
//   against Alert's own real type definition that this specific prop
//   exists for exactly this situation, not invented. icon="trash" is a
//   plain string literal, confirmed directly (via tsc, not assumed) to
//   type-check correctly against Alert's own real IconName type without
//   needing @blueprintjs/icons added as a direct dependency at all --
//   nothing here ever imports from that package directly, only passes a
//   string @blueprintjs/core itself already resolves internally via its
//   own, already-direct dependency on icons. The three existing tests
//   that exercised the old window.confirm() mock were rewritten against
//   the real Alert (open/cancel/confirm), each confirmed meaningful with
//   a real negative control, not just written and trusted. Confirmed
//   live in a real browser beyond the unit suite: the real trash icon
//   SVG genuinely renders (not just referenced), Cancel genuinely leaves
//   the user untouched, and a real Confirm genuinely deletes the user via
//   a real backend call, not simulated.
// - FormGroup/InputGroup/Button for CreateUserForm, replacing the bare
//   <label>/<input>/<button> elements -- the last step on this sub-app's
//   own roadmap, closing it out. Each field's own real, explicit
//   id/labelFor pairing, confirmed directly against FormGroup's own
//   type definition first: it renders a real, separate <label for="...">
//   element, unlike the original's own implicit, nested <label>text
//   <input /></label> association, which needed no id at all.
//   labelInfo="(optional)" for the MAC value field specifically --
//   FormGroup's own real, purpose-built prop for this exact kind of
//   secondary, after-the-label annotation, not baked into the main
//   label text the way the original had it. Button's own `loading`
//   prop used in place of the original's separate `disabled` -- confirmed
//   directly against its real type definition that loading alone already
//   disables the button (even if disabled were explicitly false) while
//   also showing a real, centered spinner, strictly more informative
//   than the original's own plain text-swap for the same one prop. All
//   26 existing tests passed completely unchanged (testing-library's own
//   getByLabelText() already handles both the old nested-label and the
//   new labelFor/id association forms transparently) -- confirmed live
//   in a real browser beyond the unit suite too: real, label-based field
//   selection (Playwright's own get_by_label(), which itself depends on
//   genuine label/for-id association working, not simulated) filled out
//   and submitted the real form, genuinely creating a new user visible
//   in the table afterward, with the form correctly reset.
// - A real, genuine gap found and fixed during a later, full-migration
//   review pass, not caught during any of the three steps above: this
//   file's own top-level error state (shared by CreateUserForm's own
//   onError callback and every handleAction/loadUsers/confirmDelete
//   failure) was still rendered as a bare <p className="error">,
//   missed across all three Blueprint steps -- CreateUserForm's own
//   fields got FormGroup/InputGroup, but this specific, separate error
//   display was simply never noticed. Found via a systematic,
//   whole-frontend grep for the old className="error" pattern, done
//   specifically to catch exactly this kind of gap, not by chance --
//   LoginForm.tsx had the identical gap, found and fixed in the same
//   pass (see that file's own AI-notes). Converted to Callout
//   intent="danger", matching every other error Callout across the
//   whole app; the now-fully-dead .error CSS rule removed in the same
//   pass, confirmed dead first via a real grep, not assumed.
//
// This closes out AdminPanel's own Blueprint migration -- every step on
// the original roadmap (HTMLTable, Alert, FormGroup/InputGroup/Button)
// is done.
//
// DEFERRED (known, intentional, not yet built):
// - No Select for the role field, despite it being the most naturally
//   Select-shaped field in the form (a closed, small set of valid values
//   in any real deployment) -- confirmed directly, not assumed: the
//   backend exposes NO endpoint at all that lists valid role names
//   (checked api/routes.py and api/apps.py directly; role definitions
//   live only in each deployment's own, server-side policy.yaml,
//   read via request.app.state.config.roles, never serialized to the
//   client anywhere). Hardcoding a fixed list of role names in the
//   frontend would be actively wrong -- role names are genuinely
//   deployment-specific, not a fixed, universal set this codebase could
//   ever safely assume. Stays a plain text InputGroup until/unless a
//   real "list valid role names" endpoint exists to back a genuine
//   Select -- a real, separate, backend-first change, not attempted as
//   part of this frontend-only pass.
