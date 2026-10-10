/**
 * The graph as a MODEL, apart from anything that draws it.
 *
 * WHY IT IS A SEPARATE MODULE. ECharts draws to a canvas jsdom cannot
 * read, so every assertion worth making about a graph has to be made
 * about the data it was given. `SchemaGraph.test.tsx` already settled
 * this for the type-level canvas -- "the chart draws to a canvas jsdom
 * cannot read" -- and the same is true here, more so: this graph
 * CHANGES as a person explores, and "does expanding twice duplicate a
 * node" is a question no screenshot answers.
 *
 * INSTANCES, NOT TYPES, which is what makes this a different module
 * rather than a parameter on that one. `buildGraph` there takes a
 * whole schema and draws every type once; a dozen nodes, drawn in one
 * go, needing no expansion and no identity beyond a type name. Here
 * the graph is built one question at a time and a node is a specific
 * object -- so identity, growth and a ceiling are the whole problem,
 * and none of them exist over there.
 *
 * IDENTITY IS (TYPE, ID), NEVER ID ALONE. Two object types can use the
 * same id -- `Customer/1` and `Transaction/1` are different things and
 * the dev deployment has both. This codebase has been bitten by
 * exactly that before: `LinkTrail` has a test called "does not reuse a
 * title across two types that share an id", written after it did.
 */

/** One object on the canvas. */
export interface GraphNode {
  /** `type/id`. The only thing anything else keys on. */
  key: string
  type: string
  id: string
  /** What the person reads. The id when the type has no title. */
  title: string
  /** Whether its links have been pulled in. Drawn differently,
   *  because "nothing is attached" and "I have not looked" are
   *  different facts and a canvas that conflates them is one people
   *  stop trusting. */
  expanded: boolean
}

/** One link, between two objects BOTH on the canvas.
 *
 *  NOT EXPORTED: nothing outside builds one, and every caller reaches
 *  it through `InstanceGraph.edges`. An exported type nobody names is
 *  vocabulary somebody has to maintain. */
interface GraphEdge {
  source: string
  target: string
  /** The field followed, which is what the edge is labelled with. */
  field: string
}

export interface InstanceGraph {
  nodes: GraphNode[]
  edges: GraphEdge[]
  /**
   * WHAT THE CEILING REFUSED, by node key. Never silent: a canvas that
   * quietly dropped half an expansion would show a customer with three
   * transactions who has forty, and nothing on screen could say so.
   */
  refused: number
}

/**
 * THE MOST OBJECTS ON ONE CANVAS.
 *
 * DEV_UI.md 14.1, on what the studies found: force-directed
 * "performed better at graphs with 20 nodes but become less readable
 * as the amount of nodes increased". So this is not a performance
 * ceiling -- ECharts would draw a thousand -- it is a legibility one,
 * and the number is a judgement sitting a little above where the
 * research says reading starts to suffer.
 *
 * REFUSED RATHER THAN TRUNCATED, which is this project's standing
 * answer wherever a ceiling meets a set: `/matching-ids` and the
 * export both refuse and say the real count. A graph that silently
 * stopped adding would be a lie about what is attached to what.
 */
export const MAX_NODES = 60

export function nodeKey(type: string, id: string): string {
  return `${type}/${id}`
}

export const EMPTY: InstanceGraph = { nodes: [], edges: [], refused: 0 }

/**
 * A canvas holding these objects and nothing else.
 *
 * USED WHEN THE SET CHANGES, not when it grows. Switching object type
 * or changing a filter makes a different subject, and keeping the old
 * nodes beside the new ones would draw a graph of two questions.
 */
export function seed(objects: Array<{ type: string; id: string; title: string }>): InstanceGraph {
  const nodes: GraphNode[] = []
  const seen = new Set<string>()
  let refused = 0
  for (const object of objects) {
    const key = nodeKey(object.type, object.id)
    if (seen.has(key)) continue
    if (nodes.length >= MAX_NODES) {
      refused += 1
      continue
    }
    seen.add(key)
    nodes.push({ key, type: object.type, id: object.id, title: object.title, expanded: false })
  }
  return { nodes, edges: [], refused }
}

/**
 * The graph with one object's links pulled in.
 *
 * THE SOURCE IS MARKED EXPANDED EVEN WHEN IT HAS NO LINKS, and that is
 * the point of the flag. "This customer has no transactions" and "I
 * have not asked yet" look identical on a canvas otherwise, and the
 * first is an answer.
 *
 * AN EDGE IS KEPT EVEN WHEN ITS TARGET WAS REFUSED? NO -- an edge
 * needs both ends, and an edge to a node that is not drawn is a line
 * into empty space. The refusal is reported instead.
 */
export function expand(
  graph: InstanceGraph,
  from: GraphNode,
  found: Array<{ type: string; id: string; title: string; field: string }>,
): InstanceGraph {
  const nodes = [...graph.nodes]
  const byKey = new Map(nodes.map((node) => [node.key, node]))
  const edges = [...graph.edges]
  const edgeKeys = new Set(edges.map((edge) => `${edge.source}->${edge.target}:${edge.field}`))
  let refused = graph.refused

  for (const each of found) {
    const key = nodeKey(each.type, each.id)
    if (!byKey.has(key)) {
      if (nodes.length >= MAX_NODES) {
        refused += 1
        continue
      }
      const node: GraphNode = {
        key,
        type: each.type,
        id: each.id,
        title: each.title,
        expanded: false,
      }
      nodes.push(node)
      byKey.set(key, node)
    }
    // A LINK TO ITSELF IS NOT AN EDGE. It happens -- a parent account
    // whose parent is itself -- and a self-loop reads as a smudge
    // rather than as information.
    if (key === from.key) continue
    const edgeKey = `${from.key}->${key}:${each.field}`
    if (edgeKeys.has(edgeKey)) continue
    edgeKeys.add(edgeKey)
    edges.push({ source: from.key, target: key, field: each.field })
  }

  return {
    nodes: nodes.map((node) => (node.key === from.key ? { ...node, expanded: true } : node)),
    edges,
    refused,
  }
}

/** Whether anything more can be added. */
export function isFull(graph: InstanceGraph): boolean {
  return graph.nodes.length >= MAX_NODES
}

/**
 * The link fields of one type, with what each points at.
 *
 * READ FROM THE CALLER'S OWN SCHEMA, so a link they may not discover
 * is not a link they can expand -- the same filtering every other
 * screen gets, by using the same source rather than a second one.
 */
export function linkFieldsOf(
  visibleSchema: Record<string, { fields?: Record<string, { type?: string; target?: string }> }> | null,
  objectType: string,
): Array<{ field: string; target: string }> {
  const fields = visibleSchema?.[objectType]?.fields ?? {}
  return Object.entries(fields)
    .filter(([, field]) => field.type === 'link' && typeof field.target === 'string')
    .map(([field, info]) => ({ field, target: info.target as string }))
}

/**
 * One object's link values as things to add.
 *
 * A LINK FIELD HOLDS AN ID OR A LIST OF THEM, depending on its
 * cardinality -- `get_field` resolves "one" to an id and "many" to a
 * list, and a caller that assumed either would silently draw nothing
 * for half the ontology.
 *
 * THE TITLE IS THE ID HERE, deliberately. Resolving every target's
 * real title would be one request per target, which turns a single
 * expansion into forty; the canvas shows ids and the inspector, which
 * reads one object at a time, shows names. An id on a node is honest
 * and cheap; a blank one would be neither.
 */
export function targetsFrom(
  fields: Record<string, unknown> | null,
  links: Array<{ field: string; target: string }>,
): Array<{ type: string; id: string; title: string; field: string }> {
  const found: Array<{ type: string; id: string; title: string; field: string }> = []
  for (const { field, target } of links) {
    const value = fields?.[field]
    if (value === null || value === undefined) continue
    const ids = Array.isArray(value) ? value : [value]
    for (const id of ids) {
      if (id === null || id === undefined || id === '') continue
      found.push({ type: target, id: String(id), title: String(id), field })
    }
  }
  return found
}
