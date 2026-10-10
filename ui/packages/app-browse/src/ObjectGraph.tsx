/**
 * The set as a canvas -- objects and the links between them.
 *
 * DEV_UI.md section 5 item 7: "A GRAPH CANVAS for instance-level
 * exploration -- objects and links, expanded by search-around. The
 * resolution exists; this is rendering."
 *
 * A MODE OF BROWSE, NOT AN APP, which section 12 settles: the six apps
 * are "a decomposition BY FEATURE, the way software gets built, not BY
 * WHAT THE USER IS WORKING ON", and a set of objects "should be one
 * workspace with MODES -- table, graph, chart -- and switching mode
 * must not lose the set, which today it does, because they are
 * different apps." So this sits behind the same `view` key the table
 * and the charts do, and inherits the set, the filters and the URL.
 *
 * FORCE-DIRECTED, AND 14.1 ARGUES THE OTHER WAY FOR THE OTHER CANVAS.
 * Layered wins for the ONTOLOGY, where "hierarchy and semantic depth
 * are critical". Here the finding that applies is the one after it:
 * "for path-following tasks, orthogonal and force-directed layouts
 * need LESS link-tracing effort than hierarchical, because
 * hierarchical layouts draw attention to line crossings. Following a
 * chain of links is exactly what a person does here."
 *
 * IT GROWS BY EXPANSION RATHER THAN ARRIVING COMPLETE, which is the
 * prior art's own model -- "add objects, click one for its properties,
 * run Search Arounds to pull in related objects" -- and also the only
 * affordable one. Only a per-object read returns an object's link
 * values, so drawing every edge among fifty seeded nodes would be
 * fifty requests before anything appeared. One request per expansion
 * puts the cost where the question is.
 */

import { useEffect, useMemo, useState } from 'react'
import { Button } from '@blueprintjs/core'

import Chart from '@elysium/shell-api/components/Chart'
import ErrorState from '@elysium/shell-api/components/ErrorState'
import Notice from '@elysium/shell-api/components/Notice'
import StatusTag from '@elysium/shell-api/components/StatusTag'
import { getErrorMessage, getObjectDetail, handleIfSessionExpired } from '@elysium/shell-api/api'
import type { VisibleSchema } from '@elysium/shell-api/types'

import {
  EMPTY,
  type GraphNode,
  type InstanceGraph,
  MAX_NODES,
  expand,
  isFull,
  linkFieldsOf,
  seed,
  targetsFrom,
} from './instanceGraph'

export default function ObjectGraph({
  objectType,
  results,
  visibleSchema,
  onSessionExpired,
}: {
  objectType: string | null
  /** The page of the set, as the table has it. */
  results: Array<{ id: string; fields?: Record<string, unknown> | null }>
  visibleSchema: VisibleSchema | null
  onSessionExpired: () => void
}) {
  const [graph, setGraph] = useState<InstanceGraph>(EMPTY)
  const [selected, setSelected] = useState<string | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // THE SET IS THE SUBJECT, so a new one is a new canvas. Switching
  // type or changing a filter asks a different question, and keeping
  // the old nodes beside the new ones would draw two of them at once.
  //
  // KEYED ON THE IDS, not on the array: a re-render that produced an
  // equal list would otherwise throw away an exploration somebody had
  // built up.
  const seedKey = `${objectType ?? ''}:${results.map((result) => result.id).join(',')}`
  useEffect(() => {
    setGraph(
      seed(
        results.map((result) => ({
          type: objectType ?? '',
          id: String(result.id),
          title: String(result.id),
        })),
      ),
    )
    setSelected(null)
    setProblem(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- seedKey IS the dependency
  }, [seedKey])

  const byKey = useMemo(() => new Map(graph.nodes.map((node) => [node.key, node])), [graph.nodes])
  const chosen = selected === null ? null : (byKey.get(selected) ?? null)

  async function pullIn(node: GraphNode) {
    setProblem(null)
    setBusy(true)
    try {
      const links = linkFieldsOf(visibleSchema as never, node.type)
      const detail = await getObjectDetail(node.type, node.id)
      const fields = (detail as { fields?: Record<string, unknown> | null })?.fields ?? null
      setGraph((current) => expand(current, node, targetsFrom(fields, links)))
    } catch (error) {
      if (handleIfSessionExpired(error, onSessionExpired)) return
      setProblem(getErrorMessage(error))
    } finally {
      setBusy(false)
    }
  }

  if (!objectType) return null

  if (graph.nodes.length === 0) {
    return (
      <Notice state="active" title="Nothing to draw">
        This set has no objects in it. Narrow it differently and the graph will follow.
      </Notice>
    )
  }

  // ONE CATEGORY PER TYPE, which is what carries kind on a canvas that
  // mixes them. DEV_UI.md 13.1 states the rule for the ontology
  // canvas and it holds here: "Colour carries kind, not decoration."
  //
  // A LEGEND RATHER THAN A PREFIX ON EVERY LABEL. `Transaction 3`
  // beside `Customer cust_002` reads as noise on a graph of one type,
  // which is most of them; the colour costs nothing until a second
  // type arrives and then says it at a glance.
  //
  // COLOURS COME FROM Chart, which applies this project's palette so
  // no caller picks one -- its own comment records why: before it,
  // "two charts on one screen could use different palettes, and none
  // of them was checked for colour vision deficiency."
  const types = [...new Set(graph.nodes.map((node) => node.type))]

  const option = {
    legend: types.length > 1 ? { data: types, bottom: 0 } : undefined,
    series: [
      {
        type: 'graph',
        layout: 'force',
        roam: true,
        draggable: true,
        // NO LAYOUT ANIMATION, for the reason SchemaGraph gives: the
        // simulation still decides the arrangement, it simply settles
        // before the first paint instead of visibly wobbling. 14.1 is
        // blunt about why that matters -- a poor layout makes people
        // spend "up to 25 percent of their time on manual layout
        // adjustments".
        force: { repulsion: 260, edgeLength: 110, layoutAnimation: false },
        label: { show: true, position: 'right', fontSize: 10 },
        labelLayout: { hideOverlap: true },
        emphasis: { focus: 'adjacency' },
        edgeSymbol: ['none', 'arrow'],
        edgeSymbolSize: 7,
        edgeLabel: { show: true, formatter: '{c}', fontSize: 9 },
        categories: types.map((type) => ({ name: type })),
        data: graph.nodes.map((node) => ({
          name: node.key,
          category: types.indexOf(node.type),
          // THE TITLE IS WHAT A PERSON READS; the key is what ECharts
          // and every click handler use. Showing the key would put
          // `Customer/cust_001` on every node.
          value: node.title,
          label: { formatter: node.title },
          symbol: 'circle',
          // AN UNEXPLORED NODE IS HOLLOW. "Nothing is attached" and "I
          // have not looked" are different facts, and a canvas that
          // drew them alike is one people stop trusting.
          symbolSize: node.key === selected ? 26 : 18,
          itemStyle: node.expanded ? {} : { opacity: 0.55 },
        })),
        links: graph.edges.map((edge) => ({
          source: edge.source,
          target: edge.target,
          value: edge.field,
          lineStyle: { opacity: 0.7, curveness: 0.12 },
        })),
      },
    ],
  }

  return (
    <div className="object-graph">
      {graph.refused > 0 && (
        /* REFUSED, NOT TRUNCATED, and said out loud. A canvas that
           quietly stopped adding would show a customer with three
           transactions who has forty. */
        <Notice state="pending" title="More than this canvas can draw">
          {`${graph.refused} more would not fit. A graph stops being readable above about ${MAX_NODES} nodes, so narrow the set or explore from fewer.`}
        </Notice>
      )}
      {problem !== null && <ErrorState>{problem}</ErrorState>}
      <Chart
        option={option}
        height={520}
        /* WHAT IS ON THE CANVAS, counted honestly. A first version
           said "4 Customer objects" after an expansion had pulled in
           two Transactions -- a graph mixes types by design, which is
           the whole reason the categories above exist. */
        ariaLabel={
          `${graph.nodes.length} ${graph.nodes.length === 1 ? 'object' : 'objects'}` +
          `${types.length > 1 ? ` across ${types.length} types` : ` of type ${types[0] ?? objectType}`}` +
          ` and ${graph.edges.length} ${graph.edges.length === 1 ? 'link' : 'links'} between them`
        }
        onSelect={(name, dataType) => {
          // AN EDGE HAS NO NAME, which is why this checks the type --
          // Chart's own comment records that a handler reading only
          // the name "silently ignores every edge click".
          if (dataType === 'edge') return
          setSelected(name)
        }}
      />
      {chosen !== null && (
        <aside className="object-graph__chosen">
          <h3>{chosen.title}</h3>
          <p className="object-graph__kind">{chosen.type}</p>
          {chosen.expanded ? (
            <StatusTag state="granted">Links pulled in</StatusTag>
          ) : (
            <Button small icon="graph" loading={busy} disabled={isFull(graph)} onClick={() => void pullIn(chosen)}>
              Pull in its links
            </Button>
          )}
          {isFull(graph) && !chosen.expanded && <p className="object-graph__full">The canvas is full.</p>}
        </aside>
      )}
    </div>
  )
}
