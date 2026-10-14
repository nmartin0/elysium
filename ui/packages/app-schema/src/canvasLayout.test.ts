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
