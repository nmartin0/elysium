/**
 * Hand the agent the set that is on screen.
 *
 * DEV_UI.md section 5 item 4: "'ask about this set' inside Browse,
 * seeded with what is on screen."
 *
 * The link itself, and the reasoning behind seeding a subject rather
 * than a question, are in `AskTheAgent`. What is here is the sentence
 * -- how you describe a set out loud.
 *
 * WHAT IT DOES NOT DO is pass the filters themselves. The agent
 * resolves questions through the ontology under the asker's own
 * grants; handing it a filter expression would be asking it to trust a
 * client. The phrase describes the set in words, and the agent answers
 * it the way it answers any other question -- which is also why the
 * answer can differ from the rows on screen when the two readers
 * differ.
 */

import AskTheAgent from './AskTheAgent'

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

  return <AskTheAgent subject={subject}>Ask about this set</AskTheAgent>
}
