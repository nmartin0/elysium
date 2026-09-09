/**
 * SchemaGraph -- the ontology as a picture rather than three lists.
 *
 * Object types as nodes, link types as edges. Schema shows exactly
 * this information today as tables that make you reconstruct the shape
 * in your head: click a link type, read which two types it joins,
 * remember it, click the next.
 *
 * BOUNDED BY OBJECT TYPES, not objects. A dozen nodes, not a million
 * -- which is why this needs none of the count-before-expand
 * machinery an instance graph would, and why it can be drawn all at
 * once without becoming a hairball.
 *
 * DERIVED FROM THE CALLER'S visible_schema, so a type they cannot read
 * is not a node they can see. That falls out of using the same source
 * the tables use rather than being a check this file performs.
 */

import { useEffect, useMemo, useState } from 'react'
import { Callout } from '@blueprintjs/core'
import Chart from '@elysium/shell-api/components/Chart'
import { getVisibleActionTypesCached } from '@elysium/shell-api/api'
import type { VisibleSchema } from '@elysium/shell-api/types'

import { groupLinkTypes } from './LinkTypes'

interface SchemaGraphProps {
  schema: VisibleSchema
  /** Clicking a node opens that type, the same as clicking it in a
   *  table. A graph you can only look at is a diagram; one you can
   *  navigate is part of the app. */
  onSelectType: (objectType: string) => void
}

export interface GraphNode {
  name: string
  value: number
  x: number
  y: number
  /** Object types and action types are drawn differently, because they
   *  are different KINDS of thing -- one is a noun, the other a verb
   *  that operates on nouns. */
  kind: 'object' | 'action'
}

export interface GraphEdge {
  source: string
  target: string
  name: string
  /** "1:M", "M:1", "M:N" -- shown ON the edge. Reading a
   *  relationship's shape is most of what a schema diagram is for, and
   *  it was only available by opening a table. */
  label: string
  kind: 'link' | 'affects'
}

export interface GraphModel {
  nodes: GraphNode[]
  links: GraphEdge[]
}

/**
 * A cardinality as it is written on an ER diagram.
 *
 * one_to_many becomes 1:M rather than being spelled out, because an
 * edge label competes with the node labels around it and the short
 * form is the one people already read on diagrams.
 */
export function cardinalityLabel(cardinality: string): string {
  const parts = cardinality.split('_to_')
  if (parts.length !== 2) return cardinality
  const symbol = (side?: string) => (side === 'many' ? 'M' : '1')
  const left = symbol(parts[0])
  const right = symbol(parts[1])
  // M:M is conventionally written M:N -- two "many" sides are not the
  // same many, and one letter twice implies they are.
  if (left === 'M' && right === 'M') return 'M:N'
  return `${left}:${right}`
}

/**
 * Nodes and edges from the visible schema.
 *
 * Exported and pure, because everything worth testing about this
 * lives here -- the chart itself draws to a canvas jsdom cannot read.
 */
export function buildGraph(
  schema: VisibleSchema,
  // Keyed by api_name, matching what the endpoint returns. Taking the
  // record rather than an array means buildGraph cannot be handed a
  // shape the API never produces.
  actionTypes: Record<string, { display_name?: string | null;
                                affected_object_types?: string[] }> = {},
): GraphModel {
  // SORTED, so the starting positions below come from a stable order
  // rather than whatever order the object arrived in.
  const names = Object.keys(schema).sort()

  // Actions that touch at least one VISIBLE type. One affecting only
  // types this caller cannot read would be a node connected to
  // nothing, which says "there is something here you may not see" --
  // the disclosure uniform denial exists to prevent.
  const visibleActions = Object.entries(actionTypes).filter(([, action]) =>
    (action.affected_object_types ?? []).some((type) => type in schema))
  const actionNames = visibleActions.map(([apiName]) => apiName).sort()

  const total = Math.max(names.length + actionNames.length, 1)

  // DETERMINISTIC starting positions, on a circle. ECharts seeds a
  // force layout randomly, so the same ontology drew a different
  // picture every visit.
  const nodes: GraphNode[] = names.map((name, index) => ({
    // value sizes the node: a type with more fields is a bigger thing
    // in the ontology, and that is worth seeing at a glance.
    name,
    value: Object.keys(schema[name]?.fields ?? {}).length,
    x: Math.cos((index / total) * 2 * Math.PI) * 220,
    y: Math.sin((index / total) * 2 * Math.PI) * 220,
    kind: 'object' as const,
  }))

  // Actions continue around the SAME circle, so the two kinds
  // interleave rather than the actions all starting on one side.
  for (const [offset, apiName] of actionNames.entries()) {
    const index = names.length + offset
    nodes.push({
      name: apiName,
      value: 0,
      x: Math.cos((index / total) * 2 * Math.PI) * 220,
      y: Math.sin((index / total) * 2 * Math.PI) * 220,
      kind: 'action',
    })
  }

  const known = new Set(names)
  const links: GraphEdge[] = []
  const seen = new Set<string>()

  for (const [linkType, sides] of groupLinkTypes(schema)) {
    for (const side of sides) {
      // A link whose TARGET is invisible to this caller is dropped
      // rather than drawn to a node that is not there. That is not a
      // security decision -- the schema is already scoped -- it is
      // that an edge to nowhere is a drawing bug.
      if (!known.has(side.target) || !known.has(side.objectType)) continue

      // Both sides of a link type describe ONE relationship, so the
      // pair is drawn once. Without this a two-sided link becomes two
      // edges between the same nodes, which reads as two
      // relationships.
      const pair = [side.objectType, side.target].sort().join('\u0000') + linkType
      if (seen.has(pair)) continue
      seen.add(pair)

      links.push({
        source: side.objectType,
        target: side.target,
        name: linkType,
        label: cardinalityLabel(side.cardinality),
        kind: 'link',
      })
    }
  }

  // Action -> the object types it affects.
  for (const [apiName, action] of visibleActions) {
    for (const objectType of action.affected_object_types ?? []) {
      if (!known.has(objectType)) continue
      links.push({
        source: apiName,
        target: objectType,
        name: apiName,
        label: 'affects',
        kind: 'affects',
      })
    }
  }

  return { nodes, links }
}

interface ActionTypeSummary {
  display_name?: string | null
  affected_object_types?: string[]
}

export default function SchemaGraph({ schema, onSelectType }: SchemaGraphProps) {
  // A RECORD keyed by api_name, which is what the endpoint returns --
  // not an array. A first version called .filter() on it, which throws
  // in render, and an uncaught throw in render is a WHITE SCREEN
  // rather than an error message. Found by looking at it.
  const [actionTypes, setActionTypes] = useState<Record<string, ActionTypeSummary>>({})

  useEffect(() => {
    let cancelled = false
    // The same PROMISE cache the Action types table uses, so opening
    // both does not fetch twice and they cannot disagree about what
    // exists.
    //
    // A failure is swallowed deliberately: the object types come from
    // the schema already in hand, so the graph still draws. An error
    // banner over a working diagram would be worse than quietly having
    // no action nodes, and Action types itself reports the failure.
    getVisibleActionTypesCached()
      .then((body) => {
        if (!cancelled) setActionTypes((body as Record<string, ActionTypeSummary>) ?? {})
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [])

  const model = useMemo(() => buildGraph(schema, actionTypes), [schema, actionTypes])

  if (model.nodes.length === 0) {
    return (
      <Callout intent="none">
        You do not have read access to any object type in this ontology.
      </Callout>
    )
  }

  const option = {
    tooltip: {},
    series: [{
      type: 'graph',
      layout: 'force',
      // roam keeps zoom and pan; draggable keeps clicking a node and
      // moving it. Both are worth having and neither requires the
      // simulation to keep running.
      roam: true,
      draggable: true,
      // NO layout animation, which is what made it "squiggly and
      // bouncy". The force simulation still decides the arrangement --
      // it simply settles before the first paint instead of visibly
      // wobbling into place. Combined with deterministic starting
      // positions, the same ontology arrives at the same picture, and
      // arrives at it still.
      force: { repulsion: 420, edgeLength: 170, layoutAnimation: false },
      label: { show: true, position: 'right' },
      emphasis: { focus: 'adjacency' },
      // An arrow at the target end. A relationship has a direction and
      // an undirected line loses it -- "1:M" alone does not say which
      // side is the many.
      edgeSymbol: ['none', 'arrow'],
      edgeSymbolSize: 8,
      edgeLabel: { show: true, formatter: '{c}', fontSize: 10 },
      data: model.nodes.map((node) => ({
        name: node.name,
        value: node.value,
        x: node.x,
        y: node.y,
        // Actions are DIAMONDS, object types circles. Shape rather
        // than colour carries the distinction, because shape survives
        // a colour-blind reader and a greyscale print, and because
        // colour is already spoken for if this ever gains more
        // meaning.
        symbol: node.kind === 'action' ? 'diamond' : 'circle',
        symbolSize: node.kind === 'action' ? 18 : 22 + Math.min(node.value, 8) * 3,
        itemStyle: node.kind === 'action' ? { opacity: 0.75 } : {},
      })),
      links: model.links.map((link) => ({
        source: link.source,
        target: link.target,
        value: link.label,
        // An action's edge is dashed: it is not a relationship BETWEEN
        // data, it is something that operates on it. Same reason the
        // node shape differs.
        lineStyle: link.kind === 'affects'
          ? { type: 'dashed', opacity: 0.45, curveness: 0.1 }
          : { opacity: 0.7, curveness: 0.1 },
      })),
    }],
  }

  return (
    <Chart
      option={option}
      height={480}
      ariaLabel={
        `Ontology graph: ${model.nodes.filter((n) => n.kind === 'object').length} object types, `
        + `${model.nodes.filter((n) => n.kind === 'action').length} action types, `
        + `${model.links.length} relationships`
      }
      onSelect={onSelectType}
    />
  )
}
