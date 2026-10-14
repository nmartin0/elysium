/**
 * The ontology canvas (DEV_UI 14): types laid out in layers, links as
 * orthogonal edges, actions on the type, positions that stay where a
 * person puts them, subject areas to navigate by, and the security
 * chains on a layer of their own.
 *
 * WHAT IT REPLACES. An ECharts force layout with actions as diamond
 * nodes. Force layouts "become less readable as the amount of nodes
 * increased", positions could not be kept, and a diamond per action
 * turned a structure diagram into a process diagram (14.3).
 *
 * SVG WE DRAW, not a chart library: nodes need badges, keyboard focus
 * and dragging; edges need orthogonal routes and a second visual
 * language for security. Each is a few lines here and a fight with a
 * charting library's idea of a graph.
 *
 * WITHOUT THE MOUSE (DEV_UI 10.4): Tab reaches every type, Enter opens
 * it in the inspector, the arrow keys move it (Shift for further), and
 * the zoom controls are buttons.
 */

import { Button, Checkbox, Dialog, DialogBody, DialogFooter, InputGroup, Switch } from '@blueprintjs/core'
import {
  getErrorMessage,
  getOntologyCanvas,
  getVisibleActionTypesCached,
  handleIfSessionExpired,
  type OntologyCanvasLayout,
  saveOntologyCanvas,
} from '@elysium/shell-api/api'
import Notice from '@elysium/shell-api/components/Notice'
import { pluralise } from '@elysium/shell-api/format'
import type { VisibleSchema } from '@elysium/shell-api/types'
import { useEffect, useId, useMemo, useRef, useState } from 'react'

import {
  NODE_HEIGHT,
  NODE_WIDTH,
  type Point,
  type View,
  clampScale,
  fitView,
  labelPoint,
  lanes,
  pathOf,
  placeNodes,
  routeEdge,
} from './canvasLayout'
import { type SubjectArea, buildCanvasModel, declaredAreas } from './canvasModel'
import type { GraphSelection } from './GraphPreview'

interface OntologyCanvasProps {
  schema: VisibleSchema
  selection: GraphSelection | null
  onSelect: (selection: GraphSelection) => void
  onSessionExpired?: () => void
}

type Layout = OntologyCanvasLayout

const EMPTY: Layout = { positions: {}, areas: [] }
const HEIGHT = 560
/** How far an arrow key moves a type, and with Shift. */
const NUDGE = 16
const SHOVE = 64
/** Movement under this is a click, not a drag. */
const DRAG_THRESHOLD = 4
/** A burst of arrow-key moves is saved once, after it stops. */
const SAVE_AFTER_MS = 600
const MAX_LABEL = 22

function shorten(text: string): string {
  return text.length > MAX_LABEL ? `${text.slice(0, MAX_LABEL - 1)}…` : text
}

/** A subject area's identity: declared and personal ones may share a name. */
function areaKey(area: SubjectArea): string {
  return `${area.declared ? 'ontology' : 'mine'}:${area.name}`
}

type Gesture =
  | { kind: 'drag'; name: string; pointerX: number; pointerY: number; from: Point; moved: boolean }
  | { kind: 'pan'; pointerX: number; pointerY: number; from: View }

export default function OntologyCanvas({ schema, selection, onSelect, onSessionExpired }: OntologyCanvasProps) {
  const markerId = useId().replace(/:/g, '')
  const [actionTypes, setActionTypes] = useState<Record<string, { affected_object_types?: string[] }>>({})
  const [layout, setLayout] = useState<Layout>(EMPTY)
  const [loaded, setLoaded] = useState(false)
  const [saveState, setSaveState] = useState<
    { kind: 'idle' | 'saving' | 'saved' } | { kind: 'failed'; message: string }
  >({ kind: 'idle' })
  const [moving, setMoving] = useState<{ name: string; point: Point } | null>(null)
  const [view, setView] = useState<View | null>(null)
  const [activeArea, setActiveArea] = useState<string | null>(null)
  const [showSecurity, setShowSecurity] = useState(false)
  const [undoPositions, setUndoPositions] = useState<Layout['positions'] | null>(null)
  const [areaDialog, setAreaDialog] = useState<{ original: string | null } | null>(null)
  const [width, setWidth] = useState(900)

  const latestSessionExpired = useRef(onSessionExpired)
  useEffect(() => {
    latestSessionExpired.current = onSessionExpired
  })

  useEffect(() => {
    let cancelled = false
    // A FAILURE TO LIST ACTIONS IS FEWER BADGES, not a broken canvas --
    // Action types reports it where it belongs.
    getVisibleActionTypesCached()
      .then((body) => {
        if (!cancelled) setActionTypes((body as Record<string, { affected_object_types?: string[] }>) ?? {})
      })
      .catch(() => {})
    // A FAILURE TO READ THE LAYOUT IS THE AUTOMATIC ONE, said once.
    getOntologyCanvas()
      .then((body) => {
        if (cancelled) return
        setLayout({ positions: body.positions ?? {}, areas: body.areas ?? [], security_chains: body.security_chains })
        setLoaded(true)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        const expired = latestSessionExpired.current
        if (expired && handleIfSessionExpired(err, expired)) return
        setSaveState({ kind: 'failed', message: `Your arrangement could not be loaded: ${getErrorMessage(err)}` })
        setLoaded(true)
      })
    return () => {
      cancelled = true
    }
  }, [])

  // THE WIDTH IS MEASURED, so "fit" fits the canvas actually on screen.
  // jsdom has no ResizeObserver; the default stands in there.
  const frame = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    const node = frame.current
    if (!node || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setWidth(Math.max(320, Math.round(entry.contentRect.width)))
    })
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  const model = useMemo(() => buildCanvasModel(schema, actionTypes), [schema, actionTypes])
  const placed = useMemo(
    () =>
      placeNodes(
        model.types.map((type) => type.name),
        model.links,
        moving ? { ...layout.positions, [moving.name]: moving.point } : layout.positions,
      ),
    [model, layout.positions, moving],
  )

  const chains = layout.security_chains
  const chainByType = useMemo(() => new Map((chains ?? []).map((chain) => [chain.type, chain])), [chains])

  const areas: SubjectArea[] = useMemo(
    () => [...declaredAreas(model.types), ...layout.areas.map((area) => ({ ...area, declared: false }))],
    [model.types, layout.areas],
  )
  const area = areas.find((candidate) => areaKey(candidate) === activeArea) ?? null
  const members = area ? new Set(area.types) : null

  // FIT ONCE, when the layout first arrives -- never again on its own, or
  // the view would jump every time somebody moved a node.
  const shownView = view ?? fitView(Object.values(placed), width, HEIGHT)
  const fitTo = (names: string[]) => {
    const centres = names.map((name) => placed[name]).filter((point): point is NonNullable<typeof point> => !!point)
    setView(fitView(centres.length > 0 ? centres : Object.values(placed), width, HEIGHT))
  }

  // ---- saving ----------------------------------------------------------
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(
    () => () => {
      if (saveTimer.current) clearTimeout(saveTimer.current)
    },
    [],
  )
  const persist = (next: Pick<Layout, 'positions' | 'areas'>, delay = 0) => {
    // OPTIMISTIC, because a node that snaps back while the save is in
    // flight looks like the drag failed. The answer replaces it: the
    // server says what it KEPT.
    setLayout((current) => ({ ...current, ...next }))
    if (saveTimer.current) clearTimeout(saveTimer.current)
    const send = () => {
      setSaveState({ kind: 'saving' })
      saveOntologyCanvas(next)
        .then((kept) => {
          setLayout((current) => ({ ...current, positions: kept.positions, areas: kept.areas }))
          setSaveState({ kind: 'saved' })
        })
        .catch((err: unknown) => {
          const expired = latestSessionExpired.current
          if (expired && handleIfSessionExpired(err, expired)) return
          setSaveState({ kind: 'failed', message: `Not saved: ${getErrorMessage(err)}` })
        })
    }
    if (delay > 0) saveTimer.current = setTimeout(send, delay)
    else send()
  }

  const moveTo = (name: string, point: Point, delay = 0) => {
    setUndoPositions(null)
    persist({ positions: { ...layout.positions, [name]: { x: point.x, y: point.y } }, areas: layout.areas }, delay)
  }

  // AUTO-LAYOUT ONLY MOVES COORDINATES (14.2), and it throws away a
  // person's arrangement -- so it is UNDOABLE rather than confirmed:
  // 10.1's order of preference is "prevented, undoable, or confirmed".
  const autoLayout = () => {
    setUndoPositions(layout.positions)
    persist({ positions: {}, areas: layout.areas })
    setView(null)
  }
  const undoAutoLayout = () => {
    if (!undoPositions) return
    persist({ positions: undoPositions, areas: layout.areas })
    setUndoPositions(null)
  }

  // ---- pointer gestures -------------------------------------------------
  const gesture = useRef<Gesture | null>(null)
  // A DRAG ENDS IN A CLICK on the same element; that click must not also
  // select the type, or every move opens the inspector.
  const suppressClick = useRef(false)

  const onNodePointerDown = (event: React.PointerEvent, name: string) => {
    event.stopPropagation()
    const at = placed[name]
    if (!at) return
    gesture.current = { kind: 'drag', name, pointerX: event.clientX, pointerY: event.clientY, from: at, moved: false }
    ;(event.currentTarget as Element).setPointerCapture?.(event.pointerId)
  }
  const onBackgroundPointerDown = (event: React.PointerEvent) => {
    gesture.current = { kind: 'pan', pointerX: event.clientX, pointerY: event.clientY, from: shownView }
    ;(event.currentTarget as Element).setPointerCapture?.(event.pointerId)
  }
  const onPointerMove = (event: React.PointerEvent) => {
    const current = gesture.current
    if (!current) return
    const dx = event.clientX - current.pointerX
    const dy = event.clientY - current.pointerY
    if (current.kind === 'pan') {
      setView({ ...current.from, x: current.from.x + dx, y: current.from.y + dy })
      return
    }
    if (!current.moved && Math.hypot(dx, dy) < DRAG_THRESHOLD) return
    current.moved = true
    setMoving({
      name: current.name,
      point: { x: current.from.x + dx / shownView.scale, y: current.from.y + dy / shownView.scale },
    })
  }
  const onPointerUp = () => {
    const current = gesture.current
    gesture.current = null
    if (current?.kind === 'drag' && current.moved && moving) {
      suppressClick.current = true
      moveTo(moving.name, moving.point)
    }
    setMoving(null)
  }

  // CTRL/CMD + WHEEL ZOOMS, a plain wheel scrolls the page. Hijacking the
  // plain wheel would trap a reader scrolling past the canvas inside it.
  // Native and non-passive, because React's wheel listener is passive
  // and cannot stop the browser zooming the whole page instead.
  const svgRef = useRef<SVGSVGElement | null>(null)
  const viewRef = useRef(shownView)
  useEffect(() => {
    viewRef.current = shownView
  })
  useEffect(() => {
    const svg = svgRef.current
    if (!svg) return
    const onWheel = (event: WheelEvent) => {
      if (!event.ctrlKey && !event.metaKey) return
      event.preventDefault()
      const box = svg.getBoundingClientRect()
      zoomAbout(Math.exp(-event.deltaY * 0.002), { x: event.clientX - box.left, y: event.clientY - box.top })
    }
    svg.addEventListener('wheel', onWheel, { passive: false })
    return () => svg.removeEventListener('wheel', onWheel)
  })

  function zoomAbout(factor: number, about: Point = { x: width / 2, y: HEIGHT / 2 }) {
    const current = viewRef.current
    const scale = clampScale(current.scale * factor)
    const ratio = scale / current.scale
    setView({ scale, x: about.x - (about.x - current.x) * ratio, y: about.y - (about.y - current.y) * ratio })
  }

  // ---- keyboard ---------------------------------------------------------
  const onNodeKeyDown = (event: React.KeyboardEvent, name: string) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      onSelect({ kind: 'object', name })
      return
    }
    const step = event.shiftKey ? SHOVE : NUDGE
    const delta: Record<string, Point> = {
      ArrowLeft: { x: -step, y: 0 },
      ArrowRight: { x: step, y: 0 },
      ArrowUp: { x: 0, y: -step },
      ArrowDown: { x: 0, y: step },
    }
    const move = delta[event.key]
    const at = placed[name]
    if (!move || !at) return
    event.preventDefault()
    moveTo(name, { x: at.x + move.x, y: at.y + move.y }, SAVE_AFTER_MS)
  }

  if (model.types.length === 0) {
    return <Notice state="neutral">You do not have read access to any object type in this ontology.</Notice>
  }

  // ---- edges --------------------------------------------------------------
  const securityEdges =
    showSecurity && chains
      ? chains
          .filter((chain) => chain.kind === 'via' && chain.target && placed[chain.type] && placed[chain.target])
          .map((chain) => ({ source: chain.type, target: chain.target!, field: chain.field }))
      : []
  const drawn = [
    ...model.links.map((link) => ({ ...link, kind: 'link' as const })),
    ...securityEdges.map((edge) => ({
      name: `security:${edge.source}`,
      source: edge.source,
      target: edge.target,
      label: `${edge.source} borrows its security from ${edge.target}, through ${edge.field}`,
      kind: 'security' as const,
    })),
  ]
  const laneOf = lanes(drawn)
  const dimmed = (name: string) => members !== null && !members.has(name)
  const selectedType = selection?.kind === 'object' ? selection.name : null
  const selectedLink = selection?.kind === 'link' ? selection.name : null

  return (
    <div className="ontology-canvas">
      <div className="ontology-canvas__toolbar">
        <Button small minimal icon="zoom-out" aria-label="Zoom out" onClick={() => zoomAbout(1 / 1.25)} />
        <Button
          small
          minimal
          icon="zoom-to-fit"
          aria-label="Fit to screen"
          onClick={() => fitTo(area ? area.types : Object.keys(placed))}
        />
        <Button small minimal icon="zoom-in" aria-label="Zoom in" onClick={() => zoomAbout(1.25)} />
        <Button
          small
          minimal
          icon="layout-hierarchy"
          onClick={autoLayout}
          disabled={Object.keys(layout.positions).length === 0}
        >
          Auto-layout
        </Button>
        {undoPositions && (
          <Button small minimal icon="undo" onClick={undoAutoLayout}>
            Undo auto-layout
          </Button>
        )}
        {chains && (
          <Switch
            className="ontology-canvas__security-switch"
            checked={showSecurity}
            label="Security chains"
            onChange={() => setShowSecurity((on) => !on)}
          />
        )}
        <span className="ontology-canvas__status" aria-live="polite">
          {saveState.kind === 'saving'
            ? 'Saving…'
            : saveState.kind === 'saved'
              ? 'Arrangement saved'
              : saveState.kind === 'failed'
                ? saveState.message
                : !loaded
                  ? 'Loading your arrangement…'
                  : ''}
        </span>
      </div>

      <div className="ontology-canvas__body">
        {/* SUBJECT AREAS BESIDE THE MODEL, as ERwin's pane is: "a
            navigational overlay, not a change to the model". Choosing
            one dims everything else and brings its types into view. */}
        <nav className="ontology-canvas__areas" aria-label="Subject areas">
          <p className="ontology-canvas__areas-title">Subject areas</p>
          <ul>
            <li>
              <button
                type="button"
                className={'ontology-canvas__area' + (area === null ? ' ontology-canvas__area--on' : '')}
                aria-pressed={area === null}
                onClick={() => {
                  setActiveArea(null)
                  fitTo(Object.keys(placed))
                }}
              >
                All types
              </button>
            </li>
            {areas.map((candidate) => (
              <li key={areaKey(candidate)}>
                <button
                  type="button"
                  className={
                    'ontology-canvas__area' + (areaKey(candidate) === activeArea ? ' ontology-canvas__area--on' : '')
                  }
                  aria-pressed={areaKey(candidate) === activeArea}
                  onClick={() => {
                    setActiveArea(areaKey(candidate))
                    fitTo(candidate.types)
                  }}
                >
                  {candidate.name}
                  <span className="ontology-canvas__area-count">{candidate.types.length}</span>
                </button>
                {candidate.declared ? (
                  <span className="ontology-canvas__area-source">from the ontology</span>
                ) : (
                  <Button
                    small
                    minimal
                    icon="edit"
                    aria-label={`Edit ${candidate.name}`}
                    onClick={() => setAreaDialog({ original: candidate.name })}
                  />
                )}
              </li>
            ))}
          </ul>
          <Button small minimal icon="add" onClick={() => setAreaDialog({ original: null })}>
            New subject area
          </Button>
        </nav>

        <div className="ontology-canvas__frame" ref={frame}>
          <svg
            ref={svgRef}
            className="ontology-canvas__svg"
            width="100%"
            height={HEIGHT}
            aria-label={
              `Ontology canvas: ${pluralise(model.types.length, 'object type', 'object types')}, ` +
              pluralise(model.links.length, 'relationship', 'relationships')
            }
            onPointerDown={onBackgroundPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
          >
            <defs>
              <marker
                id={`${markerId}-arrow`}
                viewBox="0 0 10 10"
                refX="9"
                refY="5"
                markerWidth="7"
                markerHeight="7"
                orient="auto"
              >
                <path className="ontology-canvas__arrow" d="M0 0 L10 5 L0 10 z" />
              </marker>
              <marker
                id={`${markerId}-arrow-security`}
                viewBox="0 0 10 10"
                refX="9"
                refY="5"
                markerWidth="7"
                markerHeight="7"
                orient="auto"
              >
                <path className="ontology-canvas__arrow ontology-canvas__arrow--security" d="M0 0 L10 5 L0 10 z" />
              </marker>
            </defs>
            <g transform={`translate(${shownView.x} ${shownView.y}) scale(${shownView.scale})`}>
              {drawn.map((edge, index) => {
                const from = placed[edge.source]
                const to = placed[edge.target]
                if (!from || !to) return null
                const points = routeEdge(from, to, laneOf[index] ?? 0)
                const at = labelPoint(points)
                const security = edge.kind === 'security'
                const faded = dimmed(edge.source) || dimmed(edge.target)
                return (
                  <g
                    key={`${edge.kind}:${edge.name}:${edge.source}:${edge.target}`}
                    className={
                      'ontology-canvas__edge' +
                      (security ? ' ontology-canvas__edge--security' : '') +
                      (faded ? ' ontology-canvas__edge--dimmed' : '') +
                      (!security && selectedLink === edge.name ? ' ontology-canvas__edge--selected' : '')
                    }
                    data-edge={edge.name}
                  >
                    <path
                      className="ontology-canvas__line"
                      d={pathOf(points)}
                      markerEnd={`url(#${markerId}-arrow${security ? '-security' : ''})`}
                    />
                    {!security && (
                      // A WIDE, INVISIBLE TWIN TO CLICK, because a 1px line
                      // is a target nobody hits first time.
                      <path
                        className="ontology-canvas__hit"
                        d={pathOf(points)}
                        onPointerDown={(event) => event.stopPropagation()}
                        onClick={() =>
                          onSelect({
                            kind: 'link',
                            name: edge.name,
                            source: edge.source,
                            target: edge.target,
                            label: edge.label,
                          })
                        }
                      />
                    )}
                    {security ? (
                      // NO LABEL ON A CHAIN: in a browser it collided with the
                      // link labels on the same run. The dash and colour say
                      // "security", the node's badge says from where, and the
                      // sentence is here for whoever hovers.
                      <title>{edge.label}</title>
                    ) : (
                      <text className="ontology-canvas__edge-label" x={at.x} y={at.y - 4} textAnchor="middle">
                        {edge.label}
                      </text>
                    )}
                  </g>
                )
              })}

              {model.types.map((type) => {
                const at = placed[type.name]
                if (!at) return null
                const chain = chains ? chainByType.get(type.name) : undefined
                const actionText =
                  type.actions.length === 0 ? 'read-only' : pluralise(type.actions.length, 'action', 'actions')
                const securityText = chain
                  ? chain.kind === 'via'
                    ? `secured via ${chain.target}`
                    : `secured by ${chain.field}`
                  : null
                return (
                  <g
                    key={type.name}
                    className={
                      'ontology-canvas__node' +
                      (selectedType === type.name ? ' ontology-canvas__node--selected' : '') +
                      (dimmed(type.name) ? ' ontology-canvas__node--dimmed' : '') +
                      (moving?.name === type.name ? ' ontology-canvas__node--moving' : '')
                    }
                    transform={`translate(${at.x - NODE_WIDTH / 2} ${at.y - NODE_HEIGHT / 2})`}
                    role="button"
                    tabIndex={0}
                    aria-label={
                      `${type.label}: ${pluralise(type.fieldCount, 'field', 'fields')}, ` +
                      `${pluralise(type.linkCount, 'link', 'links')}, ${actionText}` +
                      (securityText ? `, ${securityText}` : '')
                    }
                    aria-pressed={selectedType === type.name}
                    data-type={type.name}
                    onPointerDown={(event) => onNodePointerDown(event, type.name)}
                    onClick={() => {
                      if (suppressClick.current) {
                        suppressClick.current = false
                        return
                      }
                      onSelect({ kind: 'object', name: type.name })
                    }}
                    onKeyDown={(event) => onNodeKeyDown(event, type.name)}
                  >
                    <title>{type.label}</title>
                    <rect className="ontology-canvas__box" width={NODE_WIDTH} height={NODE_HEIGHT} rx={6} />
                    <text className="ontology-canvas__name" x={12} y={22}>
                      {shorten(type.label)}
                    </text>
                    <text className="ontology-canvas__meta" x={12} y={40}>
                      {pluralise(type.fieldCount, 'field', 'fields')} · {pluralise(type.linkCount, 'link', 'links')}
                    </text>
                    <text
                      className={
                        'ontology-canvas__badge' + (type.actions.length === 0 ? ' ontology-canvas__badge--quiet' : '')
                      }
                      x={12}
                      y={56}
                    >
                      {actionText}
                      {securityText && (
                        <tspan className="ontology-canvas__badge--security" dx={8}>
                          {shorten(securityText)}
                        </tspan>
                      )}
                    </text>
                  </g>
                )
              })}
            </g>
          </svg>
          <p className="ontology-canvas__hint">
            Drag a type to place it, or focus it and use the arrow keys; it stays where you put it. Drag the background
            to pan; Ctrl or Cmd with the wheel zooms.
          </p>
        </div>
      </div>

      {areaDialog && (
        <AreaDialog
          types={model.types.map((type) => ({ name: type.name, label: type.label }))}
          areas={layout.areas}
          original={areaDialog.original}
          suggested={selectedType}
          onClose={() => setAreaDialog(null)}
          onSave={(next) => {
            persist({ positions: layout.positions, areas: next })
            setAreaDialog(null)
          }}
        />
      )}
    </div>
  )
}

/**
 * Making, renaming and changing a subject area.
 *
 * "There is no wrong way of grouping and categorizing", and people will
 * regroup constantly (14.4) -- so it is a small form, and deleting one
 * loses nothing but the grouping: the types are untouched.
 */
function AreaDialog({
  types,
  areas,
  original,
  suggested,
  onClose,
  onSave,
}: {
  types: { name: string; label: string }[]
  areas: Layout['areas']
  original: string | null
  suggested: string | null
  onClose: () => void
  onSave: (areas: Layout['areas']) => void
}) {
  const existing = areas.find((area) => area.name === original)
  const [name, setName] = useState(existing?.name ?? '')
  const [chosen, setChosen] = useState<Set<string>>(new Set(existing ? existing.types : suggested ? [suggested] : []))
  const trimmed = name.trim()
  const clash = areas.some(
    (area) => area.name !== original && area.name.toLocaleLowerCase() === trimmed.toLocaleLowerCase(),
  )
  const problem =
    trimmed === '' ? 'Give it a name.' : clash ? `You already have a subject area called ${trimmed}.` : null

  const save = () => {
    if (problem) return
    const entry = { name: trimmed, types: [...chosen].sort((a, b) => a.localeCompare(b)) }
    onSave(original === null ? [...areas, entry] : areas.map((area) => (area.name === original ? entry : area)))
  }

  return (
    <Dialog isOpen onClose={onClose} title={original === null ? 'New subject area' : `Edit ${original}`}>
      <DialogBody>
        <label className="ontology-canvas__dialog-label" htmlFor="subject-area-name">
          Name
        </label>
        <InputGroup id="subject-area-name" value={name} autoFocus onChange={(event) => setName(event.target.value)} />
        {problem && trimmed !== '' && <p className="ontology-canvas__dialog-problem">{problem}</p>}
        <fieldset className="ontology-canvas__dialog-types">
          <legend>Types in it</legend>
          {types.map((type) => (
            <Checkbox
              key={type.name}
              label={type.label}
              checked={chosen.has(type.name)}
              onChange={() =>
                setChosen((current) => {
                  const next = new Set(current)
                  if (next.has(type.name)) next.delete(type.name)
                  else next.add(type.name)
                  return next
                })
              }
            />
          ))}
        </fieldset>
      </DialogBody>
      <DialogFooter
        actions={
          <>
            {original !== null && (
              <Button intent="danger" minimal onClick={() => onSave(areas.filter((area) => area.name !== original))}>
                Delete subject area
              </Button>
            )}
            <Button onClick={onClose}>Cancel</Button>
            <Button intent="primary" disabled={problem !== null} onClick={save}>
              Save
            </Button>
          </>
        }
      />
    </Dialog>
  )
}
