import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

const getObjectDetail = vi.fn()

vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return { ...actual, getObjectDetail: (...args: unknown[]) => getObjectDetail(...args) }
})

/**
 * ECharts draws to a canvas jsdom cannot read, so the wrapper is
 * replaced by something a query CAN see. The graph's own model is
 * tested beside it in instanceGraph.test.ts; what is left here is the
 * wiring -- which node a click chose, what a click fetched, and the
 * states a canvas has that a model does not.
 *
 * THE STAND-IN EXPOSES THE SERIES as text so a test can assert what
 * was handed to ECharts, and a button per node so a click has
 * somewhere to land.
 */
vi.mock('@elysium/shell-api/components/Chart', () => ({
  default: ({
    option,
    ariaLabel,
    onSelect,
  }: {
    option: Record<string, unknown>
    ariaLabel: string
    onSelect?: (name: string, dataType?: string) => void
  }) => {
    const series = (option.series as Array<Record<string, unknown>>)[0]
    const data = (series?.data ?? []) as Array<{ name: string; value: string; category: number }>
    const categories = (series?.categories ?? []) as Array<{ name: string }>
    const links = (series?.links ?? []) as Array<{ source: string; target: string; value: string }>
    return (
      <div>
        <p>{ariaLabel}</p>
        {data.map((node) => (
          <button key={node.name} onClick={() => onSelect?.(node.name, 'node')}>
            {`node:${node.name}:${categories[node.category]?.name ?? '?'}`}
          </button>
        ))}
        {links.map((link) => (
          <span key={`${link.source}->${link.target}:${link.value}`}>
            {`edge:${link.source}->${link.target}:${link.value}`}
          </span>
        ))}
        <button onClick={() => onSelect?.('', 'edge')}>click an edge</button>
      </div>
    )
  },
}))

const { default: ObjectGraph } = await import('./ObjectGraph')

const SCHEMA = {
  Customer: {
    fields: {
      name: { type: 'data' },
      transactions: { type: 'link', target: 'Transaction' },
    },
  },
  Transaction: { fields: { amount: { type: 'data' } } },
}

function show(results = [{ id: 'cust_001' }, { id: 'cust_002' }], schema: unknown = SCHEMA) {
  return render(
    <ObjectGraph objectType="Customer" results={results} visibleSchema={schema as never} onSessionExpired={vi.fn()} />,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  getObjectDetail.mockResolvedValue({ fields: { transactions: ['t1', 't2'] } })
})

describe('the canvas starts from the set', () => {
  it('draws a node per object', () => {
    show()

    expect(screen.getByText('node:Customer/cust_001:Customer')).toBeInTheDocument()
    expect(screen.getByText('node:Customer/cust_002:Customer')).toBeInTheDocument()
  })

  it('draws no edges until something is expanded', () => {
    show()

    expect(screen.queryByText(/^edge:/)).toBeNull()
  })

  it('says what it is showing, for a reader who cannot see a canvas', () => {
    show()

    expect(screen.getByText('2 objects of type Customer and 0 links between them')).toBeInTheDocument()
  })

  /**
   * COUNTED HONESTLY ONCE THE GRAPH MIXES TYPES. A first version said
   * "4 Customer objects" after an expansion had pulled in two
   * Transactions -- which a graph does by design.
   */
  it('counts the types rather than claiming they are all the set s', async () => {
    show([{ id: 'cust_001' }])
    fireEvent.click(screen.getByText('node:Customer/cust_001:Customer'))
    fireEvent.click(screen.getByRole('button', { name: /pull in/i }))

    expect(await screen.findByText('3 objects across 2 types and 2 links between them')).toBeInTheDocument()
  })

  /**
   * COLOUR CARRIES KIND, which DEV_UI.md 13.1 states for the ontology
   * canvas and holds here: a node labelled `3` beside one labelled
   * `cust_002` says nothing about being a Transaction otherwise, and
   * prefixing every label with its type would be noise on a graph of
   * one type, which is most of them.
   */
  it('gives each type its own category, so colour says which is which', async () => {
    show([{ id: 'cust_001' }])
    fireEvent.click(screen.getByText('node:Customer/cust_001:Customer'))
    fireEvent.click(screen.getByRole('button', { name: /pull in/i }))

    expect(await screen.findByText('node:Transaction/t1:Transaction')).toBeInTheDocument()
    expect(screen.getByText('node:Customer/cust_001:Customer')).toBeInTheDocument()
  })

  it('says object and link in the singular when there is one', () => {
    show([{ id: 'cust_001' }])

    expect(screen.getByText('1 object of type Customer and 0 links between them')).toBeInTheDocument()
  })

  it('says so plainly when the set is empty', () => {
    // Rather than an empty canvas, which reads as a broken screen.
    show([])

    expect(screen.getByText('Nothing to draw')).toBeInTheDocument()
  })

  it('renders nothing at all before a type is chosen', () => {
    const { container } = render(
      <ObjectGraph objectType={null} results={[]} visibleSchema={SCHEMA as never} onSessionExpired={vi.fn()} />,
    )

    expect(container).toBeEmptyDOMElement()
  })
})

describe('choosing a node', () => {
  it('shows what was chosen', () => {
    show()

    fireEvent.click(screen.getByText('node:Customer/cust_001:Customer'))

    expect(screen.getByRole('heading', { name: 'cust_001' })).toBeInTheDocument()
  })

  it('says which type it is, because a graph mixes them', () => {
    show()

    fireEvent.click(screen.getByText('node:Customer/cust_001:Customer'))

    expect(screen.getByText('Customer')).toBeInTheDocument()
  })

  /**
   * AN EDGE HAS NO NAME. Chart's own comment records that a handler
   * reading only the name "silently ignores every edge click" -- here
   * the risk is the reverse, selecting a node called "".
   */
  it('ignores a click on an edge rather than CLEARING what was chosen', () => {
    // A first version only checked that no panel appeared from a cold
    // start -- which passes with the guard deleted, because "" is not
    // a node key and selects nothing either way. The visible bug is
    // the other one: clicking a line made the panel vanish.
    show()
    fireEvent.click(screen.getByText('node:Customer/cust_001:Customer'))
    expect(screen.getByRole('heading', { name: 'cust_001' })).toBeInTheDocument()

    fireEvent.click(screen.getByText('click an edge'))

    expect(screen.getByRole('heading', { name: 'cust_001' })).toBeInTheDocument()
  })
})

describe('expanding', () => {
  it('fetches the chosen object and draws what it links to', async () => {
    show()
    fireEvent.click(screen.getByText('node:Customer/cust_001:Customer'))

    fireEvent.click(screen.getByRole('button', { name: /pull in/i }))

    await waitFor(() => expect(getObjectDetail).toHaveBeenCalledWith('Customer', 'cust_001'))
    expect(await screen.findByText('node:Transaction/t1:Transaction')).toBeInTheDocument()
    expect(screen.getByText('edge:Customer/cust_001->Transaction/t1:transactions')).toBeInTheDocument()
  })

  it('says it is done rather than offering to do it again', async () => {
    show()
    fireEvent.click(screen.getByText('node:Customer/cust_001:Customer'))
    fireEvent.click(screen.getByRole('button', { name: /pull in/i }))

    expect(await screen.findByText('Links pulled in')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /pull in/i })).toBeNull()
  })

  /**
   * "NOTHING IS ATTACHED" AND "I HAVE NOT LOOKED" ARE DIFFERENT FACTS.
   * A node with no links must still come back marked, or somebody
   * clicks it forever getting nothing.
   */
  it('marks a node with no links as looked at', async () => {
    getObjectDetail.mockResolvedValue({ fields: { transactions: [] } })
    show()
    fireEvent.click(screen.getByText('node:Customer/cust_001:Customer'))
    fireEvent.click(screen.getByRole('button', { name: /pull in/i }))

    expect(await screen.findByText('Links pulled in')).toBeInTheDocument()
  })

  it('follows no link the caller cannot see in their own schema', async () => {
    // The same filtering every other screen gets, by reading the same
    // source rather than a second one.
    getObjectDetail.mockResolvedValue({ fields: { transactions: ['t1'] } })
    show([{ id: 'cust_001' }], { Customer: { fields: { name: { type: 'data' } } } })
    fireEvent.click(screen.getByText('node:Customer/cust_001:Customer'))
    fireEvent.click(screen.getByRole('button', { name: /pull in/i }))

    await waitFor(() => expect(getObjectDetail).toHaveBeenCalled())
    expect(screen.queryByText('node:Transaction/t1:Transaction')).toBeNull()
  })

  it('shows the server s own words when a fetch fails', async () => {
    getObjectDetail.mockRejectedValue(new Error('Request failed (500)'))
    show()
    fireEvent.click(screen.getByText('node:Customer/cust_001:Customer'))
    fireEvent.click(screen.getByRole('button', { name: /pull in/i }))

    expect(await screen.findByText(/Request failed/)).toBeInTheDocument()
  })

  it('hands an expired session to the shell rather than drawing it', async () => {
    const { ApiError } = await import('@elysium/shell-api/api')
    const onSessionExpired = vi.fn()
    getObjectDetail.mockRejectedValue(new ApiError(401, 'Not authenticated'))
    render(
      <ObjectGraph
        objectType="Customer"
        results={[{ id: 'cust_001' }]}
        visibleSchema={SCHEMA as never}
        onSessionExpired={onSessionExpired}
      />,
    )
    fireEvent.click(screen.getByText('node:Customer/cust_001:Customer'))
    fireEvent.click(screen.getByRole('button', { name: /pull in/i }))

    await waitFor(() => expect(onSessionExpired).toHaveBeenCalled())
  })
})

describe('when the set changes', () => {
  it('starts a new canvas rather than drawing two questions at once', () => {
    const { rerender } = show()

    rerender(
      <ObjectGraph
        objectType="Customer"
        results={[{ id: 'cust_009' }]}
        visibleSchema={SCHEMA as never}
        onSessionExpired={vi.fn()}
      />,
    )

    expect(screen.getByText('node:Customer/cust_009:Customer')).toBeInTheDocument()
    expect(screen.queryByText('node:Customer/cust_001:Customer')).toBeNull()
  })

  /**
   * AND NOT ON EVERY RENDER. A re-render producing an equal list would
   * otherwise throw away an exploration somebody had built up, which
   * is the whole value of the canvas.
   */
  it('keeps an exploration when the same set re-renders', async () => {
    const { rerender } = show([{ id: 'cust_001' }])
    fireEvent.click(screen.getByText('node:Customer/cust_001:Customer'))
    fireEvent.click(screen.getByRole('button', { name: /pull in/i }))
    await screen.findByText('node:Transaction/t1:Transaction')

    rerender(
      <ObjectGraph
        objectType="Customer"
        results={[{ id: 'cust_001' }]}
        visibleSchema={SCHEMA as never}
        onSessionExpired={vi.fn()}
      />,
    )

    expect(screen.getByText('node:Transaction/t1:Transaction')).toBeInTheDocument()
  })
})

describe('the ceiling', () => {
  it('says how many it would not draw, rather than stopping quietly', () => {
    show(Array.from({ length: 70 }, (_, index) => ({ id: `c${index}` })))

    expect(screen.getByText('More than this canvas can draw')).toBeInTheDocument()
    expect(screen.getByText(/10 more would not fit/)).toBeInTheDocument()
  })

  it('says nothing when the set fits', () => {
    show()

    expect(screen.queryByText('More than this canvas can draw')).toBeNull()
  })

  it('will not offer to expand a full canvas', () => {
    show(Array.from({ length: 70 }, (_, index) => ({ id: `c${index}` })))

    fireEvent.click(screen.getByText('node:Customer/c0:Customer'))

    expect(screen.getByRole('button', { name: /pull in/i })).toBeDisabled()
    expect(screen.getByText('The canvas is full.')).toBeInTheDocument()
  })
})
