/**
 * Action -- a button, with this application's defaults already applied.
 *
 * WHY THIS EXISTS, and it is not the reason usually given. The common
 * argument for wrapping a component library is that it lets you swap
 * the library later. The literature is blunt that this is the weak
 * case: "the main benefit comes from the reduced complexity and the
 * gained consistency of reducing the used API surface of the external
 * library". Swappability is a side effect, not the point.
 *
 * THE EVIDENCE HERE IS SPECIFIC. `<Button>` appears 36 times across
 * the screens. Twenty-one of those pass `small`. Sixteen pass
 * `minimal`. The house style was already decided -- it was just being
 * retyped at every call site, which is how a style drifts: somebody
 * forgets one, and now there are two sizes of button on one screen and
 * no rule that says which is wrong.
 *
 * SO THE DEFAULTS LIVE HERE. `<Action text="Save" />` is a small,
 * minimal button because that is what this application's buttons are.
 * The variants below are the three cases that genuinely differ.
 *
 * WHAT THIS DELIBERATELY DOES NOT DO: mirror Blueprint's prop surface.
 * A wrapper that forwards everything "will just become a copy of the
 * component and thus not be helpful at all" -- it adds a file, a name
 * to learn, and no constraint. Anything not expressible here should
 * import Blueprint directly and say why in a comment; that is a
 * legitimate escape hatch, not a failure.
 */

import { Button } from '@blueprintjs/core'
import type { ButtonProps } from '@blueprintjs/core'

/** NOT `variant`. Blueprint 6 already has a `variant` prop on Button
 *  with its own meaning, so reusing the name collides on the type and
 *  would confuse anybody who knows the library. `tone` says what this
 *  one is for: how loud the action should be. */
export type ActionTone =
  /** The default. Small and minimal: toolbar actions, row actions,
   *  anything that sits inside dense content. */
  | 'quiet'
  /** The one action a screen wants you to take. At most one per view. */
  | 'primary'
  /** Destructive and irreversible. Deleting, revoking, rejecting. */
  | 'danger'

interface ActionProps extends Omit<ButtonProps, 'intent' | 'minimal' | 'small'> {
  tone?: ActionTone
}

export default function Action({ tone = 'quiet', ...rest }: ActionProps) {
  if (tone === 'primary') {
    return <Button intent="primary" small {...rest} />
  }
  if (tone === 'danger') {
    return <Button intent="danger" small {...rest} />
  }
  return <Button minimal small {...rest} />
}
