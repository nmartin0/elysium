/**
 * ViewSelector -- which view of a sub-app you are looking at.
 *
 * Lives in the configuration pane, above whatever else that pane
 * holds. Left to right, the shell reads general to specific: the rail
 * picks an APP, this picks a VIEW within it, and the canvas holds the
 * thing itself. That ordering is the point -- an interface that sends
 * you left, then up, then left again costs a decision at every hop.
 *
 * EXTRACTED WHEN THE SECOND CALLER ARRIVED, not the first. Admin built
 * this by hand and that was right; Schema needing the same thing is
 * what makes it a pattern rather than a guess about one.
 *
 * WHAT IT DELIBERATELY IS NOT: a router, a tab strip, or anything that
 * knows what a view CONTAINS. It renders a list and reports a choice.
 * A component that also decided what to show would have to know every
 * sub-app, which is the coupling the sub-app split exists to avoid.
 */

import { Button, ButtonGroup } from '@blueprintjs/core'
import type { IconName } from '@blueprintjs/icons'

export interface ViewOption {
  id: string
  label: string
  icon: IconName
}

interface ViewSelectorProps {
  views: readonly ViewOption[]
  selected: string
  onSelect: (id: string) => void
  /** Names the group for assistive technology. "View" is the default
   *  because that is what it selects; a sub-app with a more specific
   *  word should say so. */
  label?: string
}

export default function ViewSelector({ views, selected, onSelect, label = 'View' }: ViewSelectorProps) {
  return (
    <div className="workspace__filter">
      {/* A real label, not a heading. This names a group of controls,
          and a heading would put it in the document outline as a
          section that does not exist. */}
      <label id="view-selector-label">{label}</label>
      <ButtonGroup vertical alignText="left" fill aria-labelledby="view-selector-label">
        {views.map((view) => (
          <Button
            key={view.id}
            icon={view.icon}
            active={view.id === selected}
            /* aria-pressed, because `active` is a visual state that
               announces nothing. A selector whose current choice is
               invisible to a screen reader is a selector you cannot
               use without sight. */
            aria-pressed={view.id === selected}
            onClick={() => onSelect(view.id)}
          >
            {view.label}
          </Button>
        ))}
      </ButtonGroup>
    </div>
  )
}
