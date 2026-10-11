/**
 * Compare the set on screen with a saved view or a frozen set.
 *
 * FOUNDRY'S OBJECT SET SERVICE is the precedent: two sets combine by
 * union, intersect and subtract, and each result is a new set. This
 * shows the three regions at once -- only here, both, only there --
 * which is the overlap view Amplitude's cohort comparison and
 * HubSpot's list overlap both give.
 *
 * COUNTS FIRST, MEMBERS ON REQUEST. Keeping a region makes it a frozen
 * set and opens it, so every view of a set -- table, charts, facets,
 * graph, export -- works on the answer without knowing it came from a
 * comparison.
 */

import { Button, HTMLSelect, Popover } from '@blueprintjs/core'
import {
  combineSets,
  compareSets,
  getErrorMessage,
  getFrozenSets,
  getSavedViews,
  handleIfSessionExpired,
  type SetComparison,
  type SetReference,
  type SetRegion,
} from '@elysium/shell-api/api'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { urlForFrozen } from './FrozenSets'

interface Candidate {
  key: string
  name: string
  kind: 'Saved view' | 'Frozen set'
  reference: SetReference
}

export default function CompareSets({
  objectType,
  queryText,
  conditions,
  activeSetId,
  onSessionExpired,
}: {
  objectType: string | null
  queryText: string
  /** The set on screen's conditions, in the SERVER's shape. */
  conditions: unknown[]
  /** The frozen set on screen, if one is; the conditions narrow it. */
  activeSetId: string
  onSessionExpired: () => void
}) {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [candidates, setCandidates] = useState<Candidate[]>([])
  const [chosen, setChosen] = useState('')
  const [result, setResult] = useState<SetComparison | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // ONLY WHAT IS SET. An empty key and a missing one mean the same to
  // the server, but a reference carrying `frozen_set: ""` reads as a
  // claim about a set when there is none.
  const here: SetReference = {
    ...(queryText ? { q: queryText } : {}),
    ...(conditions.length > 0 ? { conditions } : {}),
    ...(activeSetId ? { frozen_set: activeSetId } : {}),
  }
  const other = candidates.find((candidate) => candidate.key === chosen) ?? null

  async function loadCandidates() {
    try {
      const [views, sets] = await Promise.all([getSavedViews(), getFrozenSets()])
      // THE SAME TYPE ONLY. Ids are unique within a type, so comparing
      // Customers with Transactions would match ids that merely collide.
      setCandidates([
        ...views
          .filter((view) => view.object_type === objectType)
          .map((view) => ({
            key: `view:${view.view_id}`,
            name: view.name,
            kind: 'Saved view' as const,
            reference: { saved_view: view.view_id },
          })),
        ...sets
          .filter((set) => set.object_type === objectType && set.set_id !== activeSetId)
          .map((set) => ({
            key: `frozen:${set.set_id}`,
            name: set.name,
            kind: 'Frozen set' as const,
            reference: { frozen_set: set.set_id },
          })),
      ])
    } catch (caught: unknown) {
      if (handleIfSessionExpired(caught, onSessionExpired)) return
      setCandidates([])
    }
  }

  async function compareWith(key: string) {
    setChosen(key)
    setResult(null)
    setProblem(null)
    const picked = candidates.find((candidate) => candidate.key === key)
    if (!picked || !objectType) return
    // NO `finally`: the busy flag clears in the same update as the
    // answer, so nothing renders after the counts have.
    setBusy(true)
    try {
      const counts = await compareSets(objectType, here, picked.reference)
      setBusy(false)
      setResult(counts)
    } catch (caught: unknown) {
      setBusy(false)
      if (handleIfSessionExpired(caught, onSessionExpired)) return
      // THE SERVER'S WORDS: "'Escalations' filters on fields you can no
      // longer read (region), so it cannot be compared."
      setProblem(getErrorMessage(caught))
    }
  }

  async function keep(region: SetRegion, name: string) {
    if (!other || !objectType) return
    setBusy(true)
    setProblem(null)
    try {
      const kept = await combineSets(objectType, here, other.reference, region, name)
      setOpen(false)
      setResult(null)
      setChosen('')
      navigate(urlForFrozen(kept))
    } catch (caught: unknown) {
      if (handleIfSessionExpired(caught, onSessionExpired)) return
      setProblem(getErrorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  const regions: Array<{ region: SetRegion; label: string; count: number; name: string }> =
    result && other
      ? [
          {
            region: 'left_only',
            label: 'Only in this set',
            count: result.left_only,
            name: `This set, not in ${other.name}`,
          },
          { region: 'both', label: 'In both', count: result.both, name: `This set and ${other.name}` },
          {
            region: 'right_only',
            label: `Only in ${other.name}`,
            count: result.right_only,
            name: `${other.name}, not in this set`,
          },
          {
            region: 'either',
            label: 'In either',
            count: result.left_only + result.both + result.right_only,
            name: `This set or ${other.name}`,
          },
        ]
      : []

  return (
    <Popover
      isOpen={open}
      onInteraction={(next) => {
        setOpen(next)
        if (next) {
          setProblem(null)
          void loadCandidates()
        }
      }}
      content={
        <div className="compare-sets">
          <label className="compare-sets__pick">
            Compare this set with
            <HTMLSelect
              value={chosen}
              onChange={(event) => void compareWith(event.target.value)}
              aria-label="Set to compare with"
            >
              <option value="">
                {candidates.length === 0 ? 'No saved views or frozen sets of this type' : 'Choose…'}
              </option>
              {candidates.map((candidate) => (
                <option key={candidate.key} value={candidate.key}>
                  {`${candidate.name} (${candidate.kind.toLowerCase()})`}
                </option>
              ))}
            </HTMLSelect>
          </label>
          {problem !== null && <p className="compare-sets__problem">{problem}</p>}
          {result?.scan_truncated && (
            // SAID, AND KEEPING DISABLED: a part computed from half a
            // set is not the part, and the server refuses to keep it.
            <p className="compare-sets__problem">
              One of these sets is larger than a search reads, so these counts are of what was read. Narrow it to keep a
              part.
            </p>
          )}
          {regions.length > 0 && (
            <table className="compare-sets__regions">
              <tbody>
                {regions.map(({ region, label, count, name }) => (
                  <tr key={region}>
                    <th scope="row">{label}</th>
                    <td className="compare-sets__count">{count.toLocaleString()}</td>
                    <td>
                      <Button
                        small
                        minimal
                        icon="snowflake"
                        disabled={busy || count === 0 || result?.scan_truncated}
                        aria-label={`Keep ${label.toLowerCase()} as a frozen set`}
                        onClick={() => void keep(region, name)}
                      >
                        Keep
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      }
    >
      <Button icon="intersection" small disabled={!objectType}>
        Compare
      </Button>
    </Popover>
  )
}
