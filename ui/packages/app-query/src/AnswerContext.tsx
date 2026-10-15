/**
 * What comes with an answer: how it was reached, where it leads, and
 * what to ask next. Built on the server from the agent's own steps --
 * core/agent/answer_context.py has the reasoning; this only draws it.
 *
 * READ BACK ABOVE THE ANSWER, OPEN. DEV_UI 9.8: "STEPS VISIBLE ... with
 * the answer beneath. The steps are collapsible but shown by default: an
 * agent that traverses an ontology is making claims about YOUR data, and
 * the traversal is the evidence." Power BI and ThoughtSpot read a
 * question back so a person can check what was understood; here that is
 * what was DONE, and it sits where it can be checked before the number
 * is believed.
 *
 * FOLLOW-ONS FILL THE BOX, THEY DO NOT ASK. A suggestion is a guess
 * about what someone wants, and asking it on a click would spend a
 * model run on the guess. Putting it in the box lets them edit it first
 * -- and each one is a whole question, because there is no thread.
 */

import Action from '@elysium/shell-api/components/Action'
import { Link } from 'react-router-dom'

export interface AnswerDoor {
  kind: 'object' | 'set'
  object_type: string
  label: string
  object_id?: string | null
  filters?: { field: string; values: string[]; mode: 'keep' | 'exclude' }[] | null
}

/** Where a door goes: the object's page, or the set in Browse in the
 * URL form Browse already reads (`type` and `filters`). */
export function doorHref(door: AnswerDoor): string {
  if (door.kind === 'object' && door.object_id) {
    return `/objects/${encodeURIComponent(door.object_type)}/${encodeURIComponent(door.object_id)}`
  }
  const params = new URLSearchParams({ type: door.object_type })
  if (door.filters && door.filters.length > 0) params.set('filters', JSON.stringify(door.filters))
  return `/browse?${params.toString()}`
}

export function ReadBack({ steps }: { steps: string[] }) {
  if (steps.length === 0) return null
  return (
    <details className="answer-context__read-back" open>
      <summary>What it did to answer</summary>
      <ol>
        {steps.map((step, index) => (
          <li key={`${index}-${step}`}>{step}</li>
        ))}
      </ol>
    </details>
  )
}

export function WhereNext({
  doors,
  followOns,
  onPick,
}: {
  doors: AnswerDoor[]
  followOns: string[]
  onPick: (question: string) => void
}) {
  if (doors.length === 0 && followOns.length === 0) return null
  return (
    <section className="answer-context" aria-label="Where next">
      {doors.length > 0 && (
        <p className="answer-context__doors">
          <span className="answer-context__lede">Open:</span>
          {doors.map((door) => (
            <Link key={doorHref(door)} className="answer-context__door" to={doorHref(door)}>
              {door.label}
            </Link>
          ))}
        </p>
      )}
      {followOns.length > 0 && (
        <>
          <p className="answer-context__lede">Ask next:</p>
          <ul className="answer-context__follow-ons">
            {followOns.map((question) => (
              <li key={question}>
                <Action text={question} onClick={() => onPick(question)} />
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}
