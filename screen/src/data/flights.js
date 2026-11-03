import { defaultSurface } from './surfaceServices.js';
import { createApplicationFlights } from '../app/layers/flights.js';

import { createFlightSource } from '../sources/live/standalone.js';
import { createMilitaryRegistry } from '../layers/aircraft/classification.js';

const flightsLayer = createApplicationFlights({
  surface: defaultSurface,
  source: createFlightSource(),
  militaryRegistry: createMilitaryRegistry(),
});
export const _floorGroundedDisplayPositionForTest =
  flightsLayer.testing._floorGroundedDisplayPositionForTest;
export const _clearDisplayFloorStateForTest =
  flightsLayer.testing._clearDisplayFloorStateForTest;
export const _setTrackedFlightRefreshStateForTest =
  flightsLayer.testing._setTrackedFlightRefreshStateForTest;
export const _setFlightTrackingRefreshOutcomeForTest =
  flightsLayer.testing._setFlightTrackingRefreshOutcomeForTest;
export const _addFlightTrackingCandidateForTest =
  flightsLayer.testing._addFlightTrackingCandidateForTest;
export const _militaryLayerSuppressesForTest =
  flightsLayer.testing._militaryLayerSuppressesForTest;
export const _armFlightTrackingRestoreForTest =
  flightsLayer.testing._armFlightTrackingRestoreForTest;
export const _pendingFlightTrackingRestoreForTest =
  flightsLayer.testing._pendingFlightTrackingRestoreForTest;
export const _applyPendingFlightTrackingRestoreForTest =
  flightsLayer.testing._applyPendingFlightTrackingRestoreForTest;
export const mapAnalystRecord = flightsLayer.mapAnalystRecord;
export default flightsLayer;
