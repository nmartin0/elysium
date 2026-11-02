/**
 * Inert stand-ins for the layers the fork removed.
 *
 * The application shell still reaches a few layers by role (`trafficLayer`,
 * `cctvLayer`, ...) through `catalogControlServices`, and calls a handful of
 * hooks on them. A stub answers those hooks and does nothing else: it is not a
 * member of `catalog.layers`, so it registers no source, draws nothing, and
 * never appears in a layer list, panel, search result or share link.
 */
const noop = () => {};

/** Create the inert object for one removed layer id. */
export function createLayerStub(id) {
  return Object.freeze({
    id,
    inert: true,
    enabled: false,
    isEnabled: () => false,
    beginWorldJump: noop,
    endWorldJump: noop,
    stopTracking: noop,
    cancelPendingTrackingRestore: noop,
    releaseCameraOwnership: noop,
    attachNavigation: noop,
    getTrackedInfo: () => null,
    getTrackedSubject: () => null,
    getContextSnapshot: () => null,
    getUIState: () => ({}),
  });
}

/** Layer ids the control surface still asks the catalog for by role. */
export const STUBBED_LAYER_IDS = Object.freeze([
  'military',
  'military-awareness',
  'military-installations',
  'traffic',
  'cctv',
  'street-level',
  'radio',
  'local-adsb',
]);

export function createLayerStubs() {
  return STUBBED_LAYER_IDS.map(createLayerStub);
}
