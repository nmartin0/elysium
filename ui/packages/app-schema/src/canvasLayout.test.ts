import { describe, expect, it } from 'vitest'
import {
  MAX_SCALE,
  NODE_HEIGHT,
  NODE_WIDTH,
  type Point,
  fitView,
  labelPoint,
  lanes,
  pathOf,
  placeNodes,
  routeEdge,
} from './canvasLayout'

const isOrthogonal = (points: Point[]) =>
  points.slice(1).every((point, i) => point.x === points[i]!.x || point.y === points[i]!.y)

describe('placing the types (DEV_UI 14.1)', () => {
  const CHAIN = [
    { source: 'Transaction', target: 'Customer' },
    { source: 'Customer', target: 'Region' },
  ]

  it('layers left to right along the links', () => {
    const placed = placeNodes(['Customer', 'Region', 'Transaction'], CHAIN, {})
    expect(placed.Transaction!.x).toBeLessThan(placed.Customer!.x)
    expect(placed.Customer!.x).toBeLessThan(placed.Region!.x)
  })

  it('draws the same picture every time, whatever order the types arrive in', () => {
    const a = placeNodes(['Customer', 'Region', 'Transaction'], CHAIN, {})
    const b = placeNodes(['Transaction', 'Region', 'Customer'], [...CHAIN].reverse(), {})
    expect(b).toEqual(a)
  })

  it('a moved node stays where it was put; the rest follow the layout', () => {
    const placed = placeNodes(['Customer', 'Region', 'Transaction'], CHAIN, { Region: { x: -500, y: 900 } })
    expect(placed.Region).toEqual({ x: -500, y: 900, pinned: true })
    expect(placed.Customer!.pinned).toBe(false)
  })

  it('no two unmoved types overlap', () => {
    const names = Array.from({ length: 12 }, (_, i) => `T${i}`)
    const edges = names.slice(1).map((name, i) => ({ source: name, target: names[Math.floor(i / 3)]! }))
    const placed = Object.values(placeNodes(names, edges, {}))
    for (const [i, a] of placed.entries()) {
      for (const b of placed.slice(i + 1)) {
        const apart = Math.abs(a.x - b.x) >= NODE_WIDTH || Math.abs(a.y - b.y) >= NODE_HEIGHT
        expect(apart).toBe(true)
      }
    }
  })

  it('a link to itself, or to a type not drawn, places nothing and breaks nothing', () => {
    const placed = placeNodes(
      ['Customer'],
      [
        { source: 'Customer', target: 'Customer' },
        { source: 'Customer', target: 'Gone' },
      ],
      {},
    )
    expect(Object.keys(placed)).toEqual(['Customer'])
  })
})

describe('routing the edges', () => {
  it('side by side: out of the facing sides, every segment horizontal or vertical', () => {
    const route = routeEdge({ x: 0, y: 0 }, { x: 400, y: 120 })
    expect(isOrthogonal(route)).toBe(true)
    expect(route[0]).toEqual({ x: NODE_WIDTH / 2, y: 0 })
    expect(route.at(-1)).toEqual({ x: 400 - NODE_WIDTH / 2, y: 120 })
  })

  it('above and below: out of the top and bottom instead', () => {
    const route = routeEdge({ x: 0, y: 0 }, { x: 40, y: 300 })
    expect(isOrthogonal(route)).toBe(true)
    expect(route[0]).toEqual({ x: 0, y: NODE_HEIGHT / 2 })
    expect(route.at(-1)).toEqual({ x: 40, y: 300 - NODE_HEIGHT / 2 })
  })

  it('pointing left works as well as right', () => {
    const route = routeEdge({ x: 400, y: 0 }, { x: 0, y: 0 })
    expect(route).toEqual([
      { x: 400 - NODE_WIDTH / 2, y: 0 },
      { x: NODE_WIDTH / 2, y: 0 },
    ])
  })

  it('a straight run is one segment, not a jog of zero length', () => {
    expect(routeEdge({ x: 0, y: 50 }, { x: 400, y: 50 })).toHaveLength(2)
  })

  it('a type linked to itself gets a loop off its right side', () => {
    const loop = routeEdge({ x: 0, y: 0 }, { x: 0, y: 0 })
    expect(isOrthogonal(loop)).toBe(true)
    expect(loop.every((point) => point.x >= NODE_WIDTH / 2)).toBe(true)
  })

  it('two relationships between one pair run in two lanes, not one line', () => {
    expect(
      lanes([
        { source: 'A', target: 'B' },
        { source: 'B', target: 'A' },
        { source: 'A', target: 'B' },
        { source: 'A', target: 'C' },
      ]),
    ).toEqual([0, 1, -1, 0])
    expect(routeEdge({ x: 0, y: 0 }, { x: 400, y: 0 }, 1)).not.toEqual(routeEdge({ x: 0, y: 0 }, { x: 400, y: 0 }, 0))
  })

  it('writes a path and finds a label point on the middle segment', () => {
    const points = [
      { x: 0, y: 0 },
      { x: 10, y: 0 },
      { x: 10, y: 20 },
      { x: 30, y: 20 },
    ]
    expect(pathOf(points)).toBe('M0 0 L10 0 L10 20 L30 20')
    expect(labelPoint(points)).toEqual({ x: 10, y: 10 })
  })

  it('puts the label on the run into the target, not on a trunk other edges share', () => {
    // Several edges leave one type along one vertical trunk; labels on
    // it were struck through by the line (found in a browser).
    const points = [
      { x: 0, y: 0 },
      { x: 100, y: 0 },
      { x: 100, y: 200 },
      { x: 200, y: 200 },
    ]
    expect(labelPoint(points)).toEqual({ x: 150, y: 200 })
  })

  it('puts the label beside a run that comes down into the target, not on it', () => {
    const points = [
      { x: 0, y: 0 },
      { x: 0, y: 40 },
      { x: 50, y: 40 },
      { x: 50, y: 200 },
    ]
    const at = labelPoint(points)
    expect(at.x).toBeGreaterThan(50 + 10)
    expect(at.y).toBeGreaterThan(40 + 80 - 20)
    expect(at.y).toBeLessThan(200)
  })

  it('falls back to the middle when the run into the target is too short for a label', () => {
    const points = [
      { x: 0, y: 0 },
      { x: 100, y: 0 },
      { x: 100, y: 200 },
      { x: 130, y: 200 },
    ]
    expect(labelPoint(points)).toEqual({ x: 100, y: 100 })
  })
})

describe('routing round the types in the way', () => {
  const A = { x: 0, y: 0 }
  const B = { x: 600, y: 0 }
  const inTheWay = { x: 300, y: 0 }

  /** Whether the route runs through the inside of a node's real box. */
  const through = (route: Point[], centre: Point) =>
    route.slice(1).some((point, i) => {
      const a = route[i]!
      const left = centre.x - NODE_WIDTH / 2
      const right = centre.x + NODE_WIDTH / 2
      const top = centre.y - NODE_HEIGHT / 2
      const bottom = centre.y + NODE_HEIGHT / 2
      return a.y === point.y
        ? a.y > top && a.y < bottom && Math.max(a.x, point.x) > left && Math.min(a.x, point.x) < right
        : a.x > left && a.x < right && Math.max(a.y, point.y) > top && Math.min(a.y, point.y) < bottom
    })

  const crossedNone = (route: Point[], others: Point[]) => !others.some((centre) => through(route, centre))

  it('the plain route runs through a type between the two, which is what this is for', () => {
    expect(through(routeEdge(A, B), inTheWay)).toBe(true)
  })

  it('goes round it instead, out of the same sides, every segment horizontal or vertical', () => {
    const route = routeEdge(A, B, 0, [inTheWay])

    expect(through(route, inTheWay)).toBe(false)
    expect(isOrthogonal(route)).toBe(true)
    expect(route[0]).toEqual({ x: NODE_WIDTH / 2, y: 0 })
    expect(route.at(-1)).toEqual({ x: 600 - NODE_WIDTH / 2, y: 0 })
    // Out and in horizontally, as a facing side asks.
    expect(route[1]!.y).toBe(route[0]!.y)
    expect(route.at(-2)!.y).toBe(route.at(-1)!.y)
  })

  it('takes the fewest bends: over or under one type is four', () => {
    expect(routeEdge(A, B, 0, [inTheWay]).length).toBeLessThanOrEqual(6)
  })

  it('does the same for a run above and below', () => {
    const route = routeEdge({ x: 0, y: 0 }, { x: 0, y: 500 }, 0, [{ x: 0, y: 250 }])

    expect(through(route, { x: 0, y: 250 })).toBe(false)
    expect(isOrthogonal(route)).toBe(true)
    expect(route[0]).toEqual({ x: 0, y: NODE_HEIGHT / 2 })
    expect(route.at(-1)).toEqual({ x: 0, y: 500 - NODE_HEIGHT / 2 })
    expect(route[1]!.x).toBe(route[0]!.x)
  })

  it('leaves a clear route exactly as it was, whatever else is on the canvas', () => {
    const far = [
      { x: 300, y: 400 },
      { x: -900, y: 0 },
    ]
    expect(routeEdge(A, B, 0, far)).toEqual(routeEdge(A, B))
    expect(routeEdge({ x: 0, y: 0 }, { x: 400, y: 120 }, 1, far)).toEqual(
      routeEdge({ x: 0, y: 0 }, { x: 400, y: 120 }, 1),
    )
  })

  it('draws the same route every time', () => {
    expect(routeEdge(A, B, 0, [inTheWay])).toEqual(routeEdge(A, B, 0, [inTheWay]))
  })

  it('finds a way past a wall of types', () => {
    const wall = [-2, -1, 0, 1, 2].map((row) => ({ x: 300, y: row * 100 }))
    const route = routeEdge(A, B, 0, wall)

    expect(wall.some((centre) => through(route, centre))).toBe(false)
    expect(isOrthogonal(route)).toBe(true)
  })

  it('keeps two relationships between one pair apart even when both go round', () => {
    const first = routeEdge(A, B, 0, [inTheWay])
    const second = routeEdge(A, B, 1, [inTheWay])
    const third = routeEdge(A, B, -1, [inTheWay])

    expect(second).not.toEqual(first)
    expect(third).not.toEqual(first)
    expect(third).not.toEqual(second)
    for (const route of [first, second, third]) expect(through(route, inTheWay)).toBe(false)
  })

  it('does the same for lanes running up and down', () => {
    const above = { x: 0, y: 0 }
    const below = { x: 0, y: 500 }
    const between = { x: 0, y: 250 }
    const routes = [0, 1, -1].map((lane) => routeEdge(above, below, lane, [between]))

    expect(new Set(routes.map((route) => JSON.stringify(route))).size).toBe(3)
    for (const route of routes) expect(through(route, between)).toBe(false)
  })

  it('keeps clear of the type it goes past, by more than the gap it was asked for', () => {
    const route = routeEdge(A, B, 0, [inTheWay])
    const gap = Math.min(...route.map((point) => Math.abs(point.y - inTheWay.y)).filter((d) => d > 0))

    expect(gap).toBeGreaterThan(NODE_HEIGHT / 2 + 14)
  })

  it('keeps clear of a type it goes past on either axis', () => {
    const sideways = routeEdge({ x: 0, y: 0 }, { x: 0, y: 500 }, 0, [{ x: 0, y: 250 }])
    const gap = Math.min(...sideways.map((point) => Math.abs(point.x)).filter((d) => d > 0))

    expect(gap).toBeGreaterThan(NODE_WIDTH / 2 + 14)
  })

  it('is not slowed by types far from the edge, which cannot be in its way', () => {
    // A crowd far to the right: with every type taken into account the
    // search is several times slower for nothing.
    const crowd = Array.from({ length: 400 }, (_, i) => ({ x: 5000 + (i % 20) * 300, y: Math.floor(i / 20) * 130 }))
    const time = (others: Point[]) => {
      const started = performance.now()
      for (let again = 0; again < 60; again++) routeEdge(A, B, 0, others)
      return performance.now() - started
    }
    time([inTheWay, ...crowd])
    const alone = time([inTheWay])
    const withCrowd = time([inTheWay, ...crowd])

    expect(withCrowd).toBeLessThan(alone * 2.5 + 5)
  })

  it('never runs through a type, over a few hundred scattered layouts', () => {
    // A small deterministic generator, so a failure names its layout.
    let seed = 12345
    const next = () => {
      seed = (seed * 1664525 + 1013904223) % 4294967296
      return seed / 4294967296
    }
    let rounded = 0
    for (let layout = 0; layout < 300; layout++) {
      const columns = 6
      const cells = Array.from({ length: 18 }, (_, i) => i).filter(() => next() < 0.7)
      const centres = cells.map((cell) => ({ x: (cell % columns) * 260, y: Math.floor(cell / columns) * 140 }))
      if (centres.length < 3) continue
      const from = centres[0]!
      const to = centres[centres.length - 1]!
      const others = centres.slice(1, -1)
      const route = routeEdge(from, to, 0, others)
      if (route.length > routeEdge(from, to).length) rounded++
      expect(isOrthogonal(route), `layout ${layout}`).toBe(true)
      // Nor does it come back through the two it joins.
      if (crossedNone(route, others)) {
        expect(through(route, from), `layout ${layout} through its source`).toBe(false)
        expect(through(route, to), `layout ${layout} through its target`).toBe(false)
      }
      // A route may only run through a node when no way round exists.
      const crossed = others.filter((centre) => through(route, centre))
      if (crossed.length > 0) {
        expect(route, `layout ${layout} had no way round`).toEqual(routeEdge(from, to))
      }
    }
    expect(rounded).toBeGreaterThan(20)
  })
})

describe('fitting the view', () => {
  it('shows every node inside the viewport', () => {
    const centres = [
      { x: 0, y: 0 },
      { x: 1000, y: 600 },
    ]
    const view = fitView(centres, 800, 500)
    for (const centre of centres) {
      const left = (centre.x - NODE_WIDTH / 2) * view.scale + view.x
      const right = (centre.x + NODE_WIDTH / 2) * view.scale + view.x
      const top = (centre.y - NODE_HEIGHT / 2) * view.scale + view.y
      const bottom = (centre.y + NODE_HEIGHT / 2) * view.scale + view.y
      expect(left).toBeGreaterThanOrEqual(0)
      expect(right).toBeLessThanOrEqual(800)
      expect(top).toBeGreaterThanOrEqual(0)
      expect(bottom).toBeLessThanOrEqual(500)
    }
  })

  it('does not blow a single type up to fill the screen', () => {
    expect(fitView([{ x: 0, y: 0 }], 2000, 2000).scale).toBeLessThan(MAX_SCALE)
  })
})
