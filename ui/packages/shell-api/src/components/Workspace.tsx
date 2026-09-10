/**
 * Workspace.tsx -- the two-pane layout every sub-app can use.
 *
 * Configuration on the left, content on the right, both filling the
 * shell and scrolling independently. That is the cloud-console shape:
 * a slim rail for top-level sections, a pane whose contents swap with
 * the selection, and the work area.
 *
 * A COMPONENT RATHER THAN CSS CLASSES, and the difference matters.
 * Browse built this by hand from `workspace`, `workspace__config` and
 * `workspace__content`, which meant the structure was remembered
 * rather than enforced -- three class names in the right nesting, or
 * the panes silently stop filling the shell and stop scrolling.
 *
 * It also lets the stylesheet stop guessing. `main` had to detect a
 * workspace with `:has(.workspace)` to decide whether to supply its
 * own padding; a component can say so.
 *
 * NOT EVERY SUB-APP WANTS TWO PANES, and none is forced to. Query is
 * a prompt and an answer; a configuration column would be an empty
 * box. Sub-apps that have controls worth separating from content use
 * this; the rest render into the canvas directly and keep the
 * padding `main` gives them.
 */

import type { ReactNode } from 'react'

interface WorkspaceProps {
  /** The left pane: filters, pickers, anything that CHANGES what the
   *  content shows. Omit it for a single-pane sub-app. */
  config?: ReactNode
  children: ReactNode
}

export default function Workspace({ config, children }: WorkspaceProps) {
  if (config === undefined) {
    return <section className="workspace__content workspace--single">{children}</section>
  }
  return (
    <div className="workspace">
      {/* aside, not div: this is complementary to the content beside
          it, and a screen reader should be able to skip it. */}
      <aside className="workspace__config" aria-label="Filters and options">
        {config}
      </aside>
      <section className="workspace__content">{children}</section>
    </div>
  )
}

/**
 * One labelled control in the configuration pane.
 *
 * A narrow column reads DOWN, so the label sits above its control
 * rather than beside it. Extracted because every filter in every
 * sub-app wants the same thing, and three of them writing the same
 * div-and-label by hand is how the spacing drifts.
 */
export function WorkspaceFilter({
  label,
  htmlFor,
  children,
}: {
  label: string
  htmlFor?: string
  children: ReactNode
}) {
  return (
    <div className="workspace__filter">
      <label htmlFor={htmlFor}>{label}</label>
      {children}
    </div>
  )
}
