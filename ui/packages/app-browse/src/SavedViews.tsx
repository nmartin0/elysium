/**
 * SavedViews -- name the thing you are looking at, and come back to it.
 *
 * A view already lives in the URL, so this stores a string and a name.
 * See savedViews.ts for why it is personal rather than shared: sharing
 * is already solved by sending the link, and what this answers is "the
 * thing I set up on Tuesday, where did it go".
 *
 * A POPOVER RATHER THAN A PANEL. Saving is a momentary act and the
 * list is short; a permanent sidebar section would spend space on
 * something most people touch once a week. It sits beside the other
 * workspace controls because that is where choices about THIS VIEW
 * already are.
 */

import { Button, InputGroup, Menu, MenuDivider, MenuItem, Popover } from '@blueprintjs/core'
import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import { deleteView, listSavedViews, saveView, type SavedView } from '@elysium/shell-api/savedViews'

interface SavedViewsProps {
  username: string
}

export default function SavedViews({ username }: SavedViewsProps) {
  const location = useLocation()
  const navigate = useNavigate()
  const [views, setViews] = useState<SavedView[]>(() => listSavedViews(username))
  const [name, setName] = useState('')
  const [open, setOpen] = useState(false)

  const currentUrl = `${location.pathname}${location.search}`
  // THE NAME OF A VIEW ALREADY SAVED AT THIS URL, so re-opening the
  // popover on a view you saved offers to update it rather than
  // silently making a second copy under a new name.
  const existing = views.find((view) => view.url === currentUrl)

  function save() {
    setViews(saveView(username, name, currentUrl))
    setName('')
    setOpen(false)
  }

  return (
    <Popover
      isOpen={open}
      onInteraction={(next) => {
        setOpen(next)
        // Prefilled with the existing name when there is one, so the
        // obvious action on an already-saved view is to update it.
        if (next) setName(existing?.name ?? '')
      }}
      content={
        <Menu className="saved-views__menu">
          <div className="saved-views__save">
            <InputGroup
              placeholder="Name this view…"
              value={name}
              onChange={(event) => setName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') save()
              }}
            />
            <Button small intent="primary" disabled={name.trim() === ''} onClick={save}>
              {existing && existing.name === name.trim() ? 'Update' : 'Save'}
            </Button>
          </div>

          {views.length > 0 && <MenuDivider title="Saved" />}
          {views.map((view) => (
            <MenuItem
              key={view.name}
              text={view.name}
              // ACTIVE when you are already looking at it, so the list
              // says where you are rather than only where you could go.
              active={view.url === currentUrl}
              onClick={() => {
                navigate(view.url)
                setOpen(false)
              }}
              labelElement={
                <Button
                  small
                  minimal
                  icon="cross"
                  aria-label={`Forget ${view.name}`}
                  onClick={(event) => {
                    // Not the MenuItem's own click, or forgetting a
                    // view would navigate to it first.
                    event.stopPropagation()
                    setViews(deleteView(username, view.name))
                  }}
                />
              }
            />
          ))}
        </Menu>
      }
    >
      <Button icon="bookmark" small>
        {existing ? existing.name : 'Saved views'}
      </Button>
    </Popover>
  )
}
