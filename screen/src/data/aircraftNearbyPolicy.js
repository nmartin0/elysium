/** Decide whether a loaded aircraft participates in a proximity query. */
export function aircraftIncludedInNearby({
  isTracked = false,
  billboardShown = false,
  includeHidden = false,
} = {}) {
  return Boolean(includeHidden || isTracked || billboardShown);
}
