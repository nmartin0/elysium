/**
 * Rules a model wrote for an enriched field, for a person to approve
 * (R41; decided 15 October: "approve first").
 *
 * WHAT THE APPROVER NEEDS, AND IN THIS ORDER: the question the field
 * answers; the rules in plain words, because the rules ARE what is being
 * approved; then how they did on rows they were NOT written from --
 * compiled from half the sample and judged on the other half, so the
 * number is about rules meeting new rows, not rules meeting their own
 * examples. Last, what produced them.
 *
 * NOTHING HAPPENS ON APPROVE BUT THE DECISION. The next sync fills the
 * field; the panel says so, rather than implying the values changed.
 *
 * A RECIPE FOR A CHANGED QUESTION cannot be approved -- the server
 * refuses it -- so the buttons are not offered, and the panel says why.
 */

import { Button } from '@blueprintjs/core'
import {
  decideEnrichmentRecipe,
  type EnrichmentRecipe,
  getEnrichmentRecipes,
  getErrorMessage,
  handleIfSessionExpired,
} from '@elysium/shell-api/api'
import EmptyState from '@elysium/shell-api/components/EmptyState'
import ErrorState from '@elysium/shell-api/components/ErrorState'
import LoadingState from '@elysium/shell-api/components/LoadingState'
import Notice from '@elysium/shell-api/components/Notice'
import StatusTag, { type TagState } from '@elysium/shell-api/components/StatusTag'
import { formatTimestamp } from '@elysium/shell-api/format'
import { useFetchOnce } from '@elysium/shell-api/useFetchOnce'
import { useState } from 'react'

const STATUS_TAG: Record<EnrichmentRecipe['status'], TagState> = {
  proposed: 'pending',
  approved: 'granted',
  rejected: 'refused',
  superseded: 'neutral',
}

function percent(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : `${Math.round(value * 100)}%`
}

/** How the rules did on rows they were not written from, in a sentence. */
export function heldOutSentence(recipe: EnrichmentRecipe): string {
  const held = recipe.evaluation.held_out
  if (!held || held.rows === 0) return 'There were no held-out rows to judge these rules on.'
  return (
    `On ${held.rows} sampled rows these rules were not written from, they gave an answer for ` +
    `${percent(held.coverage)}, and agreed with the model's own answer on ${percent(held.agreement)} of those.`
  )
}

function RecipeCard({
  recipe,
  onDecided,
  onSessionExpired,
}: {
  recipe: EnrichmentRecipe
  onDecided: (next: EnrichmentRecipe) => void
  onSessionExpired: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const decidable = recipe.status === 'proposed' && recipe.current

  async function decide(approve: boolean) {
    setBusy(true)
    setError(null)
    try {
      onDecided(await decideEnrichmentRecipe(recipe.recipe_id, approve))
    } catch (err: unknown) {
      if (handleIfSessionExpired(err, onSessionExpired)) return
      setError(getErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <article className="enrichment-recipe" aria-label={`${recipe.object_type} ${recipe.field_label}`}>
      <header className="enrichment-recipe__head">
        <h3>
          {recipe.object_type} · {recipe.field_label}
        </h3>
        <StatusTag state={STATUS_TAG[recipe.status]}>{recipe.status}</StatusTag>
      </header>
      <p className="enrichment-recipe__question">{recipe.instruction}</p>
      <p className="enrichment-recipe__meta">
        Reads {recipe.inputs.join(', ')}; answers one of {recipe.choices.join(', ')}. A row no rule matches is left
        empty.
      </p>

      {(recipe.rule_sets?.length ?? 0) > 1 ? (
        // SEVERAL RULE SETS THAT VOTE (17 October): each answering set
        // adds its weight to its value; the heaviest wins, a tie is
        // left empty. Every set is shown -- the approver reads them all.
        <>
          <h4>{recipe.rule_sets!.length} rule sets that vote</h4>
          <p className="enrichment-recipe__meta">
            Within each set the first match wins. Each set that answers adds its weight to its answer; the answer with
            the most weight is used, and a tie is left empty. A weight comes from how often the set agreed with the
            model on its examples.
          </p>
          {recipe.rule_sets!.map((ruleSet, setIndex) => (
            <section key={setIndex} className="enrichment-recipe__set">
              <h5>
                Set {setIndex + 1}, weight {ruleSet.weight}
              </h5>
              <ol className="enrichment-recipe__rules">
                {ruleSet.rules.map((rule, index) => (
                  <li key={index}>{rule}</li>
                ))}
              </ol>
            </section>
          ))}
        </>
      ) : (
        <>
          <h4>The rules, first match wins</h4>
          <ol className="enrichment-recipe__rules">
            {recipe.rules.map((rule, index) => (
              <li key={index}>{rule}</li>
            ))}
          </ol>
        </>
      )}

      <p className="enrichment-recipe__score">{heldOutSentence(recipe)}</p>
      {recipe.evaluation.enough_to_judge === false && (
        <Notice state="neutral">Too few rows to judge by. Compiling again with a larger sample would say more.</Notice>
      )}
      <p className="enrichment-recipe__provenance">
        Written by {recipe.provenance.model ?? 'the model'} from a sample of {recipe.provenance.sample ?? '?'}
        {recipe.provenance.compartment ? ` in ${recipe.provenance.compartment}` : ''}, proposed{' '}
        {formatTimestamp(recipe.proposed_at)}
        {recipe.decided_by && recipe.decided_at
          ? `; ${recipe.status} by ${recipe.decided_by} ${formatTimestamp(recipe.decided_at)}`
          : ''}
        .
      </p>

      {recipe.status === 'proposed' && !recipe.current && (
        <Notice state="neutral">
          The field's question has changed since these rules were written, so they can no longer be approved. Compile it
          again.
        </Notice>
      )}
      {error && <ErrorState>{error}</ErrorState>}
      {decidable && (
        <div className="enrichment-recipe__actions">
          <Button intent="primary" loading={busy} onClick={() => void decide(true)}>
            Approve
          </Button>
          <Button loading={busy} onClick={() => void decide(false)}>
            Reject
          </Button>
          <span className="enrichment-recipe__after">
            Approving fills {recipe.field_label} at the next sync; nothing changes before then.
          </span>
        </div>
      )}
    </article>
  )
}

export default function EnrichmentReview({ onSessionExpired }: { onSessionExpired: () => void }) {
  const { data, error } = useFetchOnce<EnrichmentRecipe[]>(getEnrichmentRecipes, onSessionExpired)
  const [decided, setDecided] = useState<Record<string, EnrichmentRecipe>>({})

  if (error) return <ErrorState>{error}</ErrorState>
  if (data === null) return <LoadingState />

  const recipes = data.map((recipe) => decided[recipe.recipe_id] ?? recipe)
  const waiting = recipes.filter((recipe) => recipe.status === 'proposed' && recipe.current)
  const rest = recipes.filter((recipe) => !(recipe.status === 'proposed' && recipe.current))
  const card = (recipe: EnrichmentRecipe) => (
    <RecipeCard
      key={recipe.recipe_id}
      recipe={recipe}
      onSessionExpired={onSessionExpired}
      onDecided={(next) => setDecided((current) => ({ ...current, [next.recipe_id]: next }))}
    />
  )

  if (recipes.length === 0) {
    return (
      <EmptyState
        icon="learning"
        title="No enrichment rules to review"
        reason="Rules appear here when someone compiles an enriched field, and only for fields you may read, in your own compartment."
      />
    )
  }
  return (
    <div className="enrichment-review">
      {waiting.length > 0 ? (
        waiting.map(card)
      ) : (
        <p className="enrichment-review__none">Nothing is waiting for a decision.</p>
      )}
      {rest.length > 0 && (
        <section className="enrichment-review__decided">
          <h3>Decided, or for a question that has changed</h3>
          {rest.map(card)}
        </section>
      )}
    </div>
  )
}
