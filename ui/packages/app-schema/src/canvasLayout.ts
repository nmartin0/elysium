/**
 * Where the ontology canvas puts things, and how its edges run (DEV_UI 14.1).
 *
 * LAYERED, FOR STRUCTURE: "in ontology graphs, where hierarchy and
 * semantic depth are critical, layered or hierarchical layouts tend to
 * offer the clearest structure". The force layout this replaces was
 * fine at the fixture's handful of types and is the one the studies
 * found "less readable as the amount of nodes increased" -- and a real
 * deployment has 10 to 120. dagre is a Sugiyama layout: layers, then
 * crossing minimisation, which 14.1 asks for "as a first-class
 * requirement rather than a nicety".
 *
 * A MOVED NODE STAYS WHERE IT WAS PUT. "A graph that re-jiggles on
 * reload destroys spatial memory, which is most of why a canvas beats
 * a list." The layout runs over every type and a saved position then
 * wins; a type never moved keeps following the layout.
 *
 * ORTHOGONAL EDGES, ROUTED HERE rather than by the layout. dagre's
 * edges are polylines through its own layers, and stop meaning anything
 * the moment a person moves a node. Routing every edge with the same
 * few rules means an edge looks the same whether its ends were placed
 * by the layout or by hand -- one visual language, which 14.5 asks for.
 * What it does NOT do is route around other nodes: an edge between two
 * types moved far apart can cross a third. Recorded rather than left to
 * be found; "Auto-layout" puts everything back where no edge has to.
 *
 * PURE AND EXPORTED: jsdom computes no layout, but it can check numbers.
 */

import { Graph, layout } from '@dagrejs/dagre'

export const NODE_WIDTH = 188
export const NODE_HEIGHT = 64

export interface Point {
  x: number
  y: number
}

/** A node's CENTRE, and whether a person put it there. */
export interface Placed extends Point {
  pinned: boolean
}

interface EdgeEnds {
  source: string
  target: string
}

/**
 * Every type's centre.
 *
 * DETERMINISTIC: the same ontology gives the same picture. dagre is
 * deterministic for a given insertion order, so names and edges go in
 * sorted.
 */
export function placeNodes(names: string[], edges: EdgeEnds[], saved: Record<string, Point>): Record<string, Placed> {
  const graph = new Graph({ multigraph: true })
  // LEFT TO RIGHT: a link reads "Transaction -> Customer", and a row of
  // type names is easier to read than a column of them at this width.
  graph.setGraph({ rankdir: 'LR', nodesep: 40, ranksep: 110, marginx: 24, marginy: 24 })
  graph.setDefaultEdgeLabel(() => ({}))
  const sorted = [...names].sort((a, b) => a.localeCompare(b))
  for (const name of sorted) graph.setNode(name, { width: NODE_WIDTH, height: NODE_HEIGHT })
  const known = new Set(sorted)
  const ordered = [...edges].sort((a, b) => `${a.source}>${a.target}`.localeCompare(`${b.source}>${b.target}`))
  for (const [index, edge] of ordered.entries()) {
    // A SELF-LINK places nothing -- its loop is drawn on the node.
    if (edge.source === edge.target || !known.has(edge.source) || !known.has(edge.target)) continue
    graph.setEdge(edge.source, edge.target, {}, `e${index}`)
  }
  layout(graph)

  const placed: Record<string, Placed> = {}
  for (const name of sorted) {
    const point = saved[name]
    if (point) {
      placed[name] = { x: point.x, y: point.y, pinned: true }
    } else {
      const node = graph.node(name) as { x: number; y: number }
      placed[name] = { x: node.x, y: node.y, pinned: false }
    }
  }
  return placed
}

/** How far apart two edges between the same pair of types run. */
const LANE_GAP = 12

/**
 * An orthogonal route from one node to another, as the points of a
 * polyline: out of the facing sides, one jog in the middle.
 *
 * `lane` separates edges between the same two types (0, 1, -1, 2, ...),
 * so two relationships do not draw as one line.
 */
export function routeEdge(from: Point, to: Point, lane = 0): Point[] {
  const halfW = NODE_WIDTH / 2
  const halfH = NODE_HEIGHT / 2
  const offset = lane * LANE_GAP

  // A LOOP for a type linked to itself: out of the right side, round, back.
  if (from.x === to.x && from.y === to.y) {
    const right = from.x + halfW
    const reach = 28 + Math.abs(offset)
    return [
      { x: right, y: from.y - 12 - offset },
      { x: right + reach, y: from.y - 12 - offset },
      { x: right + reach, y: from.y + 12 + offset },
      { x: right, y: from.y + 12 + offset },
    ]
  }

  const dx = to.x - from.x
  const dy = to.y - from.y
  // SIDE BY SIDE: leave by the facing vertical sides, jog halfway.
  if (Math.abs(dx) >= NODE_WIDTH + 16) {
    const direction = Math.sign(dx)
    const startX = from.x + direction * halfW
    const endX = to.x - direction * halfW
    const midX = (startX + endX) / 2 + offset
    const startY = from.y + offset
    const endY = to.y + offset
    if (startY === endY)
      return [
        { x: startX, y: startY },
        { x: endX, y: endY },
      ]
    return [
      { x: startX, y: startY },
      { x: midX, y: startY },
      { x: midX, y: endY },
      { x: endX, y: endY },
    ]
  }
  // ABOVE AND BELOW: the same, turned a quarter.
  const direction = Math.sign(dy) || 1
  const startY = from.y + direction * halfH
  const endY = to.y - direction * halfH
  const midY = (startY + endY) / 2 + offset
  const startX = from.x + offset
  const endX = to.x + offset
  if (startX === endX)
    return [
      { x: startX, y: startY },
      { x: endX, y: endY },
    ]
  return [
    { x: startX, y: startY },
    { x: startX, y: midY },
    { x: endX, y: midY },
    { x: endX, y: endY },
  ]
}

/** The polyline as an SVG path. */
export function pathOf(points: Point[]): string {
  return points.map((point, index) => `${index === 0 ? 'M' : 'L'}${point.x} ${point.y}`).join(' ')
}

/** Where an edge's label sits: the middle of its middle segment. */
export function labelPoint(points: Point[]): Point {
  const at = Math.max(0, Math.floor((points.length - 1) / 2))
  const a = points[at]!
  const b = points[Math.min(at + 1, points.length - 1)]!
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }
}

/**
 * Lane numbers for edges sharing a pair of types, in the order given:
 * 0, then 1, -1, 2, -2. Keyed on the UNORDERED pair, because A->B and
 * B->A would otherwise draw over each other.
 */
export function lanes(edges: EdgeEnds[]): number[] {
  const seen = new Map<string, number>()
  return edges.map((edge) => {
    const key = [edge.source, edge.target].sort().join('\u0000')
    const count = seen.get(key) ?? 0
    seen.set(key, count + 1)
    return count === 0 ? 0 : count % 2 === 1 ? (count + 1) / 2 : -count / 2
  })
}

export interface View {
  scale: number
  x: number
  y: number
}

const MIN_SCALE = 0.25
export const MAX_SCALE = 2.5

/** The view that shows every one of these centres, inside a viewport. */
export function fitView(centres: Point[], width: number, height: number, padding = 32): View {
  if (centres.length === 0 || width <= 0 || height <= 0) return { scale: 1, x: 0, y: 0 }
  const left = Math.min(...centres.map((c) => c.x)) - NODE_WIDTH / 2
  const right = Math.max(...centres.map((c) => c.x)) + NODE_WIDTH / 2
  const top = Math.min(...centres.map((c) => c.y)) - NODE_HEIGHT / 2
  const bottom = Math.max(...centres.map((c) => c.y)) + NODE_HEIGHT / 2
  const scale = clampScale(
    Math.min((width - padding * 2) / (right - left), (height - padding * 2) / (bottom - top), 1.25),
  )
  return {
    scale,
    x: (width - (right - left) * scale) / 2 - left * scale,
    y: (height - (bottom - top) * scale) / 2 - top * scale,
  }
}

export function clampScale(scale: number): number {
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale))
}
