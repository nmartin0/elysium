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
 * AROUND OTHER NODES: where the plain route would run through a third
 * type, the edge is routed again around it -- the fewest bends, then the
 * shortest -- leaving and arriving by the same facing sides. An edge
 * with a clear run is drawn exactly as before, so moving one node does
 * not redraw edges it has nothing to do with.
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
function directRoute(from: Point, to: Point, lane: number): Point[] {
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

interface Rect {
  left: number
  right: number
  top: number
  bottom: number
}

/** Space kept round a node an edge goes past, and how far from a node's
 *  side a detour runs once it clears it. */
const CLEARANCE = 14
const TRACK = 8

/** Only nodes this near the two ends can be in the way worth routing round. */
const NEIGHBOURHOOD = 240

/** A turn costs this many pixels of length, so fewer bends win. */
const TURN_COST = 40

const rectOf = (centre: Point, grow: number): Rect => ({
  left: centre.x - NODE_WIDTH / 2 - grow,
  right: centre.x + NODE_WIDTH / 2 + grow,
  top: centre.y - NODE_HEIGHT / 2 - grow,
  bottom: centre.y + NODE_HEIGHT / 2 + grow,
})

/** Whether a straight, axis-aligned segment runs through a rectangle's
 *  inside. Touching an edge is not through it: an edge leaves a node by
 *  its side. */
function crosses(a: Point, b: Point, rect: Rect): boolean {
  if (a.y === b.y) {
    return a.y > rect.top && a.y < rect.bottom && Math.max(a.x, b.x) > rect.left && Math.min(a.x, b.x) < rect.right
  }
  return a.x > rect.left && a.x < rect.right && Math.max(a.y, b.y) > rect.top && Math.min(a.y, b.y) < rect.bottom
}

const blocked = (route: Point[], rects: Rect[]): boolean =>
  route.slice(1).some((point, i) => rects.some((rect) => crosses(route[i]!, point, rect)))

/**
 * The route round whatever is in the way: Dijkstra over the lines that
 * run just outside each node, with a cost for every turn, so it takes
 * the fewest bends and then the shortest. Starts where the plain route
 * does, on the side the first node faces, and ends going in through the
 * side the second faces. Null if nothing gets through.
 */
function detourRoute(start: Point, end: Point, horizontal: boolean, others: Point[], track: number) {
  const rects = others.map((centre) => rectOf(centre, CLEARANCE))
  const xs = new Set([start.x, end.x, (start.x + end.x) / 2])
  const ys = new Set([start.y, end.y, (start.y + end.y) / 2])
  for (const rect of rects) {
    xs.add(rect.left - track).add(rect.right + track)
    ys.add(rect.top - track).add(rect.bottom + track)
  }
  const gridX = [...xs].sort((a, b) => a - b)
  const gridY = [...ys].sort((a, b) => a - b)
  const columns = gridX.length
  // Directions: 0 right, 1 left, 2 down, 3 up.
  const step: [number, number][] = [
    [1, 0],
    [-1, 0],
    [0, 1],
    [0, -1],
  ]
  const at = (column: number, row: number) => ({ x: gridX[column]!, y: gridY[row]! })
  const key = (column: number, row: number, direction: number) => (row * columns + column) * 4 + direction

  const first = horizontal ? (end.x > start.x ? 0 : 1) : end.y > start.y ? 2 : 3
  const startColumn = gridX.indexOf(start.x)
  const startRow = gridY.indexOf(start.y)
  const endColumn = gridX.indexOf(end.x)
  const endRow = gridY.indexOf(end.y)

  const cost = new Map<number, number>()
  const before = new Map<number, number>()
  // A binary heap, ties broken by place so the same layout gives the same
  // route every time.
  type Entry = { cost: number; column: number; row: number; direction: number }
  const heap: Entry[] = []
  const before_ = (a: Entry, b: Entry) =>
    a.cost - b.cost || a.row - b.row || a.column - b.column || a.direction - b.direction
  const push = (entry: Entry) => {
    heap.push(entry)
    for (let i = heap.length - 1; i > 0;) {
      const parent = (i - 1) >> 1
      if (before_(heap[i]!, heap[parent]!) >= 0) break
      ;[heap[i], heap[parent]] = [heap[parent]!, heap[i]!]
      i = parent
    }
  }
  const pop = (): Entry | undefined => {
    const top = heap[0]
    const last = heap.pop()
    if (top === undefined || last === undefined) return top
    if (heap.length > 0) {
      heap[0] = last
      for (let i = 0; ;) {
        const left = 2 * i + 1
        const right = left + 1
        let least = i
        if (left < heap.length && before_(heap[left]!, heap[least]!) < 0) least = left
        if (right < heap.length && before_(heap[right]!, heap[least]!) < 0) least = right
        if (least === i) break
        ;[heap[i], heap[least]] = [heap[least]!, heap[i]!]
        i = least
      }
    }
    return top
  }
  cost.set(key(startColumn, startRow, first), 0)
  push({ cost: 0, column: startColumn, row: startRow, direction: first })
  let reached: number | null = null
  for (let entry = pop(); entry !== undefined; entry = pop()) {
    const here = key(entry.column, entry.row, entry.direction)
    if (entry.cost > (cost.get(here) ?? Infinity)) continue
    if (entry.column === endColumn && entry.row === endRow && entry.direction === first) {
      reached = here
      break
    }
    for (const [direction, [dx, dy]] of step.entries()) {
      const column = entry.column + dx
      const row = entry.row + dy
      if (column < 0 || column >= columns || row < 0 || row >= gridY.length) continue
      const a = at(entry.column, entry.row)
      const b = at(column, row)
      if (rects.some((rect) => crosses(a, b, rect))) continue
      const next =
        entry.cost + Math.abs(b.x - a.x) + Math.abs(b.y - a.y) + (direction === entry.direction ? 0 : TURN_COST)
      const there = key(column, row, direction)
      if (next < (cost.get(there) ?? Infinity)) {
        cost.set(there, next)
        before.set(there, here)
        push({ cost: next, column, row, direction })
      }
    }
  }
  if (reached === null) return null

  const route: Point[] = []
  for (let state: number | undefined = reached; state !== undefined; state = before.get(state)) {
    const cell = Math.floor(state / 4)
    route.push(at(cell % columns, Math.floor(cell / columns)))
  }
  route.reverse()
  // A point in the middle of a straight run is not a bend.
  return route.filter((point, i) => {
    const previous = route[i - 1]
    const next = route[i + 1]
    return !(
      previous &&
      next &&
      ((previous.x === point.x && point.x === next.x) || (previous.y === point.y && point.y === next.y))
    )
  })
}

/**
 * An orthogonal route from one node to another, as the points of a
 * polyline: out of the facing sides, one jog in the middle -- or, if that
 * would run through one of `others` (the centres of the other types),
 * round it.
 *
 * `lane` separates edges between the same two types (0, 1, -1, 2, ...),
 * so two relationships do not draw as one line -- on a detour, by the
 * track each runs on past a node.
 */
export function routeEdge(from: Point, to: Point, lane = 0, others: Point[] = []): Point[] {
  const direct = directRoute(from, to, lane)
  if (others.length === 0 || (from.x === to.x && from.y === to.y)) return direct
  const reach = {
    left: Math.min(from.x, to.x) - NODE_WIDTH / 2 - NEIGHBOURHOOD,
    right: Math.max(from.x, to.x) + NODE_WIDTH / 2 + NEIGHBOURHOOD,
    top: Math.min(from.y, to.y) - NODE_HEIGHT / 2 - NEIGHBOURHOOD,
    bottom: Math.max(from.y, to.y) + NODE_HEIGHT / 2 + NEIGHBOURHOOD,
  }
  const nearby = others.filter((centre) => {
    const rect = rectOf(centre, 0)
    return rect.right > reach.left && rect.left < reach.right && rect.bottom > reach.top && rect.top < reach.bottom
  })
  if (
    !blocked(
      direct,
      nearby.map((centre) => rectOf(centre, CLEARANCE)),
    )
  )
    return direct

  // Each lane runs on its own track beside the node it goes past: 0, then
  // 1, -1, 2, ... one lane gap further out each.
  const slot = lane === 0 ? 0 : lane > 0 ? 2 * lane - 1 : -2 * lane
  const plain = directRoute(from, to, 0)
  const horizontal = Math.abs(to.x - from.x) >= NODE_WIDTH + 16
  const detour = detourRoute(plain[0]!, plain.at(-1)!, horizontal, nearby, TRACK + slot * LANE_GAP)
  return detour ?? direct
}

/** The polyline as an SVG path. */
export function pathOf(points: Point[]): string {
  return points.map((point, index) => `${index === 0 ? 'M' : 'L'}${point.x} ${point.y}`).join(' ')
}

/** The least room a label needs along a straight run: "many" is about 32px. */
const LABEL_ROOM = 44

/** How far to the side of a vertical line its label is centred: half "many", and a gap. */
const LABEL_BESIDE = 22

/**
 * Where an edge's label sits: on the short run INTO its target when that
 * is straight and long enough, else the middle of its middle segment.
 *
 * Several edges leaving one type share a vertical trunk, and the middle
 * segment IS that trunk -- every label sat on it and was struck through
 * ("ma|ny"), found in a browser. The run into the target is the one part
 * of the route that is each edge's own.
 */
export function labelPoint(points: Point[]): Point {
  const last = points.at(-1)
  const before = points.at(-2)
  if (last && before && before.y === last.y && Math.abs(last.x - before.x) >= LABEL_ROOM) {
    return { x: (before.x + last.x) / 2, y: last.y }
  }
  // A RUN DOWN INTO THE TARGET: beside the line, not on it. The label is
  // drawn centred and a little above the point it is given.
  if (last && before && before.x === last.x && Math.abs(last.y - before.y) >= LABEL_ROOM) {
    return { x: last.x + LABEL_BESIDE, y: (before.y + last.y) / 2 + 8 }
  }
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
