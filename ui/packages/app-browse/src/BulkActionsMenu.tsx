/**
 * BulkActionsMenu -- which actions can be applied to a selection.
 *
 * THE ONTOLOGY DECIDES WHAT APPEARS, not this component. Foundry: "in
 * 'bulk' contexts... only actions that accept object list parameters
 * of the correct type will be shown". An action without an
 * object_reference_list parameter for THIS object type is not a bulk
 * action, and no amount of UI makes it one -- the write mediator would
 * refuse it, and offering it would be an invitation to a refusal.
 *
 * OF THE CORRECT TYPE matters as much as the list-ness. An action
 * taking a list of Customers must not appear on a list of
 * Transactions; the ids would be accepted by the form and rejected at
 * the far end, after someone had filled in a whole form.
 *
 * ABSENT RATHER THAN DISABLED when nothing qualifies. A disabled menu
 * invites a person to work out what would enable it, and the answer
 * here is "the ontology would have to declare a different action",
 * which is not something they can do from this screen.
 */

import { Button, Menu, MenuItem, Popover } from '@blueprintjs/core'

import { listParameterOf } from './BulkActionForm'

export interface BulkAction {
  name: string
  display_name?: string
  parameters?: Record<string, { type: string; object_type?: string }>
}

interface BulkActionsMenuProps {
  actions: BulkAction[]
  objectType: string
  /** How many objects would be acted on, for the button's own label --
   *  the same number the selection bar shows, restated where the
   *  decision is actually made. */
  count: number
  onChoose: (action: BulkAction) => void
}

export default function BulkActionsMenu({ actions, objectType, count, onChoose }: BulkActionsMenuProps) {
  const applicable = actions.filter((action) => listParameterOf(action as never, objectType) !== null)

  if (applicable.length === 0) return null

  return (
    <Popover
      content={
        <Menu>
          {applicable.map((action) => (
            <MenuItem key={action.name} text={action.display_name ?? action.name} onClick={() => onChoose(action)} />
          ))}
        </Menu>
      }
      placement="bottom-start"
    >
      <Button minimal icon="play" rightIcon="caret-down">
        Actions ({count})
      </Button>
    </Popover>
  )
}
