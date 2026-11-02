/**
 * What is left of the first-person aircraft view (Cockpit).
 *
 * Fork: the Cockpit was removed. The shell still reads its state through the
 * coordinator's interface (`cockpitView`, `getCockpitState`, ...), so this
 * object answers that interface with "no Cockpit" and does nothing else.
 */
export function createInertCockpit() {
  const unavailable = (action) => ({
    ok: false,
    action,
    error: 'Cockpit is not available',
  });
  return {
    cockpitView: null,
    _cockpitDisplayPortal: null,
    _cockpitDisplayPortalActive: false,
    _displayPortalScrollRestoreOwner: null,
    _standardDisplayScrollTop: 0,
    getCockpitState: () => ({
      active: false,
      entryAllowed: false,
      visionMode: 'optical',
      subject: null,
      navigation: null,
    }),
    controlCockpit: async (action) => unavailable(String(action || 'status')),
    _retargetCockpitEntryLayer: () => unavailable('enter'),
    _initCockpitDisplayPortal() {},
    _setCockpitDisplayPortalActive() {},
    stop() {},
    destroy() {},
  };
}
