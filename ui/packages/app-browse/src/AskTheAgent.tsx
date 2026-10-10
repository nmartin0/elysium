/**
 * A way into the agent from whatever you are already looking at.
 *
 * DEV_UI.md section 4 names the symptom: "the agent lives in its own
 * app, so a question about what you are looking at means starting
 * again in another tab, describing in words what was already on
 * screen." Section 5 item 4 names the fix -- "THE AGENT EVERYWHERE" --
 * and calls it "Elysium's actual edge over the prior art, where AI
 * sits alongside rather than inside".
 *
 * EXTRACTED AT THE SECOND CALLER, which is this project's rule and not
 * a guess at a third. The set had one of these; the object page needed
 * the same link with a different sentence, and the part worth sharing
 * turned out to be only the link -- where it goes, how the subject is
 * carried, and the decision not to write the question.
 *
 * THE PHRASING STAYS WITH THE CALLER, deliberately. Describing a set
 * and describing one object are different judgements, each worth its
 * own test, and a single component taking a `kind` prop would have
 * meant one body with two unrelated halves.
 *
 * IT SEEDS A SUBJECT, NOT A QUESTION. The link carries a phrase naming
 * what is on screen and leaves the cursor after it, because the person
 * knows what they want to ask and the interface does not. Writing them
 * a whole question would mean guessing, and a guessed question that
 * reads plausibly is worse than an empty box -- somebody presses Ask
 * on it.
 *
 * THE URL IS THE CARRIER, which is the same reason a set's filters
 * live there. Nothing is stored, nothing is coordinated between the
 * two apps, and the result is a link somebody can send.
 */

import { Link } from 'react-router-dom'

export default function AskTheAgent({ subject, children }: { subject: string; children: React.ReactNode }) {
  return (
    <Link className="ask-the-agent" to={`/query?q=${encodeURIComponent(subject)}`}>
      {children}
    </Link>
  )
}
