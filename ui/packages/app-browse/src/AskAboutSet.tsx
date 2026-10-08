/**
 * Hand the agent the set that is on screen.
 *
 * DEV_UI.md section 4 names the symptom: "the agent lives in its own
 * app, so a question about what you are looking at means starting again
 * in another tab, describing in words what was already on screen."
 *
 * And section 5 item 4 names the fix: "THE AGENT EVERYWHERE: 'ask about
 * this set' inside Browse, seeded with what is on screen. Elysium's
 * actual edge over the prior art, where AI sits alongside rather than
 * inside."
 *
 * IT SEEDS A SUBJECT, NOT A QUESTION. The link carries a phrase naming
 * what is on screen and leaves the cursor after it, because the person
 * knows what they want to ask and the interface does not. Writing them
 * a whole question would mean guessing, and a guessed question that
 * reads plausibly is worse than an empty box -- somebody presses Ask on
 * it.
 *
 * THE URL IS THE CARRIER, which is the same reason the set's filters
 * live there. Nothing is stored, nothing is coordinated between the two
 * apps, and the result is a link somebody can send.
 *
 * WHAT IT DOES NOT DO is pass the filters themselves. The agent resolves
 * questions through the ontology under the asker's own grants; handing
 * it a filter expression would be asking it to trust a client. The
 * phrase describes the set in words, and the agent answers it the way
 * it answers any other question -- which is also why the answer can
 * differ from the rows on screen when the two readers differ.
 */

import { Link } from 'react-router-dom'

export default function AskAboutSet({
  objectType,
  filterCount,
  total,
}: {
  objectType: string | null
  filterCount: number
  total: number
}) {
  if (!objectType) return null

  const narrowed = filterCount > 0 ? ` matching ${filterCount} filter${filterCount === 1 ? '' : 's'}` : ''
  const subject = `About the ${total.toLocaleString()} ${objectType} objects${narrowed}: `

  return (
    <Link className="ask-about-set" to={`/query?q=${encodeURIComponent(subject)}`}>
      Ask about this set
    </Link>
  )
}
