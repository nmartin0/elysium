/**
 * The whole product as search, on Cmd/Ctrl-K.
 *
 * DEV_UI.md section 5 item 8: "A COMMAND PALETTE AND GLOBAL SEARCH.
 * Keyboard-first is most of what makes a tool feel like a tool." And
 * 10.1 on why this product needs one rather than a bigger menu: "menus
 * do not scale. Elysium has object types, saved views, actions per
 * type, admin functions and an agent. A sidebar cannot hold that, and a
 * submenu tree is a memory test."
 *
 * AVAILABLE EVERYWHERE, which is Superhuman's own guidance and the
 * reason this lives in the shell rather than in a sub-app. A palette
 * that works on four screens out of seven is one people stop reaching
 * for.
 *
 * UNDER 100ms OR IT WILL NOT BE USED -- 10.1 again, and the reason this
 * filters a list already in memory rather than asking the server. Every
 * command here comes from data the shell has already fetched. A palette
 * that waits on a round trip has lost the thing it was for, and a
 * global SEARCH that does ask the server belongs beside this rather
 * than inside it.
 *
 * DISABLED WITH THE REASON, NOT HIDDEN. A command the caller cannot run
 * is listed, greyed, with its sentence beside it. Hiding it is the
 * easier code and the worse interface: somebody who knows a command
 * exists and cannot find it concludes the product is broken.
 */

import { useMemo, useState } from 'react'
import { Dialog, DialogBody } from '@blueprintjs/core'

import { type Command, matching } from '../commands'

export default function CommandPalette({
  commands,
  isOpen,
  onClose,
}: {
  commands: Command[]
  isOpen: boolean
  onClose: () => void
}) {
  return (
    <Dialog
      isOpen={isOpen}
      onClose={onClose}
      title="Go to"
      className="command-palette"
      /* A PORTAL CLASS SO THE CONTAINER CAN BE REACHED. Blueprint
         centres a dialog with flex on `.bp6-dialog-container`, which
         `className` does not touch -- it lands on the dialog itself, so
         a top margin there only offsets the centre. Measured in a
         browser: 108px of margin moved it 38px.

         Every other dialog in the app should stay centred, so the rule
         is scoped to this portal rather than written against the
         container globally. */
      portalClassName="command-palette-portal"
      /* NO BACKDROP CLICK TRAP AND NO CONFIRMATION. Escape closes it,
         which Dialog handles, and nothing here is destructive -- 10.1
         reserves confirmation for "genuinely serious, rare actions",
         and a palette that asked twice would not be used once. */
    >
      {/* THE STATE LIVES IN THE BODY, NOT OUT HERE, and that is what
          makes a fresh open fresh. Blueprint's overlay does not render
          its children until it opens and unmounts them when it closes,
          so the query and the highlight are new every time without a
          reset effect reaching for them.

          IT WAS AN EFFECT FIRST, and the linter was right to refuse it:
          "update it from the event that caused the change". The event
          that causes a reset here is the open itself, and a mount IS
          that event. */}
      <PaletteBody commands={commands} onClose={onClose} />
    </Dialog>
  )
}

function PaletteBody({ commands, onClose }: { commands: Command[]; onClose: () => void }) {
  const [query, setQuery] = useState('')
  const [highlighted, setHighlighted] = useState(0)

  const hits = useMemo(() => matching(commands, query), [commands, query])

  const choose = (command: Command) => {
    if (command.unavailable) return
    onClose()
    command.run()
  }

  // A NEW QUERY STARTS AT THE TOP. Keeping the old index means the
  // highlight lands on whatever happens to be in that position now,
  // which is how somebody runs the wrong command. Done here rather than
  // in an effect watching `query`: typing is the event that causes it.
  const retype = (next: string) => {
    setQuery(next)
    setHighlighted(0)
  }

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setHighlighted((at) => Math.min(at + 1, hits.length - 1))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setHighlighted((at) => Math.max(at - 1, 0))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      const command = hits[highlighted]
      if (command) choose(command)
    }
  }

  return (
    <DialogBody>
      <input
        className="command-palette__query"
        type="text"
        autoFocus
        value={query}
        placeholder="Search for a screen, a type, a command…"
        aria-label="Search commands"
        onChange={(event) => retype(event.target.value)}
        onKeyDown={onKeyDown}
      />
      {hits.length === 0 ? (
        <p className="command-palette__empty">Nothing matches that.</p>
      ) : (
        <ul className="command-palette__results" role="listbox">
          {hits.map((command, index) => (
            <li
              key={command.id}
              role="option"
              aria-selected={index === highlighted}
              aria-disabled={Boolean(command.unavailable)}
              className={
                'command-palette__hit' +
                (index === highlighted ? ' command-palette__hit--on' : '') +
                (command.unavailable ? ' command-palette__hit--off' : '')
              }
              onMouseEnter={() => setHighlighted(index)}
              onClick={() => choose(command)}
            >
              <span className="command-palette__group">{command.group}</span>
              <span className="command-palette__label">{command.label}</span>
              {/* THE REASON, BESIDE THE COMMAND. This is the whole
                  point of listing it rather than hiding it. */}
              {command.unavailable && <span className="command-palette__why">{command.unavailable}</span>}
            </li>
          ))}
        </ul>
      )}
    </DialogBody>
  )
}
