import { t } from '../i18n/index.js';
import { shouldExpandGlobalContextPanel } from '../rightRailPolicy.js';

export function _initGlobalContextPanel() {
  const contextTabs = [
    this._globalContextFlightsBtn,
    this._globalContextMissionsBtn,
  ].filter(Boolean);
  contextTabs.forEach((tab, index) =>
    this.listen(tab, 'keydown', (event) => {
      let nextIndex = null;
      if (event.key === 'ArrowRight')
        nextIndex = (index + 1) % contextTabs.length;
      else if (event.key === 'ArrowLeft')
        nextIndex = (index - 1 + contextTabs.length) % contextTabs.length;
      else if (event.key === 'Home') nextIndex = 0;
      else if (event.key === 'End') nextIndex = contextTabs.length - 1;
      if (nextIndex === null) return;
      event.preventDefault();
      contextTabs[nextIndex].focus({ preventScroll: true });
      contextTabs[nextIndex].click();
    }),
  );
  this.listen(this._globalContextFlightsBtn, 'click', () => {
    if (
      this.destroyed ||
      this._contextModeChanging ||
      this._clearSelectedLayersPromise
    )
      return;
    const nextMode = this._contextMode === 'flights' ? null : 'flights';
    this._claimContextVisualAuthority();
    void this._runUserFacingContextAction(
      (notificationToken) =>
        this._selectContextMode(nextMode, { notificationToken }),
      t('Contacts could not complete the requested transition; try again'),
    ).then((succeeded) => {
      if (
        !this.destroyed &&
        nextMode &&
        shouldExpandGlobalContextPanel({
          action: 'contacts',
          explicitUserAction: true,
          succeeded: succeeded === true,
        })
      )
        this.actions.setPanelCollapsed('global-context-panel', false, {
          explicit: true,
        });
    });
  });
  this.listen(this._globalContextMissionsBtn, 'click', () => {
    if (
      this.destroyed ||
      this._contextModeChanging ||
      this._clearSelectedLayersPromise
    )
      return;
    const nextMode =
      this._contextMode === 'space-missions' ? null : 'space-missions';
    this._claimContextVisualAuthority();
    void this._runUserFacingContextAction(
      (notificationToken) =>
        this._selectContextMode(nextMode, { notificationToken }),
      t(
        'Space Missions could not complete the requested transition; try again',
      ),
    ).then((succeeded) => {
      if (
        !this.destroyed &&
        nextMode &&
        shouldExpandGlobalContextPanel({
          action: 'space-missions',
          explicitUserAction: true,
          succeeded: succeeded === true,
        })
      )
        this.actions.setPanelCollapsed('global-context-panel', false, {
          explicit: true,
        });
    });
  });
}
