import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { CONTRACT_VERSION } from './contract'
import { moduleRoutes, type PageResolver } from './ModuleRoutes'
import { buildRegistry } from './registry'

const registry = buildRegistry({
  contract: CONTRACT_VERSION,
  home: '/here',
  modules: [
    {
      id: 'here',
      name: 'Here',
      version: '1',
      entry: null,
      contributes: { pages: [{ id: 'main', path: '/here' }], redirects: [{ from: '/was', to: '/here' }] },
    },
    { id: 'gone', name: 'Gone', version: '1', entry: null, contributes: { pages: [{ id: 'main', path: '/gone' }] } },
  ],
})

const resolve: PageResolver = (moduleId) => (moduleId === 'here' ? () => <p>the page here</p> : null)

function at(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>{moduleRoutes(registry, resolve, '/here')}</Routes>
    </MemoryRouter>,
  )
}

describe('moduleRoutes', () => {
  it('mounts the page the host resolves', () => {
    at('/here')

    expect(screen.getByText('the page here')).toBeInTheDocument()
  })

  it('says nothing opens a page whose module the host cannot find', () => {
    at('/gone')

    expect(screen.getByRole('status')).toHaveTextContent(/belongs to the module gone/)
  })

  it('follows an old address to its new one', () => {
    at('/was')

    expect(screen.getByText('the page here')).toBeInTheDocument()
  })

  it('sends an unknown address home', () => {
    at('/nowhere')

    expect(screen.getByText('the page here')).toBeInTheDocument()
  })

  it('does not send an address to a home nothing mounts, which would loop', () => {
    render(
      <MemoryRouter initialEntries={['/nowhere']}>
        <Routes>{moduleRoutes(registry, resolve, '/admin')}</Routes>
      </MemoryRouter>,
    )

    expect(screen.getByRole('status')).toHaveTextContent('Nothing loaded opens this page.')
  })
})
