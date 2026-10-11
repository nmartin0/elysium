/**
 * Frozen sets -- membership fixed at an instant (DEV_UI 11.3).
 *
 * THE OTHER KIND OF SAVED SET. A saved VIEW is live: its query, re-run,
 * so membership is whatever matches today. This keeps WHO was in the
 * set when it was frozen. DEV_UI 11.3 names both failure modes from
 * HubSpot's FAQ -- "why are contacts dropping off my list?" (it is
 * live) and "why isn't my list updating?" (it is frozen) -- which is
 * why the two live side by side and say which they are.
 *
 * KEYS, AND VALUES READ LIVE. Foundry's static object sets are "saved
 * as a list of primary keys"; opening one here is an ordinary search
 * narrowed to them, so the table, charts, facets, graph and export all
 * work on it without knowing it is frozen.
 *
 * WHAT GETS FROZEN: the selection if anything is selected, otherwise
 * everything the current search matches -- resolved by the SERVER, as
 * "select all matching" is, so the membership is exactly what this
 * person could see at the instant they froze it.
 */

import { Button, InputGroup, Menu, MenuDivider, MenuItem, Popover } from '@blueprintjs/core'
import {
  deleteFrozenSet,
  freezeSet,
  getErrorMessage,
  getFrozenSets,
  handleIfSessionExpired,
  type FrozenSet,
} from '@elysium/shell-api/api'
import { formatTimestamp } from '@elysium/shell-api/format'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

/** Where a frozen set opens: its type, narrowed to it, and nothing
 *  else -- a frozen set is a different subject from whatever search
 *  was on screen, so the old text and filters do not follow it. */
export function urlForFrozen(set: Pick<FrozenSet, 'object_type' | 'set_id'>): string {
  const params = new URLSearchParams({ type: set.object_type, frozen: set.set_id })
  return `/browse?${params.toString()}`
}

export default function FrozenSets({
  objectType,
  queryText,
  conditions,
  selectedIds,
  activeSetId,
  onSessionExpired,
}: {
  objectType: string | null
  queryText: string
  /** The live set's conditions, in the SERVER's shape. */
  conditions: unknown[]
  /** A hand-picked selection, if any. Frozen instead of the filter. */
  selectedIds: string[]
  /** The frozen set on screen, if one is -- freezing a frozen set
   *  narrows within it, so its id goes along. */
  activeSetId: string
  onSessionExpired: () => void
}) {
  const navigate = useNavigate()
  const [sets, setSets] = useState<FrozenSet[]>([])
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // THE SESSION CALLBACK THROUGH A REF, for the reason SavedViews
  // records: a parent declaring it inline gives it a new identity
  // every render, and a `load` depending on it refetched each time.
  const latestSessionExpired = useRef(onSessionExpired)
  useEffect(() => {
    latestSessionExpired.current = onSessionExpired
  })

  const load = useCallback(async () => {
    try {
      setSets(await getFrozenSets())
    } catch (caught: unknown) {
      if (handleIfSessionExpired(caught, latestSessionExpired.current)) return
      setSets([])
    }
  }, [])

  useEffect(() => {
    // THE SAME FALSE POSITIVE SavedViews records and exempts, with its
    // proof: every setState in `load` follows an await, and the rule
    // cannot see through a useCallback to it.
    // eslint-disable-next-line react/set-state-in-effect
    void load()
  }, [load])

  async function freeze() {
    const trimmed = name.trim()
    if (trimmed === '' || !objectType) return
    setBusy(true)
    setProblem(null)
    try {
      const frozen = await freezeSet(
        selectedIds.length > 0
          ? { name: trimmed, object_type: objectType, ids: selectedIds }
          : {
              name: trimmed,
              object_type: objectType,
              q: queryText,
              conditions,
              // INSIDE A FROZEN SET, "everything matching" is matching
              // within it; without this the server ran the filter over
              // the whole type.
              ...(activeSetId ? { frozen_set: activeSetId } : {}),
            },
      )
      setOpen(false)
      setName('')
      await load()
      navigate(urlForFrozen(frozen))
    } catch (caught: unknown) {
      if (handleIfSessionExpired(caught, latestSessionExpired.current)) return
      // THE SERVER'S WORDS, which say what to do: "404 objects match,
      // and at most 1000 can be frozen at once. Narrow the filter."
      setProblem(getErrorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  async function forget(setId: string) {
    try {
      await deleteFrozenSet(setId)
      await load()
      if (setId === activeSetId) navigate(`/browse?type=${encodeURIComponent(objectType ?? '')}`)
    } catch (caught: unknown) {
      handleIfSessionExpired(caught, latestSessionExpired.current)
    }
  }

  // SAYS WHAT WILL BE FROZEN before it is, because "freeze" alone does
  // not say whether it means the three rows ticked or the 404 matching.
  const what = selectedIds.length > 0 ? `Freeze ${selectedIds.length} selected` : 'Freeze everything matching'

  return (
    <Popover
      isOpen={open}
      onInteraction={(next) => {
        setOpen(next)
        if (next) setProblem(null)
      }}
      content={
        <Menu className="frozen-sets__menu">
          <div className="frozen-sets__freeze">
            <InputGroup
              small
              placeholder="Name this set"
              aria-label="Name for the frozen set"
              value={name}
              onChange={(event) => setName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void freeze()
              }}
            />
            <Button
              small
              icon="snowflake"
              disabled={!objectType || name.trim() === ''}
              loading={busy}
              onClick={() => void freeze()}
            >
              {what}
            </Button>
          </div>
          {problem !== null && <p className="frozen-sets__problem">{problem}</p>}
          {sets.length > 0 && <MenuDivider title="Frozen" />}
          {sets.map((set) => (
            <MenuItem
              key={set.set_id}
              active={set.set_id === activeSetId}
              text={set.name}
              label={`${set.object_type} · ${set.size.toLocaleString()} · ${formatTimestamp(set.frozen_at)}`}
              onClick={() => {
                setOpen(false)
                navigate(urlForFrozen(set))
              }}
              labelElement={
                <Button
                  minimal
                  small
                  icon="trash"
                  aria-label={`Delete ${set.name}`}
                  onClick={(event) => {
                    // INSIDE A MenuItem, whose own click would open the
                    // set first and then delete it from under itself.
                    event.stopPropagation()
                    void forget(set.set_id)
                  }}
                />
              }
            />
          ))}
        </Menu>
      }
    >
      <Button icon="snowflake" small>
        Frozen sets
      </Button>
    </Popover>
  )
}
