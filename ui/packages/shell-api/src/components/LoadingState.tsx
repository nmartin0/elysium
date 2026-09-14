/**
 * LoadingState -- one treatment for "the data has not arrived yet".
 *
 * THREE TREATMENTS EXISTED, across six components. `<p>Loading…</p>`
 * in ObjectDetailPanel, ObjectSearchPanel and AdminPanel; `<Spinner />`
 * in AsyncPanel and SchemaPanel; `<Spinner size={20} />` in
 * WriteDetail. ObjectDetailPanel's own comment claimed a plain
 * "Loading…" was "matching every other data-fetching component's own
 * existing convention", which was true when written and had stopped
 * being true.
 *
 * NEITHER EXISTING TREATMENT WAS RIGHT, which is why this is a new
 * component rather than a vote between them.
 *
 * A bare Spinner announces NOTHING to a screen reader: Blueprint
 * renders an svg, and an svg with no accessible name is invisible to
 * assistive technology. A reader using one would sit in silence with
 * no way to tell a slow request from a finished empty one.
 *
 * Plain text announces, and shows no progress -- on hardware where a
 * query runs for minutes, a motionless "Loading…" reads as a hung
 * page.
 *
 * So: both. The spinner for anyone watching, the label for anyone
 * listening, and role="status" so it is announced when it appears
 * rather than only when focused.
 */

import { Spinner } from '@blueprintjs/core'

interface LoadingStateProps {
  /** What is being waited for, if a page has more than one thing in
   *  flight. "Loading…" alone is fine when there is only one. */
  label?: string
  /** Small for an inline region -- a row expanding, a card's detail.
   *  The default suits a whole panel. */
  inline?: boolean
}

export default function LoadingState({ label = 'Loading…', inline = false }: LoadingStateProps) {
  return (
    <div className="loading-state" role="status">
      <Spinner size={inline ? 20 : undefined} />
      {/* VISUALLY HIDDEN, NOT display:none. A screen reader skips
          anything display:none hides, so the label has to stay in the
          layout and out of sight -- see .visually-hidden in
          index.css. */}
      <span className="visually-hidden">{label}</span>
    </div>
  )
}
