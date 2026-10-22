import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import type { InboxCounts } from '@elysium/shell-api/api'

const getInboxCounts = vi.fn()

vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return { ...actual, getInboxCounts: () => getInboxCounts() }
})
// THE TABS ARE A SLOT (step 1.5b): rendered here as the app does, inside
// the shell's SlotsProvider, from the three modules' real manifests --
// so the titles, icons and order are what ships -- with each module's
// code standing in for its panel.
import type { FunctionComponent } from 'react'
import type { ModuleEntry } from '@shell/core/contract'
import { SlotsProvider } from '@shell/core/slots'
import approvalsManifest from '../packages/app-approvals/module.json'
import notificationsManifest from '../packages/app-notifications/module.json'
import identityManifest from '../packages/app-identity/module.json'
import inboxManifest from './inbox/module.json'

const { default: InboxPanel } = await import('./InboxPanel')

const feed = [inboxManifest, approvalsManifest, notificationsManifest, identityManifest].map(
  (manifest) => ({ ...manifest, entry: null }) as ModuleEntry,
)
const panel = (text: string) => () => <p>{text}</p>
const CODE: Record<string, Record<string, FunctionComponent>> = {
  approvals: {
    approvals: panel('approvals panel'),
    enrichment: panel('enrichment review'),
    predictions: panel('prediction review'),
    unusual: panel('unusual review'),
  },
  notifications: { notifications: panel('notifications panel') },
  identity: { identity: panel('identity panel') },
}

function show(
  url: string,
  counts: InboxCounts = { approvals: 0, notifications: 0, identity: 0, enrichment: 0, predictions: 0 },
  offered: ModuleEntry[] = feed,
) {
  getInboxCounts.mockResolvedValue(counts)
  return render(
    <MemoryRouter initialEntries={[url]}>
      <SlotsProvider modules={{ feed: offered, activate: (m) => ({ contributions: CODE[m.id] }) }}>
        <Routes>
          <Route path="/inbox" element={<InboxPanel onSessionExpired={vi.fn()} />} />
        </Routes>
      </SlotsProvider>
    </MemoryRouter>,
  )
}

describe('the Inbox (DEV_UI 12, 15)', () => {
  it('holds the four queues as tabs, approvals first', async () => {
    show('/inbox')

    expect(await screen.findByText('approvals panel')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /Approvals/ })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /Notifications/ })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /Identity/ })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /Enrichment/ })).toBeInTheDocument()
  })

  it('enrichment rules waiting on a decision are counted on their tab, and open there (R41)', async () => {
    show('/inbox?tab=enrichment', { approvals: 0, notifications: 0, identity: 0, enrichment: 2 })

    expect(await screen.findByText('enrichment review')).toBeInTheDocument()
    await screen.findByText('2')
    expect(screen.getByRole('tab', { name: /Enrichment/ })).toHaveTextContent('2')
  })

  it('predicted fields waiting on a decision are counted on their tab, and open there (R48)', async () => {
    show('/inbox?tab=predictions', { approvals: 0, notifications: 0, identity: 0, enrichment: 0, predictions: 3 })

    expect(await screen.findByText('prediction review')).toBeInTheDocument()
    await screen.findByText('3')
    expect(screen.getByRole('tab', { name: /Predictions/ })).toHaveTextContent('3')
  })

  it('unusual values waiting on a decision are counted on their tab, and open there (R51)', async () => {
    show('/inbox?tab=unusual', {
      approvals: 0,
      notifications: 0,
      identity: 0,
      enrichment: 0,
      predictions: 0,
      unusual: 4,
    })

    expect(await screen.findByText('unusual review')).toBeInTheDocument()
    await screen.findByText('4')
    expect(screen.getByRole('tab', { name: /Unusual/ })).toHaveTextContent('4')
  })

  it('opens the tab the URL names, so a link to a tab is a link', async () => {
    show('/inbox?tab=identity')

    expect(await screen.findByText('identity panel')).toBeInTheDocument()
    expect(screen.queryByText('approvals panel')).toBeNull()
  })

  it('an unknown tab is approvals, not an empty page', async () => {
    show('/inbox?tab=nonsense')

    expect(await screen.findByText('approvals panel')).toBeInTheDocument()
  })

  it('each tab says how much is waiting in it', async () => {
    show('/inbox', { approvals: 3, notifications: 0, identity: 1, enrichment: 0 })

    const approvals = await screen.findByRole('tab', { name: /Approvals/ })
    await screen.findByText('3')

    expect(approvals).toHaveTextContent('3')
    expect(screen.getByRole('tab', { name: /Identity/ })).toHaveTextContent('1')
    // Nothing waiting says nothing -- not a zero.
    expect(screen.getByRole('tab', { name: /Notifications/ })).not.toHaveTextContent('0')
  })
})

describe('the Inbox as a slot (step 1.5b)', () => {
  const tabNames = () => screen.getAllByRole('tab').map((tab) => tab.textContent)

  it("keeps the Inbox's own order, though its tabs come from three modules", async () => {
    show('/inbox')
    await screen.findByText('approvals panel')
    expect(tabNames()).toEqual(['Approvals', 'Notifications', 'Identity', 'Enrichment', 'Predictions', 'Unusual'])
  })

  it('a queue module not offered -- turned off, say -- has no tab, and the rest stand', async () => {
    show(
      '/inbox',
      undefined,
      feed.filter((module) => module.id !== 'identity'),
    )
    await screen.findByText('approvals panel')
    expect(tabNames()).toEqual(['Approvals', 'Notifications', 'Enrichment', 'Predictions', 'Unusual'])
  })
})
