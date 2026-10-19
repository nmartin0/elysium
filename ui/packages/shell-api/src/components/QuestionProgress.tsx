/**
 * QuestionProgress -- what a question has done so far, while it runs
 * (19 October).
 *
 * A QUESTION TAKES MINUTES on a CPU model, and the page said nothing
 * until the end: a button reading "Thinking…". Nielsen's limits are the
 * reason this exists -- "10 seconds is about the limit for keeping the
 * user's attention focused on the dialogue"; past it, people "should be
 * given feedback indicating when the computer expects to be done", with
 * "a clearly signposted way for the user to interrupt the operation".
 *
 * WHAT IT CAN HONESTLY SAY: the steps already done, in the words the
 * answer will end with; how long it has been; and when the answer is
 * being written. Not a percentage -- how many steps a question needs is
 * the model's choice, and a bar that guesses is a bar that lies.
 *
 * STOP closes the request, and the server abandons the run (AL-11).
 *
 * ANNOUNCED POLITELY: each new step reaches a screen reader without
 * interrupting it.
 */

import { Spinner } from '@blueprintjs/core'
import { useEffect, useState } from 'react'

import type { QueryProgress } from '../api'
import Action from './Action'

interface QuestionProgressProps {
  progress: QueryProgress | null
  /** Date.now() when the question was sent. */
  startedAt: number
  onStop: () => void
}

export function elapsed(milliseconds: number): string {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000))
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

export default function QuestionProgress({ progress, startedAt, onStop }: QuestionProgressProps) {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])

  const lines = progress?.lines ?? []
  return (
    <section className="question-progress" aria-label="Working on your question">
      <header className="question-progress__head">
        <Spinner size={16} />
        <span className="question-progress__title">
          {progress?.answering ? 'Writing the answer' : 'Working on it'} ·{' '}
          <span className="question-progress__elapsed">{elapsed(now - startedAt)}</span>
        </span>
        <Action tone="quiet" text="Stop" onClick={onStop} />
      </header>
      <ol className="question-progress__steps" aria-live="polite">
        {lines.map((line, index) => (
          <li key={index}>{line}</li>
        ))}
      </ol>
      {lines.length === 0 && !progress?.answering && (
        <p className="question-progress__waiting">Choosing the first step…</p>
      )}
    </section>
  )
}
