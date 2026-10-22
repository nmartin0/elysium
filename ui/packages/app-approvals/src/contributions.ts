/**
 * WHAT THE APPROVALS MODULE PUTS IN OTHER MODULES' SLOTS (BLOCKING.md item
 * 3, step 1.5b), by the ids its module.json's `into` declares: four tabs
 * of the Inbox. Each loads when its tab is first opened, as when the
 * Inbox imported them itself.
 *
 * THEIR ICONS, in module.json, which cannot say why (moved here from the
 * Inbox, step 1.5b): `inbox` for Approvals; `learning` for Enrichment --
 * rules a model wrote for an enriched field, waiting on a person (R41),
 * so what the rules are is something a model learnt; `predictive-
 * analysis` for Predictions, a predicted field measured and waiting
 * (R48); `scatter-plot` for Unusual -- one point away from the rest, a
 * value unusual for its kind (R51); not the eye, which is watching.
 */
import { lazy } from 'react'

export const contributions = {
  approvals: lazy(() => import('./ApprovalsPanel')),
  enrichment: lazy(() => import('./EnrichmentReview')),
  predictions: lazy(() => import('./PredictionReview')),
  unusual: lazy(() => import('./UnusualReview')),
}
