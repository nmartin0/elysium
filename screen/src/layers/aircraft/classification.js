/**
 * Aircraft classification, as the fork keeps it: nothing is military.
 *
 * Fork: the military layer and its identity list were removed. The civil
 * flights layer still asks this registry whether an aircraft is military
 * (to tint it, or to suppress a duplicate), so the registry stays as an object
 * with the same methods that always answers "no" and never fetches anything.
 */
export function createMilitaryRegistry() {
  return {
    configureSource: () => () => {},
    dispose() {},
    isMilitaryLayerActive: () => false,
    setMilitaryLayerActive() {},
    onMilitaryLayerActiveChange: () => () => {},
    registerMilitaryIcaos() {},
    isMilitaryIcao: () => false,
    refreshMilitaryRegistryIfStale: async () => {},
  };
}
