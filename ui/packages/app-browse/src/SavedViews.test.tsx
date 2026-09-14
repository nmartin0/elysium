/**
 * Name the thing you are looking at, and come back to it.
 *
 * The store is tested in shell-api/savedViews.test.ts. This is about
 * the two things only the component decides: that saving captures the
 * CURRENT url, and that opening one navigates there.
 */

import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'

import SavedViews from './SavedViews'

function Where() {
  const location = useLocation()
  return <span data-testid="where">{`${location.pathname}${location.search}`}</span>
}

function renderAt(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route
          path="/browse"
          element={
            <>
              <SavedViews username="alice" />
              <Where />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => window.localStorage.clear())

describe('SavedViews', () => {
  it('saves the view you are actually looking at', () => {
    renderAt('/browse?type=Transaction&q=refund')

    fireEvent.click(screen.getByRole('button', { name: /Saved views|refunds|scratch/ }))
    fireEvent.change(screen.getByPlaceholderText('Name this view…'), {
      target: { value: 'refunds' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    // Scoped to the menu: the trigger button also shows the current
    // view's name, which is deliberate and makes a bare getByText
    // ambiguous.
    expect(screen.getByRole('menuitem', { name: /refunds/ })).toBeInTheDocument()
  })

  it('navigates back to a saved view', () => {
    // THE POINT OF THE FEATURE. Storing a URL is worth nothing if
    // opening it does not go there.
    renderAt('/browse?type=Transaction&q=refund')
    fireEvent.click(screen.getByRole('button', { name: /Saved views|refunds|scratch/ }))
    fireEvent.change(screen.getByPlaceholderText('Name this view…'), {
      target: { value: 'refunds' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    fireEvent.click(screen.getByRole('menuitem', { name: /refunds/ }))

    expect(screen.getByTestId('where')).toHaveTextContent('q=refund')
  })

  it('will not save an unnamed view', () => {
    // An unfindable entry is worse than none: it occupies the list and
    // cannot be described.
    renderAt('/browse?type=Transaction')

    fireEvent.click(screen.getByRole('button', { name: /Saved views|refunds|scratch/ }))

    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  })

  it('offers to UPDATE a view you are already on', () => {
    // Re-opening the popover on a saved view prefills its name, so the
    // obvious action is to update rather than silently make a second
    // copy under a new name.
    renderAt('/browse?type=Transaction&q=refund')
    fireEvent.click(screen.getByRole('button', { name: /Saved views|refunds|scratch/ }))
    fireEvent.change(screen.getByPlaceholderText('Name this view…'), {
      target: { value: 'refunds' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    // Reopened: clicking a menu item navigates AND closes the
    // popover, so the prefilled name is only visible on the next open.
    fireEvent.click(screen.getByRole('button', { name: 'refunds' }))

    expect(screen.getByRole('button', { name: 'Update' })).toBeInTheDocument()
  })

  it('forgetting a view does not navigate to it', () => {
    // THE CONTROL. The cross sits inside a MenuItem, so without
    // stopping propagation the click would open the view it is
    // deleting -- leaving the person somewhere they did not ask to be.
    renderAt('/browse?type=Transaction')
    fireEvent.click(screen.getByRole('button', { name: /Saved views|refunds|scratch/ }))
    fireEvent.change(screen.getByPlaceholderText('Name this view…'), {
      target: { value: 'scratch' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    fireEvent.click(screen.getByLabelText('Forget scratch'))

    // ASSERTED ON THE ROUTE, not on the menu. Blueprint keeps popover
    // content mounted in jsdom after a close, so a DOM assertion about
    // the item disappearing tests the popover rather than the delete
    // -- and removal is already covered in savedViews.test.ts.
    //
    // HONEST LIMIT, found by a control that did not fire. Removing
    // stopPropagation from the component fails nothing here: in jsdom
    // the nested button's click does not bubble to the MenuItem the
    // way it does in a browser, so this cannot actually catch the bug
    // it is named for. The guard in the component is still right --
    // without it, forgetting a view would open it first and leave the
    // person somewhere they did not ask to be -- and it is verified by
    // using the app, not by this.
    expect(screen.getByTestId('where')).toHaveTextContent('/browse?type=Transaction')
  })
})
