/**
 * Hand the agent the object that is on screen.
 *
 * DEV_UI.md section 5 item 4 is "THE AGENT EVERYWHERE", and the object
 * page was the half that did not have it. Item 3 says why this is the
 * page that needs it: "THE OBJECT VIEW AS A HUB: properties, links,
 * history, notes, provenance and the actions available on THIS object,
 * together." A hub you have to leave in order to ask a question about
 * what is in it is not one.
 *
 * NO FIELD VALUES IN THE SUBJECT, INCLUDING THE TITLE, and this is the
 * one real decision in the file.
 *
 * The obvious sentence names the object the way the page does -- "the
 * Customer cust_001 (Ada Okafor)" -- and it is the wrong sentence. The
 * title is a FIELD VALUE, and this subject travels in a URL somebody
 * can paste into a chat. A reader without the grant would learn from
 * the link alone that cust_001 is Ada Okafor, which is exactly the
 * inference the field table refuses to allow when it renders "Not
 * permitted" instead of a value.
 *
 * It is also the rule `AskAboutSet` already follows for the same
 * reason: it passes the type and the COUNT of filters, never the
 * filter values. The type and the id are already in the page's own
 * address, so the subject tells a recipient nothing the link they were
 * sent did not.
 *
 * THE AGENT LOSES NOTHING BY THIS. It resolves the object through the
 * ontology under the ASKER'S grants, so if they may read the title it
 * will find the title -- and if they may not, a title pasted into the
 * question would not have entitled them to it anyway.
 */

import AskTheAgent from './AskTheAgent'

export default function AskAboutObject({ objectType, objectId }: { objectType: string; objectId: string }) {
  const subject = `About the ${objectType} object ${objectId}: `

  return <AskTheAgent subject={subject}>Ask about this object</AskTheAgent>
}
