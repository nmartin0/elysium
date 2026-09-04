import { useState } from 'react'
import { Button, Callout } from '@blueprintjs/core'
import { query } from '@elysium/shell-api/api'
import type { SubAppProps } from '@elysium/shell-api/types'
import PendingWriteCard, { type PendingWrite } from '@elysium/shell-api/components/PendingWriteCard'

interface QueryResponseBody {
  pending_write?: PendingWrite
  answer?: string
  detail?: string
}

// No additional props beyond the shell's own base contract -- see
// SubAppProps's own header comment for the full reasoning on why this
// is a real, shared, exported interface now, not an independently
// redeclared field.
type QueryPanelProps = SubAppProps

// Note on status 499 (client disconnected -- see api/routes.py's
// docstring): deliberately no special handling for it here. By the
// time the server decides the client is gone, this same fetch() call
// has already rejected with a network error on the browser's own side
// -- there's no real scenario where JS code running in a live tab
// ever observes a resolved response carrying status 499. The generic
// catch block below already covers it.
export default function QueryPanel({ onSessionExpired }: QueryPanelProps) {
  const [queryText, setQueryText] = useState('')
  const [answer, setAnswer] = useState<string | null>(null)
  const [pendingWrite, setPendingWrite] = useState<PendingWrite | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setAnswer(null)
    setPendingWrite(null)
    setSubmitting(true)

    try {
      // query() itself returns a real, typed Response (not
      // Promise<unknown> like most other api.ts callers -- see that
      // file's own comment on why: /query has four meaningfully
      // different outcomes the caller needs to branch on by status).
      const response = await query(queryText)

      if (response.status === 401) {
        onSessionExpired()
        return
      }

      // response.json() itself is typed `any` by TypeScript's own
      // built-in lib -- asserted to the real, known response body
      // shape here, matching api/routes.py's own documented contract
      // for the query route.
      const body = (await response.json()) as QueryResponseBody

      if (response.status === 202) {
        setPendingWrite(body.pending_write ?? null)
      } else if (response.status === 200) {
        setAnswer(body.answer ?? null)
      } else {
        // 403 (stale permissions were already fine at query time but
        // something else denied it), 409 (permissions changed mid-
        // request), or anything else -- shown exactly as the backend
        // phrased it, not reinterpreted client-side.
        setError(body.detail || `Request failed (${response.status})`)
      }
    } catch {
      setError('Could not reach the server.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="query-panel">
      <form onSubmit={handleSubmit}>
        <textarea
          value={queryText}
          onChange={(event) => setQueryText(event.target.value)}
          placeholder="Ask a question…"
          rows={3}
          required
        />
        {/* loading, not a separate disabled prop -- same real reasoning
            already established for CreateUserForm/LoginForm's own
            Button conversions: confirmed directly against Button's own
            type definition that loading alone already disables the
            button (even if disabled were explicitly false) while also
            showing a real, centered spinner. */}
        <Button type="submit" text={submitting ? 'Thinking…' : 'Ask'} loading={submitting} />
      </form>

      {/* intent="danger" for the error, deliberately no intent at all
          for the answer (a plain, neutral Callout) -- the answer isn't
          a "success" in the same sense an error is a failure, it's
          just the real, informational content the person was waiting
          for; success/danger stays reserved for genuinely binary
          outcomes elsewhere (see PendingWriteCard's own Callout usage
          for that real contrast). */}
      {error && <Callout intent="danger">{error}</Callout>}
      {answer && <Callout>{answer}</Callout>}
      {pendingWrite && (
        // No persistent view of an object here to refresh once
        // resolved (unlike ObjectDetailPanel.jsx's own ActionForm) --
        // an explicit no-op, not an unset default.
        <PendingWriteCard pendingWrite={pendingWrite} onSessionExpired={onSessionExpired} onResolved={() => {}} />
      )}
    </div>
  )
}

// =============================================================================
// AI-ONLY NOTES -- not user-facing. Context for a future AI session (or me,
// later) that lacks this conversation's history. Update this section
// whenever something genuinely open, deferred, or rejected comes up here.
// =============================================================================
//
// Blueprint migration for this file -- the roadmap discussed directly with
// the person scopes this and PendingWriteCard.tsx together as one step
// (Button, Callout), each its own commit, matching the same discipline
// AdminPanel's own multi-step migration already established.
//
// RESOLVED (kept for history):
// - Button for the "Ask" submit button, replacing a bare <button>. Same
//   real design decision already established for every other Button
//   conversion this migration: loading, not a separate disabled prop --
//   confirmed directly against Button's own type definition that loading
//   alone already disables the button while also showing a real, centered
//   spinner. Verified live in a real browser (rendering/styling confirmed;
//   a full submit needs a real, slow LLM round-trip the person has
//   deliberately deferred testing, so the actual query/answer flow itself
//   was verified through the existing unit suite, not a live LLM call).
// - Callout for the error message and the answer display, replacing two
//   bare, differently-shaped elements (<p className="error"> and
//   <div className="answer"><p>). intent="danger" for the error; the
//   answer stays deliberately intent-less (a plain, neutral Callout) --
//   it isn't a "success" in the sense an error is a failure, just the
//   real, informational content the person was waiting for; success/
//   danger stays reserved for genuinely binary outcomes (see
//   PendingWriteCard's own resolved Callout for that real contrast).
//   Verified live in a real browser: a genuine, simulated network
//   failure (going offline right before submitting, not a mocked
//   error) showed the real, styled danger Callout -- icon, red text,
//   and background -- correctly.
//
// This closes out this file's own half of the QueryPanel/PendingWriteCard
// Blueprint step -- see PendingWriteCard.tsx's own AI-notes for its half.
