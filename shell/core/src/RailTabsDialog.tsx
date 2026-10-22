/**
 * CHOOSING ONE'S OWN RAIL TABS (BLOCKING.md item 3, step 1.4d): a person
 * hides tabs they do not use, for themselves alone. The owner's choice,
 * 22 October: BOTH, SEPARATELY -- the module manager turns modules on and
 * off for everyone; this only tidies one person's rail.
 *
 * THE RAIL ONLY: a hidden tab's pages stay where they were -- the palette
 * still offers them and their addresses still open them -- so hiding is
 * never a way to lose something. Pinned tabs cannot be hidden: the
 * system's own tools stay in reach, as in safe mode.
 *
 * APPLIED AS TICKED, like the theme and the row density: a preference,
 * with nothing to save and nothing to get wrong.
 */
import { Checkbox, Dialog, DialogBody } from '@blueprintjs/core'

export interface RailTab {
  title: string
  path: string
  /** Whether it belongs to a pinned module, and so cannot be hidden. */
  pinned: boolean
}

export function RailTabsDialog({
  isOpen,
  onClose,
  tabs,
  hidden,
  onChange,
}: {
  isOpen: boolean
  onClose: () => void
  tabs: readonly RailTab[]
  hidden: ReadonlySet<string>
  onChange: (hidden: ReadonlySet<string>) => void
}) {
  const toggle = (path: string, shown: boolean) => {
    const next = new Set(hidden)
    if (shown) next.delete(path)
    else next.add(path)
    onChange(next)
  }
  return (
    <Dialog isOpen={isOpen} onClose={onClose} title="Your rail tabs">
      <DialogBody>
        <p>
          Untick a tab you do not use to take it off your rail. Its pages stay in the command palette and at their
          addresses; nobody else&apos;s rail changes.
        </p>
        {tabs.map((tab) => (
          <Checkbox
            key={tab.path}
            label={tab.pinned ? `${tab.title} (the system's own; always shown)` : tab.title}
            checked={tab.pinned || !hidden.has(tab.path)}
            disabled={tab.pinned}
            onChange={(event) => toggle(tab.path, event.currentTarget.checked)}
          />
        ))}
      </DialogBody>
    </Dialog>
  )
}
