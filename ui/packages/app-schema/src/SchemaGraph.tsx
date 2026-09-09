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

import { useMemo } from 'react'
import { Callout } from '@blueprintjs/core'
import Chart from '@elysium/shell-api/components/Chart'
import type { VisibleSchema } from '@elysium/shell-api/types'

import { groupLinkTypes } from './LinkTypes'

interface SchemaGraphProps {
  schema: VisibleSchema
  /** Clicking a node opens that type, the same as clicking it in a
   *  table. A graph you can only look at is a diagram; one you can
   *  navigate is part of the app. */
  onSelectType: (objectType: string) => void
}

export interface GraphModel {
  nodes: { name: string; value: number }[]
  links: { source: string; target: string; name: string }[]
}

/**
 * Nodes and edges from the visible schema.
 *
 * Exported and pure, because everything worth testing about this
 * lives here -- the chart itself draws to a canvas jsdom cannot read.
 */
export function buildGraph(schema: VisibleSchema): GraphModel {
  const nodes = Object.keys(schema).map((name) => ({
    // value sizes the node: a type with more fields is a bigger thing
    // in the ontology, and that is worth seeing at a glance.
    name,
    value: Object.keys(schema[name]?.fields ?? {}).length,
  }))

  const known = new Set(nodes.map((node) => node.name))
  const links: GraphModel['links'] = []
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

      links.push({ source: side.objectType, target: side.target, name: linkType })
    }
  }

  return { nodes, links }
}

export default function SchemaGraph({ schema, onSelectType }: SchemaGraphProps) {
  const model = useMemo(() => buildGraph(schema), [schema])

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
      roam: true,
      // Labels always on. An unlabelled node is a dot, and this graph
      // exists to be read rather than admired.
      label: { show: true, position: 'right' },
      edgeLabel: { show: true, formatter: '{c}', fontSize: 10 },
      force: {
        repulsion: 320,
        edgeLength: 140,
        // Slower than the default, because a force layout that settles
        // instantly appears to have jumped rather than arranged
        // itself, and the motion is what shows which nodes are pulled
        // together.
        friction: 0.15,
      },
      emphasis: { focus: 'adjacency' },
      symbolSize: (value: number) => 22 + Math.min(value, 8) * 3,
      data: model.nodes.map((node) => ({
        name: node.name,
        value: node.value,
        symbolSize: 22 + Math.min(node.value, 8) * 3,
      })),
      links: model.links.map((link) => ({
        source: link.source,
        target: link.target,
        value: link.name,
        label: { show: false },
      })),
      lineStyle: { curveness: 0.1, opacity: 0.7 },
    }],
  }

  return (
    <Chart
      option={option}
      height={480}
      ariaLabel={`Ontology graph: ${model.nodes.length} object types, ${model.links.length} link types`}
      onSelect={onSelectType}
    />
  )
}
