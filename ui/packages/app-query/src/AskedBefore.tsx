/**
 * The questions asked in this session, newest first.
 *
 * WHY IT EXISTS. Asking a second question erased the first. There was
 * no way to see what had been asked, re-run it, or edit and retry --
 * which is most of what using a query tool consists of.
 *
 * IN MEMORY, FOR THIS SESSION ONLY, and that is a decision rather than
 * a shortcut. A question is not sensitive but an ANSWER can be, and
 * persisting either would mean a store that outlives the grants it was
 * answered under: a question answered while somebody held
 * `read:Customer.email` must not still be sitting in local storage
 * after that grant is revoked. The server already keeps the audit
 * trail, which is the record that should survive.
 *
 * QUESTIONS ONLY, NOT ANSWERS, for the same reason -- the list is for
 * getting back to what you asked, not for re-reading what you were
 * told.
 */

import Action from '@elysium/shell-api/components/Action'

export default function AskedBefore({
  questions,
  onPick,
}: {
  questions: string[]
  onPick: (question: string) => void
}) {
  if (questions.length === 0) return null

  return (
    <section className="query__history" aria-label="Asked before">
      <p className="query__history-lede">Asked in this session:</p>
      <ol>
        {questions.map((question, index) => (
          <li key={`${index}-${question}`}>
            <Action text={question} onClick={() => onPick(question)} />
          </li>
        ))}
      </ol>
    </section>
  )
}
