/**
 * Ask the agent about the set on screen, without leaving it (DEV_UI 5.4).
 *
 * "THE AGENT EVERYWHERE: 'ask about this set' inside Browse, seeded with
 * what is on screen. Elysium's actual edge over the prior art, where AI
 * sits alongside rather than inside." And section 4's symptom: "the
 * agent lives in its own app, so a question about what you are looking
 * at means starting again in another tab, describing in words what was
 * already on screen."
 *
 * WHAT CHANGED, decided 14 Oct ("both"): this was a link to Query with
 * a phrase -- "About the 404 Transaction objects matching 2 filters:" --
 * which named how many filters and not which, and left Browse. It is a
 * panel over Browse now, and it sends the SET: the type, its conditions
 * and the text search. The server says it to the agent in words,
 * after checking the asker could have built it (core/agent/
 * set_context.py). Query stays the place for open-ended questions, and
 * the panel offers to continue there.
 *
 * A FROZEN SET is described by its name, through Query as before: its
 * membership is a list of keys the agent has no step to read.
 *
 * SLOW BY NATURE ON SOME HARDWARE, and said so: an answer can take
 * minutes on a CPU, and a spinner with no words reads as hung.
 */

import { useState } from 'react'
import { Button, Drawer, DrawerSize, TextArea } from '@blueprintjs/core'
import { Link } from 'react-router-dom'

import { messageFromErrorBody, query } from '@elysium/shell-api/api'
import Action from '@elysium/shell-api/components/Action'
import ErrorState from '@elysium/shell-api/components/ErrorState'
import LoadingState from '@elysium/shell-api/components/LoadingState'
import PendingWriteCard, { type PendingWrite } from '@elysium/shell-api/components/PendingWriteCard'

import AskTheAgent from './AskTheAgent'

interface AskAboutSetProps {
  objectType: string | null
  filterCount: number
  total: number
  /** The set's conditions, in the filter wire form. */
  conditions?: unknown[]
  /** The text search narrowing it. */
  text?: string
  /** The frozen set's name, when the set on screen is frozen. */
  frozen?: string | null
  onSessionExpired?: () => void
}

/** How the set is named on the panel -- the same words SetName uses. */
function describe(objectType: string, filterCount: number, total: number): string {
  const narrowed = filterCount > 0 ? ` matching ${filterCount} filter${filterCount === 1 ? '' : 's'}` : ''
  return `${total.toLocaleString()} ${objectType} objects${narrowed}`
}

export default function AskAboutSet({
  objectType,
  filterCount,
  total,
  conditions = [],
  text = '',
  frozen = null,
  onSessionExpired = () => {},
}: AskAboutSetProps) {
  const [open, setOpen] = useState(false)
  const [question, setQuestion] = useState('')
  const [asking, setAsking] = useState(false)
  const [answer, setAnswer] = useState<string | null>(null)
  const [pendingWrite, setPendingWrite] = useState<PendingWrite | null>(null)
  const [error, setError] = useState<string | null>(null)

  if (!objectType) return null
  const subject = describe(objectType, filterCount, total)

  if (frozen) {
    return <AskTheAgent subject={`About the frozen set ${frozen} (${subject}): `}>Ask about this set</AskTheAgent>
  }

  const ask = async () => {
    if (!question.trim()) return
    setAsking(true)
    setAnswer(null)
    setPendingWrite(null)
    setError(null)
    try {
      const response = await query(question, { object_type: objectType, conditions, text })
      if (response.status === 401) {
        onSessionExpired()
        return
      }
      const body = (await response.json().catch(() => ({}))) as {
        answer?: string
        pending_write?: PendingWrite
      }
      if (response.status === 202) setPendingWrite(body.pending_write ?? null)
      else if (response.status === 200) setAnswer(body.answer ?? null)
      else setError(messageFromErrorBody(body) ?? `Request failed (${response.status})`)
    } catch {
      setError('Could not reach the server.')
    } finally {
      setAsking(false)
    }
  }

  return (
    <>
      <Button minimal small icon="chat" className="ask-the-agent" onClick={() => setOpen(true)}>
        Ask about this set
      </Button>
      <Drawer
        isOpen={open}
        onClose={() => setOpen(false)}
        size={DrawerSize.SMALL}
        // NO BACKDROP: the point is that the set stays in view, readable
        // and scrollable, while the question is asked about it.
        hasBackdrop={false}
        enforceFocus={false}
        title="Ask about this set"
        icon="chat"
        className="ask-panel"
      >
        <div className="ask-panel__body">
          <p className="ask-panel__subject">
            About the <strong>{subject}</strong> on screen. The assistant reads only what you may read.
          </p>
          <TextArea
            fill
            autoResize
            aria-label="Your question about this set"
            placeholder="Which of these…"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) void ask()
            }}
          />
          <div className="ask-panel__actions">
            <Action tone="primary" text="Ask" disabled={asking || !question.trim()} onClick={() => void ask()} />
            <Link className="ask-panel__elsewhere" to={`/query?q=${encodeURIComponent(question)}`}>
              Continue in Query
            </Link>
          </div>
          {asking && (
            <>
              <LoadingState label="Asking…" />
              <p className="ask-panel__note">This can take a few minutes on this deployment's hardware.</p>
            </>
          )}
          {error && <ErrorState>{error}</ErrorState>}
          {answer !== null && <p className="ask-panel__answer">{answer}</p>}
          {pendingWrite && (
            <PendingWriteCard pendingWrite={pendingWrite} onSessionExpired={onSessionExpired} onResolved={() => {}} />
          )}
        </div>
      </Drawer>
    </>
  )
}
