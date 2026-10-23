/**
 * THE APPROVALS MODULE AS A MODULE (BLOCKING.md item 3, step 3): the
 * entry of its own bundle, built apart from Elysium's page by
 * vite.config.ts in this folder and loaded by the shell when the Inbox
 * first shows one of its tabs. Elysium's page no longer imports it.
 *
 * NO PAGES OF ITS OWN: four tabs of the Inbox, by the ids its
 * module.json's `into` declares, drawn by the Inbox with the slot's
 * context as props. ONE BUNDLE FOR THE FOUR, where each used to be a
 * chunk of Elysium's page loaded with its own tab: the first of them
 * opened brings the other three, which share its client code and
 * WriteDetail.
 *
 * THEIR ICONS, in module.json, which cannot say why (moved here from the
 * Inbox, step 1.5b): `inbox` for Approvals; `learning` for Enrichment --
 * rules a model wrote for an enriched field, waiting on a person (R41),
 * so what the rules are is something a model learnt; `predictive-
 * analysis` for Predictions, a predicted field measured and waiting
 * (R48); `scatter-plot` for Unusual -- one point away from the rest, a
 * value unusual for its kind (R51); not the eye, which is watching.
 */
import type { ModuleActivation } from '@shell/core/moduleLoader'
import ApprovalsPanel from './ApprovalsPanel'
import EnrichmentReview from './EnrichmentReview'
import PredictionReview from './PredictionReview'
import UnusualReview from './UnusualReview'
import './approvals.css'

/** Its contributions by the ids module.json declares. */
export function activate(): ModuleActivation {
  return {
    pages: {},
    contributions: {
      approvals: ApprovalsPanel,
      enrichment: EnrichmentReview,
      predictions: PredictionReview,
      unusual: UnusualReview,
    },
  }
}
