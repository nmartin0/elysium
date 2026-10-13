/**
 * The help assistant, in a dialog from the header.
 *
 * A DIALOG, NOT A DRAWER: Dialog is already on the Blueprint surface the
 * UI-kit plan pins, and Drawer is not -- one more component for the kit
 * to own, for no difference a reader would notice.
 *
 * WHAT IT ANSWERS: how to use Elysium, as this person can -- which
 * screens they have, which kinds of object they may know about, why a
 * field shows as hidden. It has none of their DATA, by design (see
 * core/agent/help_assistant.py), and says so at the top so nobody asks
 * it for a customer's email and reads its refusal as a fault.
 *
 * THE ANSWER IS PLAIN TEXT, rendered as text. A model's reply is never
 * HTML here.
 */

import { Button, Dialog, DialogBody, TextArea } from '@blueprintjs/core'
import { useState } from 'react'

import { askHelp, getErrorMessage } from '../api'

export default function HelpPanel({
  isOpen,
  onClose,
  screen,
}: {
  isOpen: boolean
  onClose: () => void
  screen: string | null
}) {
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [asking, setAsking] = useState(false)

  const ask = () => {
    if (!question.trim() || asking) return
    setAsking(true)
    setError(null)
    setAnswer(null)
    askHelp(question, screen)
      .then(setAnswer)
      .catch((caught: unknown) => setError(getErrorMessage(caught)))
      .finally(() => setAsking(false))
  }

  return (
    <Dialog isOpen={isOpen} onClose={onClose} title="Help" className="help-panel">
      <DialogBody className="help-panel__body">
        <p className="help-panel__intro">
          Ask how to do something in Elysium. The assistant knows the screens and kinds of object you can see, not your
          data — for questions about the data itself, use Query.
        </p>
        <TextArea
          aria-label="Your question"
          fill
          value={question}
          placeholder="How do I filter by region?"
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              ask()
            }
          }}
        />
        <Button intent="primary" onClick={ask} loading={asking} disabled={!question.trim()}>
          Ask
        </Button>
        {error && <p className="help-panel__error">{error}</p>}
        {answer !== null && (
          <div className="help-panel__answer" aria-live="polite">
            {answer}
          </div>
        )}
      </DialogBody>
    </Dialog>
  )
}
