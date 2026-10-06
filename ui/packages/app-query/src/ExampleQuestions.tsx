/**
 * What this deployment can be asked, shown before anything is asked.
 *
 * THE PROBLEM IT SOLVES. A first-time user met a text field and
 * nothing else -- no indication of what the ontology accepts, what a
 * question may ask for, or that a refusal is a normal answer rather
 * than a failure. example_queries.yaml was loaded and validated on
 * every start and then discarded.
 *
 * ONLY `display: true` EXAMPLES REACH HERE, and the server refuses at
 * LOAD any that names an identifier-shaped token. So these ask a SHAPE
 * of question -- what the ontology can be asked -- never about a
 * particular row, and they are safe to render to anybody.
 *
 * CLICKING ONE FILLS THE BOX RATHER THAN ASKING IT. The person decides
 * when to ask; an example that submitted itself would spend somebody's
 * model budget on a question they were only reading.
 *
 * NOTHING RENDERS IF THERE ARE NONE. A deployment that marks no
 * example for display gets no empty heading -- the feature is
 * optional, and a panel announcing an empty list is worse than a panel
 * that stays quiet.
 */

import Action from '@elysium/shell-api/components/Action'

export default function ExampleQuestions({
  questions,
  onPick,
}: {
  questions: string[]
  onPick: (question: string) => void
}) {
  if (questions.length === 0) return null

  return (
    <section className="query__examples" aria-label="Example questions">
      <p className="query__examples-lede">Try one of these:</p>
      <ul>
        {questions.map((question) => (
          <li key={question}>
            <Action text={question} onClick={() => onPick(question)} />
          </li>
        ))}
      </ul>
    </section>
  )
}
