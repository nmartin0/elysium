/**
 * Which actions a trigger on this view may propose, and which roles it
 * may notify. Pure functions, so the rules are testable apart from the
 * dialog that shows them.
 *
 * THE SAME RULES THE SERVER ENFORCES, applied early. The server still
 * checks every one when the trigger is created and again when it
 * fires -- these exist so the dialog OFFERS only what will be accepted,
 * rather than offering everything and showing a refusal afterwards.
 */

interface ActionParameter {
  type?: string
  object_type?: string
  required?: boolean
  display_name?: string
}

export interface VisibleAction {
  affected_object_types?: string[]
  parameters?: Record<string, ActionParameter>
  executable?: boolean
  automatable?: boolean
}

export interface ActionChoice {
  name: string
  /** Parameters that can receive what the view matches. */
  targets: string[]
  /** The other parameters, which the person fills in once. */
  others: Array<[string, ActionParameter]>
}

const OBJECT_PARAMETERS = new Set(['object_reference', 'object_reference_list'])

/** Actions a trigger watching `objectType` could propose.
 *
 *  THREE RULES, each one the server's:
 *    - the person can run it themselves (a trigger grants nothing
 *      its owner lacks)
 *    - it does not declare automatable: false
 *    - some parameter takes objects of the view's type, to receive
 *      what the view matched
 */
export function actionsFor(actions: Record<string, VisibleAction>, objectType: string): ActionChoice[] {
  const choices: ActionChoice[] = []
  for (const [name, action] of Object.entries(actions)) {
    if (action.executable !== true) continue
    if (action.automatable === false) continue
    const parameters = Object.entries(action.parameters ?? {})
    const targets = parameters
      .filter(([, parameter]) => OBJECT_PARAMETERS.has(parameter.type ?? '') && parameter.object_type === objectType)
      .map(([parameterName]) => parameterName)
    if (targets.length === 0) continue
    choices.push({
      name,
      targets,
      others: parameters.filter(([parameterName]) => !targets.includes(parameterName)),
    })
  }
  return choices.sort((a, b) => a.name.localeCompare(b.name))
}

/** Roles this person may name as recipients.
 *
 *  FOUNDRY'S RULE: name only groups you have permission to see. In
 *  Elysium role names are visible to manage:users holders -- and
 *  `allRoles` is null for anybody else, because /config refused them.
 *  So: every role if they can see them all, otherwise their own.
 */
export function rolesFor(ownRole: string | null, allRoles: string[] | null): string[] {
  if (allRoles !== null) return [...allRoles].sort()
  return ownRole === null ? [] : [ownRole]
}
