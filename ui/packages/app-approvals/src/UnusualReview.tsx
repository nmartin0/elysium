/**
 * Values unusual for their kind, for someone who may edit the type to
 * decide about (R51; the owner, 19 October).
 *
 * TWO DECISIONS, NEITHER A CHANGE TO THE DATA:
 *   - "Expected": the value is right. The marker goes, for everyone who
 *     sees it, until the value changes -- a person who looked at 4,980
 *     did not look at 49,800.
 *   - "Worth a look": kept, and the marker stays, saying someone has
 *     looked and kept it. Fixing the value is an edit, made as any is.
 *
 * THE PRECEDENT: Foundry's data health checks notify the people
 * subscribed to a dataset, who decide what a failure means; Atlan with
 * Soda puts the result on the asset for its owner; Stripe Radar shows
 * each reviewer why a payment was flagged, beside the decision. So: the
 * reason first, then the record, then the two buttons.
 *
 * FURTHEST FIRST, AND SAYS SO WHEN SHORT: at most 50 per type are kept,
 * so "the 50 furthest of 212" rather than a list that looks complete.
 */

import { Button } from '@blueprintjs/core'
import {
  decideUnusual,
  getErrorMessage,
  getUnusualReview,
  handleIfSessionExpired,
  type UnusualReview as Review,
  type UnusualReviewItem,
} from '@elysium/shell-api/api'
import EmptyState from '@elysium/shell-api/components/EmptyState'
import ErrorState from '@elysium/shell-api/components/ErrorState'
import LoadingState from '@elysium/shell-api/components/LoadingState'
import StatusTag from '@elysium/shell-api/components/StatusTag'
import { useFetchOnce } from '@elysium/shell-api/useFetchOnce'
import { useState } from 'react'
import { Link } from 'react-router-dom'

const keyOf = (item: UnusualReviewItem) => `${item.object_type}|${item.record_id}|${item.field}`

const DECIDED: Record<'expected' | 'worth_a_look', string> = {
  expected: 'expected',
  worth_a_look: 'worth a look',
}

function ItemCard({
  item,
  onDecided,
  onSessionExpired,
}: {
  item: UnusualReviewItem
  onDecided: (next: UnusualReviewItem) => void
  onSessionExpired: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function decide(decision: 'expected' | 'worth_a_look') {
    setBusy(true)
    setError(null)
    try {
      onDecided(await decideUnusual(item, decision))
    } catch (err: unknown) {
      if (handleIfSessionExpired(err, onSessionExpired)) return
      setError(getErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <article className="enrichment-recipe" aria-label={`${item.object_type} ${item.record_id} ${item.field_label}`}>
      <header className="enrichment-recipe__head">
        <h3>
          <Link to={`/objects/${encodeURIComponent(item.object_type)}/${encodeURIComponent(item.record_id)}`}>
            {item.object_type} {item.record_id}
          </Link>{' '}
          · {item.field_label}
        </h3>
        {item.decision && (
          <StatusTag state={item.decision === 'expected' ? 'neutral' : 'active'}>{DECIDED[item.decision]}</StatusTag>
        )}
      </header>
      <p className="enrichment-recipe__question">{item.reason}</p>
      {item.decided_by && (
        <p className="enrichment-recipe__provenance">
          Marked {item.decision ? DECIDED[item.decision] : ''} by {item.decided_by}.
        </p>
      )}
      {error && <ErrorState>{error}</ErrorState>}
      <div className="enrichment-recipe__actions">
        {item.decision !== 'expected' && (
          <Button intent="primary" loading={busy} onClick={() => void decide('expected')}>
            Expected
          </Button>
        )}
        {item.decision !== 'worth_a_look' && (
          <Button loading={busy} onClick={() => void decide('worth_a_look')}>
            Worth a look
          </Button>
        )}
        <span className="enrichment-recipe__after">
          {item.decision === 'expected'
            ? 'Its marker is gone for everyone until the value changes.'
            : 'Expected clears its marker for everyone until the value changes. Nothing in the data is changed.'}
        </span>
      </div>
    </article>
  )
}

export default function UnusualReview({ onSessionExpired }: { onSessionExpired: () => void }) {
  const { data, error } = useFetchOnce<Review>(getUnusualReview, onSessionExpired)
  const [decided, setDecided] = useState<Record<string, UnusualReviewItem>>({})

  if (error) return <ErrorState>{error}</ErrorState>
  if (data === null) return <LoadingState />

  const items = data.items.map((item) => decided[keyOf(item)] ?? item)
  const waiting = items.filter((item) => item.decision === null)
  const rest = items.filter((item) => item.decision !== null)
  const card = (item: UnusualReviewItem) => (
    <ItemCard
      key={keyOf(item)}
      item={item}
      onSessionExpired={onSessionExpired}
      onDecided={(next) => setDecided((current) => ({ ...current, [keyOf(next)]: next }))}
    />
  )

  if (items.length === 0) {
    return (
      <EmptyState
        icon="scatter-plot"
        title="Nothing unusual to review"
        reason="Values appear here when a sync finds a number far from the usual for its kind, in types you may edit, with every field involved readable, in your own compartment."
      />
    )
  }
  return (
    <div className="enrichment-review">
      {data.found > data.items.length && (
        <p className="enrichment-review__none">
          The {data.items.length} furthest from their kind's usual, of {data.found} found.
        </p>
      )}
      {waiting.length > 0 ? (
        waiting.map(card)
      ) : (
        <p className="enrichment-review__none">Nothing is waiting for a decision.</p>
      )}
      {rest.length > 0 && (
        <section className="enrichment-review__decided">
          <h3>Decided</h3>
          {rest.map(card)}
        </section>
      )}
    </div>
  )
}
