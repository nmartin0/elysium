// The System sub-app's Server page (step 3): the five server views split
// out of Admin, each tested in its own file under ./server; this is the
// page that chooses between them.
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'

vi.mock('./server/DeploymentConfig', () => ({ default: () => <p>deployment view</p> }))
vi.mock('./server/Silos', () => ({ default: () => <p>silos view</p> }))
vi.mock('./server/MetricsPanel', () => ({ default: () => <p>metrics view</p> }))
vi.mock('./server/MirrorPanel', () => ({ default: () => <p>mirror view</p> }))
vi.mock('./server/RuleSuggestions', () => ({ default: () => <p>cleaning view</p> }))

const { default: ServerPage } = await import('./ServerPage')

function Where() {
  const location = useLocation()
  return <output aria-label="where">{location.search}</output>
}

function show(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route
          path="/system/server"
          element={
            <>
              <ServerPage onSessionExpired={vi.fn()} />
              <Where />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  )
}

describe('the Server page', () => {
  it("offers the server's five views, and opens on Deployment", () => {
    show('/system/server')

    for (const name of ['Deployment', 'Silos', 'Metrics', 'Mirror', 'Cleaning']) {
      expect(screen.getByRole('button', { name: new RegExp(name) })).toBeInTheDocument()
    }
    expect(screen.getByText('deployment view')).toBeInTheDocument()
  })

  it('opens the view the URL names, so a link to the mirror is a link', () => {
    show('/system/server?view=mirror')

    expect(screen.getByText('mirror view')).toBeInTheDocument()
    expect(screen.queryByText('deployment view')).not.toBeInTheDocument()
  })

  it('puts the chosen view in the URL', () => {
    show('/system/server')

    fireEvent.click(screen.getByRole('button', { name: /Silos/ }))

    expect(screen.getByText('silos view')).toBeInTheDocument()
    expect(screen.getByLabelText('where')).toHaveTextContent('view=silos')
  })

  it('an unknown view is Deployment, not an empty page', () => {
    show('/system/server?view=nonsense')

    expect(screen.getByText('deployment view')).toBeInTheDocument()
  })
})
