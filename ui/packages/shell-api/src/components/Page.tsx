/**
 * The frame every screen sits in.
 *
 * WHY THE APPLICATION FEELS LIKE ISLANDS. Measured across the ten
 * panels: three open with a heading and seven open with nothing, four
 * have no wrapping element at all, and the three that do have titles
 * use an `h2`, an `h3` and a `div` respectively. There is a navigation
 * rail and then six unrelated interiors.
 *
 * That is a STRUCTURE problem rather than a craft one, and the
 * distinction matters -- DEV_UI.md's own diagnosis is that treating
 * them as one fault "is how a redesign fails: new paint on the same
 * dead ends, or a new structure that still looks like a prototype".
 * The type scale fixed paint. This is the structure, and it is
 * deliberately the smallest version that works: a title, an optional
 * one-line description, one slot for a primary action, and consistent
 * padding. No chrome, no breadcrumb, no tabs.
 *
 * ONE PRIMARY ACTION, IN ONE PLACE. The convention is explicit --
 * "if you have a primary action button, place it in the same location
 * on every screen" -- and the slot is singular on purpose. A page
 * wanting two primary actions has not decided which one it is for.
 *
 * IT COMPOSES WITH `Workspace`, IT DOES NOT REPLACE IT. Five panels
 * already use Workspace for the configuration-beside-content split,
 * and that is the right shape for them -- the gap was never a missing
 * frame, it was that Workspace handles the two-pane LAYOUT and nothing
 * handled the page HEADER. A screen with filters puts Workspace inside
 * Page; a screen without, like this one's first adopter, puts its
 * content there directly.
 *
 * WHAT THIS DOES NOT DO is decide what the application is ABOUT. The
 * rail still lists seven peers with Query first, and whether the
 * ontology should be the centre with everything else supporting it is
 * a product decision, not a component's.
 */

import type { ReactNode } from 'react'

export default function Page({
  title,
  description,
  action,
  children,
}: {
  title: string
  /** One line. Says what this screen is for, to somebody who has just
   *  arrived and does not know. Omit it rather than write filler. */
  description?: string
  /** The single most important thing a person can do here. */
  action?: ReactNode
  children: ReactNode
}) {
  return (
    <div className="page">
      <header className="page__head">
        <div className="page__heading">
          <h1 className="page__title">{title}</h1>
          {description && <p className="page__description">{description}</p>}
        </div>
        {action && <div className="page__action">{action}</div>}
      </header>
      <div className="page__body">{children}</div>
    </div>
  )
}
