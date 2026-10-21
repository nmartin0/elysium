/**
 * The routes a registry asks for, as react-router elements.
 *
 * THE HOST FINDS THE CODE. `resolve(moduleId, pageId)` returns the
 * component for a page, or null when the host has none: a module built
 * into the page resolves from the host's own table, and one loaded from
 * a bundle from what its `activate` returned. The shell decides WHERE a
 * page is mounted; it never decides what the page is.
 *
 * NOTHING TO OPEN IT IS A STATE, NOT A CRASH. A link to a page whose
 * module is not loaded -- unloaded, refused, or simply not installed --
 * lands on a sentence saying so. Backstage's route references exist for
 * the same reason: a plugin links to another's page without knowing
 * whether it is there, and the app decides what happens.
 *
 * Returned as an array, to be spread into the host's own <Route> layout,
 * so the host keeps its frame and its sign-in guard around them.
 */
import type { ComponentType, ReactElement } from 'react'
import { Navigate, Route } from 'react-router-dom'
import type { Registry } from './registry'

export type PageResolver = (moduleId: string, pageId: string) => ComponentType | null

export function NothingOpensThis({ moduleId }: { moduleId: string }) {
  return (
    <div className="shell__nothing-opens-this" role="status">
      <p>
        Nothing loaded opens this page. It belongs to the module <code>{moduleId}</code>, which is not available here.
      </p>
    </div>
  )
}

export function moduleRoutes(registry: Registry, resolve: PageResolver, home: string): ReactElement[] {
  const routes = registry.pages.map((page) => {
    const Page = resolve(page.moduleId, page.pageId)
    return (
      <Route
        key={`${page.moduleId}:${page.pageId}`}
        path={page.path}
        element={Page === null ? <NothingOpensThis moduleId={page.moduleId} /> : <Page />}
      />
    )
  })
  for (const redirect of registry.redirects) {
    routes.push(
      <Route key={`redirect:${redirect.from}`} path={redirect.from} element={<Navigate to={redirect.to} replace />} />,
    )
  }
  // HOME MAY NOT BE MOUNTED FOR THIS PERSON -- a backend can name a home
  // in a module this person is not offered. Sending every stray address
  // to it would land on `*` again and loop; so `*` says nothing opens
  // the address instead.
  const homeIsMounted = registry.pages.some((page) => page.path === home)
  routes.push(
    <Route
      key="home"
      path="*"
      element={
        homeIsMounted ? (
          <Navigate to={home} replace />
        ) : (
          <div className="shell__nothing-opens-this" role="status">
            <p>Nothing loaded opens this page.</p>
          </div>
        )
      }
    />,
  )
  return routes
}
