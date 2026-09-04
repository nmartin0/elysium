import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route, Link } from 'react-router-dom'

// Partial mock via importOriginal, not a hand-duplicated module shape
// -- see App.test.tsx's own header comment for the full reasoning.
vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return {
    ...actual,
    getObjectDetail: vi.fn(),
    getVisibleActionTypes: vi.fn(),
  }
})
vi.mock('./ActionForm', () => ({
  // A simple stub -- ActionForm has its own, separate test file. This
  // file's own job is only to confirm ObjectDetailPanel renders it
  // with the right props and reacts correctly to onCancel/onResolved,
  // not to re-prove ActionForm's own internal form behavior here too.
  default: ({
    actionName,
    onCancel,
    onResolved,
  }: {
    actionName: string
    onCancel: () => void
    onResolved: () => void
  }) => (
    <div data-testid="action-form">
      <p>{actionName}</p>
      <button onClick={onCancel}>fake cancel</button>
      <button onClick={onResolved}>fake resolve</button>
    </div>
  ),
}))

import { getObjectDetail, getVisibleActionTypes, ApiError } from '@elysium/shell-api/api'
import ObjectDetailPanel, { type VisibleSchema } from './ObjectDetailPanel'

const mockedGetObjectDetail = vi.mocked(getObjectDetail)
const mockedGetVisibleActionTypes = vi.mocked(getVisibleActionTypes)

const CUSTOMER_SCHEMA: VisibleSchema = {
  Customer: {
    title_field: 'name',
    fields: { name: { type: 'data' }, account_id: { type: 'link', target: 'Account' } },
  },
  Account: { fields: { balance: { type: 'data' } } },
}

interface RenderPanelOptions {
  visibleSchema?: VisibleSchema
  onSessionExpired?: () => void
}

function renderPanel(
  objectType: string,
  objectId: string,
  { visibleSchema = CUSTOMER_SCHEMA, onSessionExpired = vi.fn() }: RenderPanelOptions = {},
) {
  return render(
    <MemoryRouter initialEntries={[`/objects/${objectType}/${objectId}`]}>
      <Routes>
        <Route
          path="/objects/:objectType/:objectId"
          element={<ObjectDetailPanel visibleSchema={visibleSchema} onSessionExpired={onSessionExpired} />}
        />
      </Routes>
    </MemoryRouter>,
  )
}

// A real, deliberate way to trigger React Router's own "re-render in
// place, do not remount" behavior -- the exact case ObjectDetailPanel's
// own latestRequestId guard exists for (rapid navigation between two
// DIFFERENT objects matching the SAME route pattern). A plain second
// render() call would remount instead, never exercising that guard at
// all.
function renderPanelWithNavigation(
  fromPath: string,
  toPath: string,
  { visibleSchema = CUSTOMER_SCHEMA, onSessionExpired = vi.fn() }: RenderPanelOptions = {},
) {
  return render(
    <MemoryRouter initialEntries={[fromPath]}>
      <Routes>
        <Route
          path="/objects/:objectType/:objectId"
          element={
            <>
              <Link to={toPath}>navigate away</Link>
              <ObjectDetailPanel visibleSchema={visibleSchema} onSessionExpired={onSessionExpired} />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedGetVisibleActionTypes.mockResolvedValue({})
})

describe('ObjectDetailPanel -- loading and basic rendering', () => {
  it('shows "Loading…" before the real fetch resolves', async () => {
    mockedGetObjectDetail.mockReturnValue(new Promise(() => {}))
    // getVisibleActionTypes is a separate, independent effect that
    // still resolves (the beforeEach default) even while this test is
    // only interested in the object-detail fetch's own pending state
    // -- left unresolved here too, so its own state update can't land
    // outside this test's control after the assertion below.
    mockedGetVisibleActionTypes.mockReturnValue(new Promise(() => {}))
    renderPanel('Customer', 'cust_001')
    expect(screen.getByText('Loading…')).toBeInTheDocument()
  })

  it('shows the object type label, title, and every real field once loaded', async () => {
    mockedGetObjectDetail.mockResolvedValue({ fields: { name: 'Ada Okafor', account_id: null } })
    renderPanel('Customer', 'cust_001')

    await waitFor(() => expect(screen.getByText('Customer')).toBeInTheDocument())
    expect(screen.getByText('Ada Okafor', { selector: '.object-detail__title' })).toBeInTheDocument()
    expect(screen.getByText('Account id')).toBeInTheDocument()
  })

  it('shows the raw id as a subtitle when the title came from a real title_field', async () => {
    mockedGetObjectDetail.mockResolvedValue({ fields: { name: 'Ada Okafor', account_id: null } })
    renderPanel('Customer', 'cust_001')

    await waitFor(() => expect(screen.getByText('cust_001')).toBeInTheDocument())
  })

  it('shows no redundant subtitle when the title falls back to the raw id', async () => {
    mockedGetObjectDetail.mockResolvedValue({ fields: { balance: 500 } })
    renderPanel('Account', 'acct_001')

    await waitFor(() => expect(screen.getByText('acct_001', { selector: '.object-detail__title' })).toBeInTheDocument())
    expect(screen.getAllByText('acct_001')).toHaveLength(1)
  })

  it('calls getObjectDetail with the real objectType and objectId from the URL', async () => {
    mockedGetObjectDetail.mockResolvedValue({ fields: { name: 'Ada Okafor' } })
    renderPanel('Customer', 'cust_001')

    await waitFor(() => expect(mockedGetObjectDetail).toHaveBeenCalledWith('Customer', 'cust_001'))
  })
})

describe('ObjectDetailPanel -- the generic "nothing to show" case', () => {
  it('shows a generic message, never distinguishing not-found from access-denied, when every field is empty', async () => {
    // Matches the backend's own deliberate ambiguity -- see this
    // component's own SECURITY note: identical shape either way.
    mockedGetObjectDetail.mockResolvedValue({ fields: { name: null, account_id: null } })
    renderPanel('Customer', 'cust_001')

    await waitFor(() => expect(screen.getByText('Nothing to show here.')).toBeInTheDocument())
  })

  it('shows real fields normally when at least one has a real value', async () => {
    mockedGetObjectDetail.mockResolvedValue({ fields: { name: 'Ada Okafor', account_id: null } })
    renderPanel('Customer', 'cust_001')

    await waitFor(() => expect(screen.queryByText('Nothing to show here.')).not.toBeInTheDocument())
  })
})

describe('ObjectDetailPanel -- error handling', () => {
  it('shows the error message on a non-401 failure', async () => {
    mockedGetObjectDetail.mockRejectedValue(new ApiError(500, 'Something went wrong'))
    renderPanel('Customer', 'cust_001')

    await waitFor(() => expect(screen.getByText('Something went wrong')).toBeInTheDocument())
  })

  it('calls onSessionExpired and shows no error text on a 401', async () => {
    mockedGetObjectDetail.mockRejectedValue(new ApiError(401, 'session expired'))
    const onSessionExpired = vi.fn()
    renderPanel('Customer', 'cust_001', { onSessionExpired })

    await waitFor(() => expect(onSessionExpired).toHaveBeenCalledTimes(1))
    expect(screen.queryByText('session expired')).not.toBeInTheDocument()
  })
})

describe('ObjectDetailPanel -- link field rendering', () => {
  it('renders a single-cardinality link field as a real, clickable link to the target object', async () => {
    mockedGetObjectDetail.mockResolvedValue({ fields: { name: 'Ada Okafor', account_id: 'acct_001' } })
    renderPanel('Customer', 'cust_001')

    await waitFor(() => expect(screen.getByRole('link', { name: 'acct_001' })).toBeInTheDocument())
    expect(screen.getByRole('link', { name: 'acct_001' })).toHaveAttribute('href', '/objects/Account/acct_001')
  })

  it('renders a null link value as "(not set)", not a broken link', async () => {
    mockedGetObjectDetail.mockResolvedValue({ fields: { name: 'Ada Okafor', account_id: null } })
    renderPanel('Customer', 'cust_001')

    await waitFor(() => expect(screen.getByText('(not set)')).toBeInTheDocument())
    expect(screen.queryByRole('link', { name: 'acct_001' })).not.toBeInTheDocument()
  })

  it('renders a many-cardinality link field (an array) as multiple, comma-separated links', async () => {
    const schema: VisibleSchema = {
      Customer: {
        fields: { orders: { type: 'link', target: 'Order' } },
      },
    }
    mockedGetObjectDetail.mockResolvedValue({ fields: { orders: ['order_1', 'order_2'] } })
    renderPanel('Customer', 'cust_001', { visibleSchema: schema })

    await waitFor(() => expect(screen.getByRole('link', { name: 'order_1' })).toBeInTheDocument())
    expect(screen.getByRole('link', { name: 'order_1' })).toHaveAttribute('href', '/objects/Order/order_1')
    expect(screen.getByRole('link', { name: 'order_2' })).toHaveAttribute('href', '/objects/Order/order_2')
  })

  it('renders an empty array link value as "(not set)"', async () => {
    const schema: VisibleSchema = { Customer: { fields: { orders: { type: 'link', target: 'Order' } } } }
    mockedGetObjectDetail.mockResolvedValue({ fields: { orders: [] } })
    renderPanel('Customer', 'cust_001', { visibleSchema: schema })

    await waitFor(() => expect(screen.getByText('(not set)')).toBeInTheDocument())
  })

  it('renders a plain data field as a plain value, never as a link', async () => {
    mockedGetObjectDetail.mockResolvedValue({ fields: { name: 'Ada Okafor', account_id: null } })
    renderPanel('Customer', 'cust_001')

    await waitFor(() =>
      expect(screen.getByText('Ada Okafor', { selector: '.object-detail__title' })).toBeInTheDocument(),
    )
    expect(screen.queryByRole('link', { name: 'Ada Okafor' })).not.toBeInTheDocument()
  })
})

describe('ObjectDetailPanel -- available actions', () => {
  it('shows a button only for an action that is BOTH executable and affects this object type', async () => {
    mockedGetObjectDetail.mockResolvedValue({ fields: { name: 'Ada Okafor' } })
    mockedGetVisibleActionTypes.mockResolvedValue({
      UpdateCustomerName: { affected_object_types: ['Customer'], executable: true, parameters: {} },
      DeleteAccount: { affected_object_types: ['Account'], executable: true, parameters: {} },
      ViewOnlyAction: { affected_object_types: ['Customer'], executable: false, parameters: {} },
    })
    renderPanel('Customer', 'cust_001')

    await waitFor(() => expect(screen.getByRole('button', { name: 'UpdateCustomerName' })).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'DeleteAccount' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'ViewOnlyAction' })).not.toBeInTheDocument()
  })

  it('shows no action buttons at all when getVisibleActionTypes fails -- a safe, silent degradation', async () => {
    mockedGetObjectDetail.mockResolvedValue({ fields: { name: 'Ada Okafor' } })
    mockedGetVisibleActionTypes.mockRejectedValue(new ApiError(500, 'action types unavailable'))
    renderPanel('Customer', 'cust_001')

    await waitFor(() =>
      expect(screen.getByText('Ada Okafor', { selector: '.object-detail__title' })).toBeInTheDocument(),
    )
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    // The object's own fields are unaffected by this failure.
    expect(screen.queryByText('action types unavailable')).not.toBeInTheDocument()
  })
})

describe('ObjectDetailPanel -- invoking an action', () => {
  it('clicking an action button shows ActionForm with the right actionName, hides the action buttons', async () => {
    mockedGetObjectDetail.mockResolvedValue({ fields: { name: 'Ada Okafor' } })
    mockedGetVisibleActionTypes.mockResolvedValue({
      UpdateCustomerName: { affected_object_types: ['Customer'], executable: true, parameters: {} },
    })
    renderPanel('Customer', 'cust_001')
    await waitFor(() => expect(screen.getByRole('button', { name: 'UpdateCustomerName' })).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: 'UpdateCustomerName' }))

    expect(screen.getByTestId('action-form')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'UpdateCustomerName' })).not.toBeInTheDocument()
  })

  it("ActionForm's onCancel returns to the plain detail view, action buttons visible again", async () => {
    mockedGetObjectDetail.mockResolvedValue({ fields: { name: 'Ada Okafor' } })
    mockedGetVisibleActionTypes.mockResolvedValue({
      UpdateCustomerName: { affected_object_types: ['Customer'], executable: true, parameters: {} },
    })
    renderPanel('Customer', 'cust_001')
    await waitFor(() => expect(screen.getByRole('button', { name: 'UpdateCustomerName' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'UpdateCustomerName' }))

    fireEvent.click(screen.getByRole('button', { name: 'fake cancel' }))

    expect(screen.queryByTestId('action-form')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'UpdateCustomerName' })).toBeInTheDocument()
  })

  it("ActionForm's onResolved returns to the detail view AND refreshes the object's own fields", async () => {
    mockedGetObjectDetail
      .mockResolvedValueOnce({ fields: { name: 'Ada Okafor' } })
      .mockResolvedValueOnce({ fields: { name: 'Ada Lovelace' } })
    mockedGetVisibleActionTypes.mockResolvedValue({
      UpdateCustomerName: { affected_object_types: ['Customer'], executable: true, parameters: {} },
    })
    renderPanel('Customer', 'cust_001')
    await waitFor(() => expect(screen.getByRole('button', { name: 'UpdateCustomerName' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'UpdateCustomerName' }))

    fireEvent.click(screen.getByRole('button', { name: 'fake resolve' }))

    await waitFor(() => expect(mockedGetObjectDetail).toHaveBeenCalledTimes(2))
    await waitFor(() =>
      expect(screen.getByText('Ada Lovelace', { selector: '.object-detail__title' })).toBeInTheDocument(),
    )
    expect(screen.queryByTestId('action-form')).not.toBeInTheDocument()
  })
})

describe('ObjectDetailPanel -- the real race-condition guard across navigation', () => {
  it('a SLOWER response for the FIRST object must never overwrite a faster response already shown for the object navigated to next', async () => {
    let resolveFirst: ((value: unknown) => void) | undefined
    let resolveSecond: ((value: unknown) => void) | undefined
    mockedGetObjectDetail.mockImplementation(() => {
      const callNumber = mockedGetObjectDetail.mock.calls.length
      return new Promise((resolve) => {
        if (callNumber === 1) resolveFirst = resolve
        else if (callNumber === 2) resolveSecond = resolve
      })
    })

    renderPanelWithNavigation('/objects/Customer/cust_001', '/objects/Customer/cust_002')
    await waitFor(() => expect(mockedGetObjectDetail).toHaveBeenCalledTimes(1))

    fireEvent.click(screen.getByRole('link', { name: 'navigate away' }))
    await waitFor(() => expect(mockedGetObjectDetail).toHaveBeenCalledTimes(2))

    // The SECOND object's response arrives first (faster).
    resolveSecond!({ fields: { name: 'Second Object' } })
    await waitFor(() =>
      expect(screen.getByText('Second Object', { selector: '.object-detail__title' })).toBeInTheDocument(),
    )

    // The FIRST object's response finally arrives, late -- must be
    // silently discarded, never shown over the second object's data.
    resolveFirst!({ fields: { name: 'First Object (stale)' } })
    await new Promise((resolve) => setTimeout(resolve, 200))

    expect(screen.getByText('Second Object', { selector: '.object-detail__title' })).toBeInTheDocument()
    expect(screen.queryByText('First Object (stale)')).not.toBeInTheDocument()
  })
})
