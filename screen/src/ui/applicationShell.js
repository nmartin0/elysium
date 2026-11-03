import { resolveImageryHost } from '../layers/weather/imageryHost.js';
import { ShellFacade } from './shellFacade.js';
import { LayerBindings } from './layerBindings.js';
import { PanelChrome } from './panelChrome.js';
import { initMobileShell } from './mobileShell.js';
import { VisualSettings } from './visualSettings.js';
import { NavigationController } from './navigationController.js';
import { ShareRestoration } from './shareRestoration.js';
import { DisplayBindings } from './displayBindings.js';
import { createStateChannel } from '../app/stateChannel.js';
import { setSplitFlapText } from '../splitFlap.js';
import { UiLifetime } from './uiLifetime.js';
import { RecordingControls } from './recordingControls.js';
import { readShellElements } from './shellElements.js';
import { ContextControls } from './context.js';
import { LocationNavigation } from './locationNavigation.js';
import { bindClearLayersControl } from './layers.js';
import { bindCameraOrientationControls } from './cameraOrientationControls.js';
import { createMapSourceControls } from './mapSource.js';
import { STYLES } from './effects.js';
import { isHudLayout } from '../hudLayouts.js';
import {
  getCyberSonarControlState,
  setCyberSonarControls,
} from './cyberSonarControls.js';

import * as Cesium from 'cesium';

import { ShellFeedback } from './shellFeedback.js';
import {
  applyShareFollowOffset,
  readShareFollowSubject,
} from './shareFollow.js';

import {
  describeUnsavedWork,
  getLocale,
  persistLocaleAndReload,
  t,
} from '../i18n/index.js';
import { applyLocaleChoice, mountLocalePicker } from './localePicker.js';

/**
 * Central UI orchestrator for the God's Eye View application.
 *
 * Responsibilities:
 * - Visual controls and presets backed by the VisualEffects controller.
 * - Bloom and sharpen post-processing toggle/intensity control.
 * - Collapsible rail panels with their collapsed state kept in localStorage.
 * - CCTV panel: camera selection, coverage toggle, projection, calibration
 *   sliders, auto-hop, and summary typewriter effect.
 * - Location bar with city/POI preset pills, QWERTY key navigation,
 *   geocoding search, and inter-city world-jump transitions.
 * - Orbit controller integration for POI fly-around.
 * - Recording mode with safe-frame overlay and HUD mode switching.
 * - Share link encoding/decoding (delegates to ShareLinkManager).
 * - Detection overlay mode cycling and density tuning.
 * - Toast notification system.
 * - Telemetry HUD lifecycle and variant switching.
 */

export class StyleManager extends ShellFacade {
  /**
   * @param {Cesium.Viewer} viewer - The CesiumJS viewer instance.
   * @param {object} [options]
   */
  constructor(
    viewer,
    {
      mapStackController = null,
      placeSearch,
      services,
      requestServices,
      initialShareCode = null,
    } = {},
  ) {
    super();
    const {
      IntelHUD,
      ShareLinkManager,
      CelestialRing,
      initTrackedReadout,
      initWorldOverlay,
      initDetection,
      setDetectionStyle,
      flightsLayer,
      militaryFlightsLayer,
      satellitesLayer,
      bikeshareLayer,
      transitLayer,
      aisLiveVesselsLayer,
      militaryAwarenessLayer,
    } = services;
    this.services = services;
    this._lifetime = new UiLifetime();
    this._recording = new RecordingControls({
      syncShareState: () => this._syncShareState(),
    });
    Object.assign(this, readShellElements());
    this._panelChrome = new PanelChrome({
      elements: {
        _leftPanelStack: this._leftPanelStack,
        _locationSearch: this._locationSearch,
        _ppToggles: this._ppToggles,
        _rightPanelStack: this._rightPanelStack,
      },
      operations: {
        _showToast: (...args) => this._showToast(...args),
      },
      readHud: () => this.hud,
      readShareLinks: () => this.shareLinkManager,
      readInitialShare: () => this._initialShareState,
      readSharedCollapsed: (panelId) =>
        this._mobileShell?.sharedCollapsed(panelId),
    });
    this._feedback = new ShellFeedback({
      readLayers: () => this._dataManager?.getAll?.() || [],
    });
    this.viewer = viewer;
    this.mapStackController = mapStackController;
    this.placeSearch = placeSearch;

    this._navigation = new NavigationController({
      viewer,
      tracking: {
        flightsLayer,
        militaryFlightsLayer,
        satellitesLayer,
        aisLiveVesselsLayer,
        militaryAwarenessLayer,
        rocketLaunchesLayer: services.rocketLaunchesLayer,
      },
      searchInput: this._locationSearch,
      interruptCameraMotion: services.interruptCameraMotion,
      interruptGlobeRotation: services.interruptGlobeRotation,
      clearLocation: () => this.clearSearchedLocation(),
      cancelShareSelection: () => this._shareRestoration.cancelSelection(),
      getDataManager: () => this._dataManager,
      stopOrbit: () => this._stopOrbit(),
      cancelOrientation: () => this._cameraOrientationControls?.cancel(),
      showToast: (text) => this._showToast(text),
    });
    this._shareRestoration = new ShareRestoration({
      viewer,
      navigation: this._navigation,
      syncShareState: () => this._syncShareState(),
      showStatus: (message, options) =>
        this._showGlobalStatusNotice(message, options),
      feedback: this._feedback,
      updateFeedback: () => this._updateGlobalLoadingFeedback(),
      applyFollowOffset: (entity, offset) =>
        applyShareFollowOffset(viewer, entity, offset),
    });

    this._visualSettings = new VisualSettings({
      viewer,
      mapStackController,
      services: {
        setScopeTerminusOverride: services.setScopeTerminusOverride,
        clampScopeTerminusPct: services.clampScopeTerminusPct,
        getDetectionMode: services.getDetectionMode,
        getDetectionTuning: services.getDetectionTuning,
        getKeyholeFadeTuning: services.getKeyholeFadeTuning,
        getScopeMaskFeather: services.getScopeMaskFeather,
        getScopeTerminusOverride: services.getScopeTerminusOverride,
        governorRequestRender: services.governorRequestRender,
        holdContinuousRender: services.holdContinuousRender,
        isCelestialRingStyleSupported: services.isCelestialRingStyleSupported,
        isScopeMaskEnabled: services.isScopeMaskEnabled,
        readDetectionDiagnostics: services.readDetectionDiagnostics,
        releaseContinuousRender: services.releaseContinuousRender,
        setDetectionModeByLabel: services.setDetectionModeByLabel,
        setDetectionStyle: services.setDetectionStyle,
        setDetectionTuning: services.setDetectionTuning,
        setKeyholeFadeTuning: services.setKeyholeFadeTuning,
        setScopeMaskEnabled: services.setScopeMaskEnabled,
        setScopeMaskFeather: services.setScopeMaskFeather,
      },
      elements: {
        _bloomBtn: this._bloomBtn,
        _bloomSlider: this._bloomSlider,
        _bloomSliderRow: this._bloomSliderRow,
        _bloomSliderValue: this._bloomSliderValue,
        _celestialBtn: this._celestialBtn,
        _detectionAllocationRow: this._detectionAllocationRow,
        _detectionBtn: this._detectionBtn,
        _detectionDensitySlider: this._detectionDensitySlider,
        _detectionDensityValue: this._detectionDensityValue,
        _detectionFadeRow: this._detectionFadeRow,
        _detectionFadeSlider: this._detectionFadeSlider,
        _detectionFadeValue: this._detectionFadeValue,
        _detectionOpacityRow: this._detectionOpacityRow,
        _detectionOpacitySlider: this._detectionOpacitySlider,
        _detectionOpacityValue: this._detectionOpacityValue,
        _detectionSliderRow: this._detectionSliderRow,
        _hudBtn: this._hudBtn,
        _cyberSonarBtn: this._cyberSonarBtn,
        _cyberSonarRings: this._cyberSonarRings,
        _cyberSonarRingsValue: this._cyberSonarRingsValue,
        _cyberSonarRange: this._cyberSonarRange,
        _cyberSonarRangeValue: this._cyberSonarRangeValue,
        _cyberSonarIntensity: this._cyberSonarIntensity,
        _cyberSonarIntensityValue: this._cyberSonarIntensityValue,
        _cyberSonarOpacity: this._cyberSonarOpacity,
        _cyberSonarOpacityValue: this._cyberSonarOpacityValue,
        _cyberSonarSector: this._cyberSonarSector,
        _cyberSonarSectorValue: this._cyberSonarSectorValue,
        _hudLayoutRow: this._hudLayoutRow,
        _hudLayoutSelect: this._hudLayoutSelect,
        _ppToggles: this._ppToggles,
        _scopeBtn: this._scopeBtn,
        _scopeFeatherSlider: this._scopeFeatherSlider,
        _scopeFeatherValue: this._scopeFeatherValue,
        _sharpenBtn: this._sharpenBtn,
        _sharpenSlider: this._sharpenSlider,
        _sharpenSliderRow: this._sharpenSliderRow,
        _sharpenSliderValue: this._sharpenSliderValue,
        _sliderContainer: this._sliderContainer,
        _sliderPanel: this._sliderPanel,
        _styleIndicator: this._styleIndicator,
        _styleMiniValue: this._styleMiniValue,
      },
      operations: {
        _restorePanelState: (...args) => this._restorePanelState(...args),
        _layoutRightPanels: (...args) => this._layoutRightPanels(...args),
        _scheduleAdaptivePanelLayout: (...args) =>
          this._scheduleAdaptivePanelLayout(...args),
        _scheduleRightPanelLayout: (...args) =>
          this._scheduleRightPanelLayout(...args),
        _setMapStack: (...args) => this._setMapStack(...args),
        _syncPanelCollapseButton: (...args) =>
          this._syncPanelCollapseButton(...args),
        _syncShareState: (...args) => this._syncShareState(...args),
        setPanelCollapsed: (...args) => this.setPanelCollapsed(...args),
      },
      readHud: () => this.hud,
      readDataManager: () => this._dataManager,
      readShareLinks: () => this.shareLinkManager,
      readCelestialRing: () => this.celestialRing,
      readContextMode: () => this._contextMode,
      readContextChanging: () => this._contextModeChanging,
    });

    this._layerBindings = new LayerBindings({
      viewer,
      services: {
        imageryHost: () =>
          resolveImageryHost({
            viewer,
            tileset: mapStackController?.getImageryHostTileset?.(),
          }),
        cachedGroundFloor: services.cachedGroundFloor,
        warmGroundFloor: services.warmGroundFloor,
      },
      readControls: () => ({
        hud: this.hud,
        _contextControls: this._contextControls,
      }),
      operations: {
        _updateGlobalLoadingFeedback: (...args) =>
          this._updateGlobalLoadingFeedback(...args),
        _syncContextModeButtons: (...args) =>
          this._syncContextModeButtons(...args),
        _stampNavigation: (...args) => this._stampNavigation(...args),
        _runExplicitWorldFocus: (...args) =>
          this._runExplicitWorldFocus(...args),
        runImmediateNavigation: (...args) =>
          this.runImmediateNavigation(...args),
        _showToast: (...args) => this._showToast(...args),
      },
      feedback: this._feedback,
      shareRestoration: this._shareRestoration,
    });

    this._windowResizeHandler = null;
    this._disposed = false;

    this._mapStackChangeHandler = null;

    this._locationNavigation = new LocationNavigation({
      viewer,
      placeSearch,
      navigation: this._navigation,
      services: {
        CITY_POIS: services.CITY_POIS,
        searchAndFlyTo: services.searchAndFlyTo,
        LocationSearch: services.LocationSearch,
        OrbitController: services.OrbitController,
        suspendDetection: services.suspendDetection,
        resumeDetection: services.resumeDetection,
        trafficLayer: services.trafficLayer,
        flyToPresetLocation: services.flyToPresetLocation,
        flyToPOI: services.flyToPOI,
        GLOBE_VIEW: services.GLOBE_VIEW,
        flyToGlobeView: services.flyToGlobeView,
        interruptCameraMotion: services.interruptCameraMotion,
        interruptGlobeRotation: services.interruptGlobeRotation,
        flightsLayer: services.flightsLayer,
        militaryFlightsLayer: services.militaryFlightsLayer,
        satellitesLayer: services.satellitesLayer,
        aisLiveVesselsLayer: services.aisLiveVesselsLayer,
        militaryAwarenessLayer: services.militaryAwarenessLayer,
        rocketLaunchesLayer: services.rocketLaunchesLayer,
      },
      elements: {
        _locationPills: this._locationPills,
        _poiRow: this._poiRow,
        _locationBarDivider: this._locationBarDivider,
        _locationSearch: this._locationSearch,
        _locationSearchError: this._locationSearchError,
        _searchToggle: this._searchToggle,
        _resetGlobeBtn: this._resetGlobeBtn,
        _locationMiniCity: this._locationMiniCity,
        _locationMiniPoi: this._locationMiniPoi,
      },
      operations: {
        _beginDeferredNavigation: (...args) =>
          this._beginDeferredNavigation(...args),
        _reassertNavigationHandoff: (...args) =>
          this._reassertNavigationHandoff(...args),
        _settleLocationSearchUi: (...args) =>
          this._settleLocationSearchUi(...args),
        _runExplicitNavigation: (...args) =>
          this._runExplicitNavigation(...args),
        _stampNavigation: (...args) => this._stampNavigation(...args),
        _showToast: (...args) => this._showToast(...args),
      },
    });

    // Telemetry HUD
    this.hud = new IntelHUD(viewer);
    this._recording.hud = this.hud;

    // Full-globe sun/moon ring. It is a crisp screen-space overlay above the
    // Cesium canvas but below the HUD/detection/readout z ladder.
    this.celestialRing = new CelestialRing(viewer, {
      enabled: false,
      onAutoDisable: () =>
        this.setCelestialRingEnabled(false, {
          syncShare: !!this.shareLinkManager,
          focus: false,
        }),
    });

    // Share Link Manager
    this.shareLinkManager = new ShareLinkManager(viewer, {
      onRestore: async (state) => {
        return this._visualSettings.restoreShareState(state);
      },
      isNavigationCurrent: (generation) =>
        generation === this._navigationGeneration,
      cancelOwnedNavigation: () => this.viewer.camera.cancelFlight(),
      // A host may open a share code without a `/share/<code>` address.
      initialShareCode,
    });
    this.shareLinkManager.setFollowSubjectProvider(({ nowMs }) =>
      readShareFollowSubject({ viewer: this.viewer, nowMs }),
    );
    this.shareLinkManager.setPanelStateProvider(() =>
      this._buildSharePanelState(),
    );
    this.shareLinkManager.setStyleParamStateProvider((styleName) => {
      const shader = STYLES[styleName];
      const stage = this.stages[styleName];
      if (!shader?.uniforms || !stage) return null;
      return Object.fromEntries(
        Object.keys(shader.uniforms).map((uniformName) => [
          uniformName,
          stage.uniforms[uniformName],
        ]),
      );
    });
    this._shareState = createStateChannel(() => this._readShareState());
    this._shareState.subscribe(
      ({ state }) => {
        this.shareLinkManager.onToggleChange(
          state.bloomEnabled,
          state.sharpenEnabled,
          state.options,
        );
      },
      { emitCurrent: false },
    );
    // Parse before panel chrome initializes so every valid share URL starts
    // from deterministic markup defaults instead of recipient-local panel
    // preferences. Encoded panel fields are applied after all panels exist.
    this._shareRestoration.attachLinks(this.shareLinkManager);

    // The shared world-overlay host must own its one postRender lane before
    // detection and tracked-readout initialize. It stays transparent until a
    // production source explicitly registers entries.
    initWorldOverlay(viewer);

    // Initialize detection overlay BEFORE style stages so the composite
    // stage is first in the post-process pipeline
    initDetection(
      viewer,
      [
        flightsLayer,
        satellitesLayer,
        bikeshareLayer,
        transitLayer,
        aisLiveVesselsLayer,
      ].filter(Boolean),
      (modeLabel) => {
        this._updateDetectionButton(modeLabel);
      },
    );
    initTrackedReadout(viewer);
    setDetectionStyle(this.activeStyle);
    this._applyDetectionDensityFromUi();

    this._initStages();
    this._initBloomSharpen();
    this._displayBindings = new DisplayBindings({
      viewer,
      services: {
        cycleDetectionMode: services.cycleDetectionMode,
        setScopeMaskEnabled: services.setScopeMaskEnabled,
        isScopeMaskEnabled: services.isScopeMaskEnabled,
        setScopeMaskFeather: services.setScopeMaskFeather,
      },
      elements: {
        _locationSearch: this._locationSearch,
        _bloomBtn: this._bloomBtn,
        _bloomSlider: this._bloomSlider,
        _sharpenBtn: this._sharpenBtn,
        _sharpenSlider: this._sharpenSlider,
        _scopeBtn: this._scopeBtn,
        _scopeFeatherSlider: this._scopeFeatherSlider,
        _hudLayoutSelect: this._hudLayoutSelect,
        _hudBtn: this._hudBtn,
        _cyberSonarBtn: this._cyberSonarBtn,
        _cyberSonarRings: this._cyberSonarRings,
        _cyberSonarRange: this._cyberSonarRange,
        _cyberSonarIntensity: this._cyberSonarIntensity,
        _cyberSonarOpacity: this._cyberSonarOpacity,
        _cyberSonarSector: this._cyberSonarSector,
        _cleanViewBtn: this._cleanViewBtn,
        _cleanViewExitBtn: this._cleanViewExitBtn,
        _detectionDensitySlider: this._detectionDensitySlider,
        _detectionBtn: this._detectionBtn,
        _detectionFadeSlider: this._detectionFadeSlider,
        _detectionOpacitySlider: this._detectionOpacitySlider,
        _celestialBtn: this._celestialBtn,
        _scopeFeatherValue: this._scopeFeatherValue,
        _sharpenSliderValue: this._sharpenSliderValue,
        _detectionDensityValue: this._detectionDensityValue,
      },
      operations: {
        setStyle: (...args) => this.setStyle(...args),
        _updateHudButtonState: (...args) => this._updateHudButtonState(...args),
        _syncShareState: (...args) => this._syncShareState(...args),
        _toggleOrbit: (...args) => this._toggleOrbit(...args),
        toggleCleanView: (...args) => this.toggleCleanView(...args),
        _setBloomEnabled: (...args) => this._setBloomEnabled(...args),
        _setBloomIntensity: (...args) => this._setBloomIntensity(...args),
        _setSharpenEnabled: (...args) => this._setSharpenEnabled(...args),
        _applySharpenIntensity: (...args) =>
          this._applySharpenIntensity(...args),
        _setHudVariant: (...args) => this._setHudVariant(...args),
        _setCyberSonarEnabled: (...args) => this._setCyberSonarEnabled(...args),
        _setCyberSonarSetting: (...args) => this._setCyberSonarSetting(...args),
        _applyDetectionDensityFromUi: (...args) =>
          this._applyDetectionDensityFromUi(...args),
        _setDetectionAllocation: (...args) =>
          this._setDetectionAllocation(...args),
        _applyDetectionFadeFromUi: (...args) =>
          this._applyDetectionFadeFromUi(...args),
        setCelestialRingEnabled: (...args) =>
          this.setCelestialRingEnabled(...args),
      },
      readState: () => ({
        shareLinkManager: this.shareLinkManager,
        hud: this.hud,
        bloomEnabled: this.bloomEnabled,
        sharpenEnabled: this.sharpenEnabled,
        celestialRing: this.celestialRing,
        celestialRingEnabled: this.celestialRingEnabled,
        _detectionAllocationBtns: this._detectionAllocationBtns,
      }),
      claimDetection: () => {
        this._visualSettings._detectionUserOverridden = true;
      },
    });
    this._initUI();
    this._initMapStackControl();
    // Headers first: panel chrome builds its toggle labels from them.
    this._applyRuntimeStaticHeaderText();
    this._initPanelChrome();
    this._initLocaleSelector();
    this._sizeDisplayLabelColumn();
    this._initLeftPanelAdaptiveLayout();
    this._initRightPanelAdaptiveLayout();
    this._initGlobalContextPanel();
    this._initLocationBar();
    this._initMobileShell();
    this._initShareButton();
    this._initCameraOrientationControls();
    this._initClearSelectedLayersButton();
    this._initHUDToggle();
    this._applyGlobalPostDefaults();
    this._initOrbit();
    this._initRecordingOverlay();
    this._startAnimationLoop();
    this._startLoadingPollTicker();
    this._updateStyleMiniStatus();
    this._updateLocationMiniStatus();

    this._shareRestoration.start();

    // Keep the parameter panel from overlapping toggle controls.
    this._layoutRightPanels();
    this._windowResizeHandler = () => {
      this._scheduleRightPanelLayout({ reconsiderAutoCollapse: true });
      this._scheduleLeftPanelLayout({ reconsiderAutoCollapse: true });
    };
    window.addEventListener('resize', this._windowResizeHandler);
    // The loading-chip ticker is stopped while the tab is hidden (it can do no
    // useful work off-screen and must not hold a 60ms timer there). Resample on
    // return so the time-driven reducer catches up on real elapsed time — and
    // re-arms its own ticker if the batch is still running.
    this._feedback.observeVisibility();
    this._layerBindings.observeCamera();
  }

  // Compatibility reads for existing controls and scene snapshots.

  /** Advance camera authority and settle any older search UI immediately. */
  _stampNavigation({
    cancelPendingSelection = true,
    clearSearchedLocation = true,
  } = {}) {
    return this._navigation._stampNavigation(...arguments);
  }

  /** Release every follow owner while preserving Contact and vessel selection. */
  _releaseFollowCamera({
    preserveVesselSelection = true,
    preserveCameraFlight = false,
    trackingOrigin = 'tool',
  } = {}) {
    return this._navigation._releaseFollowCamera(...arguments);
  }

  /** Accept a delayed lookup without releasing its current camera owner. */
  _beginDeferredNavigation(
    noun = 'location',
    { cancelPendingSelection = true } = {},
  ) {
    return this._navigation._beginDeferredNavigation(...arguments);
  }

  /** Public lifecycle seam used by voice location navigation. */
  beginDeferredLocationNavigation() {
    return this._beginDeferredNavigation('location');
  }

  /** Public final-authority seam used by voice geocoding. */
  reassertDeferredLocationNavigation(generation) {
    return this._reassertNavigationHandoff(generation);
  }

  /** Public immediate route used by voice destinations. */
  runImmediateLocationNavigation(navigate) {
    return this.runImmediateNavigation('location', navigate);
  }

  /** Public authority facade used by validated voice camera destinations. */
  runImmediateNavigation(noun, navigate, releaseOptions = undefined) {
    return this._runExplicitNavigation(noun, navigate, releaseOptions);
  }

  /** Supersede deferred work when an owner-specific route handles release. */
  supersedeDeferredNavigation() {
    return this._stampNavigation();
  }

  /** Route a valid vessel/fire request through the shared navigation policy. */
  _runExplicitWorldFocus(detail, fly) {
    return this._runExplicitNavigation(detail?.kind || 'target', fly);
  }

  /**
   * Sets the bloom intensity, updates the slider UI, and applies the value.
   * @param {number} intensity - Raw intensity percentage.
   * @param {object} [options]
   * @param {boolean} [options.syncShare=true] - Whether to push state to the share link.
   * @returns {void}
   */
  _setBloomIntensity(intensity, { syncShare = true } = {}) {
    return this._visualSettings._setBloomIntensity(...arguments);
  }

  /**
   * Wires up all primary UI event listeners: style buttons, keyboard shortcuts
   * (1-8 style keys, H/O/V/F/D/C hotkeys, Escape), AI prompt input with
   * debounce, bloom/sharpen/HUD toggles, detection density slider, and
   * clean-view toggle.
   * @returns {void}
   */
  _initUI() {
    this._displayBindings._initUI();
  }

  /**
   * Mounts the language picker (src/ui/localePicker.js). A choice reloads the
   * page; _confirmLocaleReload asks first when that would lose work.
   * @returns {void}
   */
  _initLocaleSelector() {
    // Work that a reload drops is registered by the modules that own it
    // (registerUnsavedWork in src/i18n/index.js).
    const root = globalThis.document?.getElementById?.('locale-picker');
    if (!root) return;
    this._localePicker = mountLocalePicker({
      root,
      current: getLocale(),
      onSelect: (locale) => this._chooseLocale(locale),
    });
  }

  /**
   * Switch to `locale`: nothing for the active language, otherwise store it
   * and reload once _confirmLocaleReload agrees.
   * @param {string} locale
   * @returns {'unchanged'|'declined'|'switched'}
   */
  _chooseLocale(locale) {
    return applyLocaleChoice(locale, {
      current: getLocale(),
      confirmSwitch: () => this._confirmLocaleReload(),
      switchLocale: (next) => persistLocaleAndReload(next),
    });
  }

  /**
   * Switching language reloads the page. While that would lose work the page
   * cannot restore, ask first.
   * @returns {boolean} true to switch.
   */
  _confirmLocaleReload() {
    const lost = describeUnsavedWork();
    if (!lost.length || typeof globalThis.confirm !== 'function') return true;
    return globalThis.confirm(
      t(
        'Switching language reloads the page. This will be lost: {items}. Switch anyway?',
        { items: lost.join(', ') },
      ),
    );
  }

  /**
   * Sizes one Display-panel label column to the longest label in the active
   * language, so slider tracks line up. Counts characters (labels are
   * monospace and often hidden); CSS turns the count into a width.
   * @returns {void}
   */
  _sizeDisplayLabelColumn() {
    const labels = document.querySelectorAll(
      '#pp-toggles .pp-slider-row > .pp-slider-mini-label',
    );
    let longest = 0;
    for (const label of labels) {
      longest = Math.max(longest, label.textContent.trim().length);
    }
    if (longest > 0) {
      document.documentElement.style.setProperty(
        '--pp-label-chars',
        String(longest),
      );
    }
  }

  /**
   * Rewrites a header's last text node, keeping the leading icon span that a
   * textContent write would destroy.
   * @param {Element|null} element
   * @param {string} text
   * @returns {void}
   */
  _setHeaderText(element, text) {
    if (!element) return;
    const textNode = Array.from(element.childNodes)
      .reverse()
      .find(
        (node) => node.nodeType === Node.TEXT_NODE && node.nodeValue?.trim(),
      );
    if (textNode) textNode.nodeValue = text;
    else element.textContent = text;
  }

  /**
   * Translates at boot the header texts that share their element with an
   * icon or a <br> (data-i18n-runtime in the templates).
   * @returns {void}
   */
  _applyRuntimeStaticHeaderText() {
    this._setHeaderText(
      document.querySelector('#control-panel .panel-title'),
      t('VISUAL PRESETS'),
    );
    this._setHeaderText(
      document.querySelector('#location-bar .location-toolbar-label'),
      t('LOCATION'),
    );
    // One span holds both mode descriptions around a <br>; keep the <br>.
    const standbyDescription = document.querySelector(
      '#context-mode-standby span',
    );
    if (standbyDescription) {
      standbyDescription.replaceChildren(
        document.createTextNode(
          t('CONTACTS — nearest planes · vessels'),
        ),
        document.createElement('br'),
        document.createTextNode(
          t('SPACE MISSIONS — launches & orbital assets'),
        ),
      );
    }
  }

  /**
   * Phone layout: a bottom tab bar presenting one panel sheet at a time
   * (src/ui/mobileShell.js). Inactive above 720px.
   * @returns {void}
   */
  _initMobileShell() {
    this._mobileShell = initMobileShell({
      setPanelCollapsed: (panelId, collapsed, options) =>
        this._panelChrome.setPanelCollapsed(panelId, collapsed, options),
      onSheetsClosed: () => this._syncShareState(),
    });
  }

  /**
   * Renders the owner-approved map stack chip row from the matching controller
   * entries. Cesium ion/Bing chips remain keyboard-focusable but unavailable,
   * with an accessible explanation, until a CESIUM_ION_TOKEN is configured.
   * @returns {void}
   */
  _initMapStackControl() {
    if (!this.mapStackController) return;

    this._mapSourceControls?.destroy();
    this._mapSourceControls = createMapSourceControls({
      container: this._mapStackChips,
      statusElement: this._mapStackStatus,
      controller: this.mapStackController,
      subscribe: (onChange) => {
        window.addEventListener('gev:map-stack-changed', onChange);
        return () =>
          window.removeEventListener('gev:map-stack-changed', onChange);
      },
      claimSelection: () => this.shareLinkManager?.claimRestoreLane?.('map'),
      onStateChanged: () => this._syncShareState(),
      onError: (message) => this._showToast(message),
    });
  }

  /**
   * Switches the active map/globe source stack.
   * @param {string} stackId - Map stack id.
   * @param {object} [options]
   * @param {boolean} [options.syncShare=true] - Whether to update the share link.
   * @returns {Promise<void>}
   */
  async _setMapStack(stackId, { syncShare = true } = {}) {
    if (!this.mapStackController) return;
    return this._mapSourceControls.select(stackId, { syncShare });
  }

  /**
   * Syncs the map stack chip row and status chip with controller state. The
   * lit chip always follows `state.activeId`, never the click — a rejected or
   * superseded switch therefore leaves the genuinely active stack lit.
   * @param {object} state - Map stack controller state.
   * @returns {void}
   */
  _renderMapStackState(state) {
    this._mapSourceControls?.render(state);
  }

  _setDetectionAllocation(strategy, { syncShare = true, persist = true } = {}) {
    return this._visualSettings._setDetectionAllocation(...arguments);
  }

  /**
   * Pushes the current visual state (bloom, sharpen, HUD, detection) to
   * the ShareLinkManager so the URL hash stays in sync.
   * @returns {void}
   */

  _syncShareState() {
    if (this._disposed) return;
    this._shareState.publish({ type: 'settings-changed' });
  }

  _setCommandDockPanelPinState(
    panelId,
    pin,
    { restore = false, persist = true, syncShare = true } = {},
  ) {
    return this._panelChrome._setCommandDockPanelPinState(...arguments);
  }

  /**
   * Configures intentional hover-expand / leave-collapse behavior on a panel.
   * Uses separate open/close timers to prevent accidental flicker from fast
   * mouse passes. Wheel events cancel pending opens to avoid surprise expansion
   * during scroll-through.
   * @param {string} panelId - DOM id of the panel element.
   * @param {object} [options]
   * @param {number} [options.openDelayMs=850] - Hover dwell time before auto-expanding.
   * @param {number} [options.closeDelayMs=1000] - Delay after pointer leaves before collapsing.
   * @returns {void}
   */
  _initAutoHoverPanel(
    panelId,
    { openDelayMs = 850, closeDelayMs = 1000 } = {},
  ) {
    return this._panelChrome._initAutoHoverPanel(...arguments);
  }

  _initGlobalContextPanel() {
    this._contextControls = new ContextControls({
      elements: {
        _globalContextPanel: document.getElementById('global-context-panel'),
        _globalContextFlightsBtn: this._globalContextFlightsBtn,
        _globalContextMissionsBtn: this._globalContextMissionsBtn,
        _contextModeStandby: this._contextModeStandby,
        _contextMissionsView: this._contextMissionsView,
      },
      actions: {
        claimVisualAuthority: () =>
          this.shareLinkManager?.claimRestoreLane?.('visual'),
        syncDetection: () => this._syncContactsDetection(),
        scheduleLayout: () => this._scheduleRightPanelLayout(),
        setPanelCollapsed: (...args) => this.setPanelCollapsed(...args),
        showToast: (message) => {
          if (!this._disposed) this._showToast(message);
        },
        setClearBusy: (busy) => {
          if (!this._disposed) this._clearLayersControl?.setBusy(busy);
        },
      },
    });
  }

  /**
   * Programmatically collapses or expands a panel, persists the state,
   * and triggers layout recalculation for dependent panels.
   * @param {string} panelId - DOM id of the panel.
   * @param {boolean} collapsed - Whether to collapse the panel.
   * @param {object} [options] Disclosure ownership options.
   * @param {boolean} [options.explicit=false] Whether a direct user action owns the panel lane.
   * @returns {void}
   */
  setPanelCollapsed(
    panelId,
    collapsed,
    {
      explicit = false,
      restore = false,
      persist = true,
      syncShare = true,
    } = {},
  ) {
    return this._panelChrome.setPanelCollapsed(...arguments);
  }

  /**
   * Toggles "clean view" mode which hides all UI panels via a CSS body class.
   * @param {boolean} [forceEnabled] - Explicit on/off. Omit to toggle.
   * @returns {void}
   */
  toggleCleanView(forceEnabled) {
    const shouldEnable =
      typeof forceEnabled === 'boolean'
        ? forceEnabled
        : !document.body.classList.contains('ui-clean-view');
    document.body.classList.toggle('ui-clean-view', shouldEnable);
    if (this._cleanViewBtn) {
      this._cleanViewBtn.classList.toggle('active', shouldEnable);
    }
    this._scheduleLeftPanelLayout();
  }

  // ── Public control facade ──────────────────────────────────────────────
  // Deliberate API for voice tools and scripting. Every setter keeps the DOM
  // sliders, share-link state, and scene snapshots in sync, and returns
  // { ok, ...resultingState } so callers confirm only what actually happened.

  /**
   * Sets HUD visibility mode. 'auto' restores style-driven show/hide.
   * @param {'on'|'off'|'auto'} mode - Visibility mode.
   * @returns {{ok: boolean, visible?: boolean, layout?: string, error?: string}}
   */
  setHudVisible(mode) {
    const normalized = String(mode ?? '').toLowerCase();
    if (!['on', 'off', 'auto'].includes(normalized)) {
      return { ok: false, error: `Unknown HUD visibility mode: ${mode}` };
    }
    this.shareLinkManager?.claimRestoreLane?.('visual');
    this.hud.setMode(normalized);
    this._updateHudButtonState();
    this._syncShareState();
    return {
      ok: true,
      visible: !!this.hud.visible,
      mode: normalized,
      layout: this.hud.getVariant(),
    };
  }

  /**
   * Switches the HUD layout variant.
   * @param {'tactical'|'minimal'|'cyber'} variantName - Layout variant.
   * @returns {{ok: boolean, layout?: string, visible?: boolean, error?: string}}
   */
  setHudLayout(variantName) {
    const variant = String(variantName ?? '').toLowerCase();
    if (!isHudLayout(variant)) {
      return { ok: false, error: `Unknown HUD layout: ${variantName}` };
    }
    this.shareLinkManager?.claimRestoreLane?.('visual');
    this._setHudVariant(variant, { applyVisualDefaults: true });
    return {
      ok: true,
      layout: this.hud.getVariant(),
      visible: !!this.hud.visible,
    };
  }

  /**
   * Controls the detection overlay: on/off, mode, and density percent.
   * Density writes the slider AND the engine so share links and scene
   * snapshots stay truthful.
   * @param {object} [options]
   * @param {boolean} [options.enabled] - false forces OFF; true restores the current density profile.
   * @param {'sparse'|'balanced'|'dense'|'panoptic'} [options.mode] - Profile (legacy aliases accepted).
   * @param {number} [options.densityPct] - 0-100 density percent.
   * @param {'elastic'|'weighted'} [options.allocationStrategy] - Layer-capacity policy.
   * @param {number} [options.fadePct] - Fade distance as 0-40% of the keyhole radius.
   * @param {number} [options.outsideOpacityPct] - Opacity beyond the fade distance, 0-100%.
   * @returns {{ok: boolean, detectionMode?: string, densityPct?: number|null, error?: string}}
   */
  setDetection({
    enabled,
    mode,
    densityPct,
    allocationStrategy,
    fadePct,
    outsideOpacityPct,
  } = {}) {
    return this._visualSettings.setDetection(...arguments);
  }

  /**
   * Switches the basemap stack and reports whether the switch landed.
   * @param {string} stackId - One of mapStackController.getStacks() ids.
   * @returns {Promise<{ok: boolean, activeStack?: string, error?: string|null, available?: string[]}>}
   */
  async setMapStack(stackId) {
    if (!this.mapStackController) {
      return { ok: false, error: 'Map stack controller unavailable' };
    }
    const stacks = this.mapStackController.getStacks();
    const target = stacks.find((stack) => stack.id === stackId);
    if (!target) {
      return {
        ok: false,
        error: `Unknown map stack: ${stackId}`,
        available: stacks.map((s) => s.id),
      };
    }
    if (!target.available) {
      return {
        ok: false,
        error: `${target.label} requires a Cesium ion token`,
        activeStack: this.mapStackController.getActiveId(),
      };
    }
    await this._setMapStack(stackId);
    const state = this.mapStackController.getState();
    const landed = state.activeId === stackId;
    return {
      ok: landed,
      activeStack: state.activeId,
      error: landed ? null : state.lastError || 'Map stack did not switch',
    };
  }

  /**
   * Controls bloom post-processing. Intensity is the UI percent (0-200).
   * @param {object} [options]
   * @param {boolean} [options.enabled]
   * @param {number} [options.intensityPct] - 0-200.
   * @returns {{ok: boolean, bloom: {enabled: boolean, intensityPct: number|null}}}
   */
  setBloom({ enabled, intensityPct } = {}) {
    return this._visualSettings.setBloom(...arguments);
  }

  /**
   * Controls sharpen post-processing. Intensity is the UI percent (0-100).
   * @param {object} [options]
   * @param {boolean} [options.enabled]
   * @param {number} [options.intensityPct] - 0-100.
   * @returns {{ok: boolean, sharpen: {enabled: boolean, intensityPct: number|null}}}
   */
  setSharpen({ enabled, intensityPct } = {}) {
    return this._visualSettings.setSharpen(...arguments);
  }

  /**
   * Controls the celestial ring. The Display button uses `focus=true` when the
   * ring is disabled or unavailable at the current zoom, turning the control
   * into a reveal action instead of requiring a separate globe-navigation step.
   * @param {boolean} enabled
   * @param {object} [options]
   * @param {boolean} [options.syncShare=true]
   * @param {boolean} [options.focus=false]
   * @returns {{ok:boolean, celestialRing:{enabled:boolean,visible:boolean}, cameraFocused:boolean, error?:string}}
   */
  setCelestialRingEnabled(enabled, { syncShare = true, focus = false } = {}) {
    return this._visualSettings.setCelestialRingEnabled(...arguments);
  }

  /**
   * Enables/disables clean view (hides all UI chrome).
   * @param {boolean} [enabled] - Omit to toggle.
   * @returns {{ok: boolean, cleanView: boolean}}
   */
  setCleanView(enabled) {
    this.toggleCleanView(enabled);
    return {
      ok: true,
      cleanView: document.body.classList.contains('ui-clean-view'),
    };
  }

  /** Apply Cyber-only sonar settings through the shared visual controls. */
  setCyberSonar(settings) {
    return setCyberSonarControls(this, settings);
  }

  /**
   * Full control-state snapshot — single source for voice read-back so the
   * agent confirms from the same state it acted on.
   * @returns {object} Current style/stack/HUD/detection/post-processing state.
   */
  getControlState() {
    return {
      style: this.activeStyle || 'normal',
      mapStack: this.mapStackController?.getActiveId?.() || null,
      hud: {
        visible: !!this.hud?.visible,
        layout: this.hud?.getVariant?.() || null,
        sonar: getCyberSonarControlState(),
      },
      detection: this.getDetectionState(),
      bloom: {
        enabled: !!this.bloomEnabled,
        intensityPct: this._bloomSlider
          ? parseInt(this._bloomSlider.value, 10)
          : null,
      },
      sharpen: {
        enabled: !!this.sharpenEnabled,
        intensityPct: this._sharpenSlider
          ? parseInt(this._sharpenSlider.value, 10)
          : null,
      },
      celestialRing: {
        enabled: this.celestialRingEnabled,
        visible: !!this.celestialRing?.visible,
      },
      orbiting: !!this.orbitController?.active,
      recording: !!this._recording._recordingMode,
      cleanView: document.body.classList.contains('ui-clean-view'),
    };
  }

  /**
   * Captures the current camera position and orientation as a serializable object.
   * @returns {{lat: number, lon: number, alt: number, heading: number, pitch: number, roll: number}|null}
   */
  getCameraState() {
    const carto = this.viewer.camera.positionCartographic;
    if (!carto) return null;
    return {
      lat: Cesium.Math.toDegrees(carto.latitude),
      lon: Cesium.Math.toDegrees(carto.longitude),
      alt: carto.height,
      heading: Cesium.Math.toDegrees(this.viewer.camera.heading),
      pitch: Cesium.Math.toDegrees(this.viewer.camera.pitch),
      roll: Cesium.Math.toDegrees(this.viewer.camera.roll),
    };
  }

  /**
   * Flies the camera to a previously captured camera state using cubic ease-in-out.
   * @param {{lat: number, lon: number, alt: number, heading?: number, pitch?: number, roll?: number}} cameraState
   * @param {number} [duration=2.8] - Flight duration in seconds.
   * @returns {void}
   */
  applyCameraState(cameraState, duration = 2.8) {
    if (!cameraState) return;
    this.viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(
        cameraState.lon,
        cameraState.lat,
        cameraState.alt,
      ),
      orientation: {
        heading: Cesium.Math.toRadians(cameraState.heading || 0),
        pitch: Cesium.Math.toRadians(cameraState.pitch || -35),
        roll: Cesium.Math.toRadians(cameraState.roll || 0),
      },
      duration: Math.max(0.2, duration || 0),
      easingFunction: Cesium.EasingFunction.CUBIC_IN_OUT,
    });
  }

  /**
   * Restores a full visual state snapshot, applying style, bloom, sharpen,
   * HUD, detection, and per-style shader uniforms. Used by scene recipes
   * and share-link restore. Async so the map-stack switch resolves before
   * the share state is synced; callers may fire-and-forget.
   * @param {object} [state={}] - Visual state object (as returned by getVisualState).
   * @param {object} [options]
   * @param {(() => boolean)|null} [options.isCurrent] Caller liveness predicate.
   *   The map-stack switch is this method's ONLY suspension point, and the
   *   shader-uniform writes come after it — so a caller superseded while that
   *   switch is in flight would otherwise resume and commit the look of a
   *   state the operator has already moved past. Scene playback reproduced
   *   exactly that: a stale shot's uniforms landing on top of the live run.
   *   Omit it and the method behaves as it always has.
   * @returns {Promise<boolean>} Whether the state was committed.
   */
  async applyVisualState(state = {}, { isCurrent = null } = {}) {
    return this._visualSettings.applyVisualState(...arguments);
  }

  /**
   * Applies recording-friendly post-processing and shader uniform overrides.
   * @param {object} preset
   */
  applyCinematicPreset(preset = {}) {
    return this._visualSettings.applyCinematicPreset(...arguments);
  }

  // ── Parameter Sliders ─────────────────────────

  /**
   * Rebuilds the parameter slider panel for the given style's shader uniforms.
   * Creates a labeled range input for each tunable uniform. Hides the panel
   * for 'normal' mode which has no shader parameters.
   * @param {string} styleName - Style name whose uniforms to display.
   * @returns {void}
   */
  _updateSliderPanel(styleName, { reveal = false } = {}) {
    return this._visualSettings._updateSliderPanel(...arguments);
  }

  // ── Style switching ───────────────────────────

  /**
   * Switches the active visual style. Handles full lifecycle:
   * 1. Crossfades the previous shader stage intensity to 0.
   * 2. Crossfades the new shader stage intensity to 1.
   * 3. Applies style preset defaults (bloom/sharpen/HUD) if applyPreset is true.
   * 4. Updates button highlights, style indicator, slider panel, HUD, and detection overlay.
   * @param {string} styleName - Target style ('normal'|'retro'|'surveillance'|'thermal'|'anime'|'noir').
   * @param {object} [options]
   * @param {boolean} [options.applyPreset=true] - Whether to apply STYLE_PRESET_DEFAULTS for the new style.
   * @param {boolean} [options.userInitiated=false] - Whether a direct user preset choice owns the Cyber exit style.
   * @param {boolean} [options.preserveCyberRestore=false] - Whether an automatic style update keeps the Cyber entry snapshot.
   * @returns {void}
   */
  setStyle(
    styleName,
    {
      applyPreset = true,
      revealParameters = applyPreset,
      restore = false,
    } = {},
  ) {
    return this._visualSettings.setStyle(...arguments);
  }

  // ── Shader transitions ────────────────────────

  /**
   * Style animation loop — self-stopping (perf wave 2). Runs only while a
   * crossfade is in flight or an animated (time-uniform) stage is visible,
   * holding continuous scene render for exactly that long. Re-armed by
   * _startTransition and by _setStageIntensity enabling an animated stage.
   * The loading chip poll has its own 500 ms interval (see
   * _startLoadingPollTicker).
   */
  _startAnimationLoop() {
    this._visualEffects.startAnimationLoop();
  }

  /**
   * Release camera ownership when a resolved Location destination starts.
   * Contact mode and its selected subject remain intact so FOCUS can return to
   * that subject after the user finishes inspecting the destination.
   * @returns {boolean} Whether a Contact subject remains selected.
   */
  beginLocationNavigation() {
    this._stampNavigation();
    return this._releaseFollowCamera({ preserveVesselSelection: false });
  }

  /** Wire the top-center action that clears only manager-owned data layers. */
  _initClearSelectedLayersButton() {
    if (!this._clearSelectedLayersBtn) return;
    this._clearLayersControl?.destroy();
    this._clearLayersControl = bindClearLayersControl(
      this._clearSelectedLayersBtn,
      () => this.clearSelectedLayers(),
    );
  }

  /** Wire Google Maps-style tilt and north-up camera actions. */
  _initCameraOrientationControls() {
    this._cameraOrientationControls?.destroy();
    this._cameraOrientationControls = bindCameraOrientationControls({
      viewer: this.viewer,
      elements: {
        tiltButton: this._tiltMapBtn,
        northButton: this._northUpBtn,
      },
      runNavigation: (noun, navigate) =>
        this._navigation.runOrientation(noun, navigate),
      showToast: (message) => this._showToast(message),
    });
  }

  // ── Share Button ─────────────────────────────

  /**
   * Wires the share button. By default it copies the current share link to the
   * clipboard; a host may pass `services.shareLink(url)` to share it another way
   * (a system share sheet, for example). It resolves to 'shared', 'copied',
   * 'cancelled' (no toast) or false (failed).
   * @returns {void}
   */
  _initShareButton() {
    this._lifetime.listen(this._shareBtn, 'click', async () => {
      const share = this.services.shareLink;
      let result;
      if (typeof share === 'function') {
        // A host's hook may return a plain value or throw; both are answers.
        result = await Promise.resolve()
          .then(() => {
            const href = this.shareLinkManager.buildLink();
            return href ? share(href) : false;
          })
          .catch(() => false);
      } else {
        result = (await this.shareLinkManager.copyLink()) ? 'copied' : false;
      }
      if (this._disposed || result === 'cancelled') return;
      this._showToast(
        result === 'shared'
          ? t('Link shared')
          : result === 'copied'
            ? t('Link copied!')
            : t('Copy failed'),
      );
    });
  }

  // ── HUD Toggle ───────────────────────────────

  /**
   * Wires the HUD toggle button, initializes the default HUD variant to 'tactical',
   * and sets up the detection mode cycle button.
   * @returns {void}
   */
  _initHUDToggle() {
    if (this._hudLayoutSelect) {
      this._hudLayoutSelect.value = 'tactical';
    }
    this._setHudVariant('tactical');
    this.hud.setMode('on');
    this._updateHudButtonState();

  }

  /** Terminal result for the complete initial share restoration. */
  get initialRestorePromise() {
    return (
      this._initialShareRestorePromise ||
      Promise.resolve({ status: 'not-requested' })
    );
  }

  /**
   * Tear down the StyleManager — cancel animation loop, clear intervals,
   * and release resources. Call this before discarding the instance to
   * prevent leaked rAF loops and event listeners.
   * @returns {Promise<void>} Resolves after focused-session state restoration.
   */
  async dispose() {
    const { destroyTrackedReadout, destroyWorldOverlay, destroyDetection } =
      this.services;
    if (this._disposed) return;
    this._shareRestoration.destroy();
    this._feedback._globalStatusNotice = null;
    if (this._globalLoadingStatus) this._globalLoadingStatus.hidden = true;
    this._disposed = true;
    this._navigation.stop();
    this._shareState.destroy();
    this._locationNavigation.destroy();
    this._lifetime.destroy();
    this._localePicker?.destroy();
    this._localePicker = null;
    this._recording.destroy();
    this._mobileShell?.destroy();
    this._panelChrome.destroy();
    this._feedback.destroy();

    this._displayBindings.destroy();
    this._mapSourceControls?.destroy();
    this._cameraOrientationControls?.destroy();
    this._clearLayersControl?.destroy();
    this._visualSettings.stop();
    this.shareLinkManager?.destroy();
    this._layerBindings.stop();

    // Invalidate any in-flight Context transaction the same way a newer request
    // would. Without this, a reinstatement already past its awaits could
    // re-enable a mode's entry layer and republish `_contextMode` while the
    // rest of teardown is tearing those very layers down.
    this._contextControls.stop();
    this._navigation.destroy();
    // Close camera-entry seams synchronously. Context restoration may await
    // layer work, so leaving these listeners attached until afterward lets a
    // focus event release tracking or start a flight during teardown.
    await this._contextControls.restoreForDisposal();
    // IR boost teardown BEFORE detaching the data manager: restore fog and
    // un-boost both aircraft layers so a surviving viewer or replacement
    // manager doesn't inherit sensor state (review P2, 2026-08-16).
    this._visualSettings.releaseIrBoost();
    this._contextControls.disconnect();
    this._layerBindings.disconnect();

    if (this._windowResizeHandler) {
      window.removeEventListener('resize', this._windowResizeHandler);
      this._windowResizeHandler = null;
    }
    destroyTrackedReadout();
    destroyDetection();
    destroyWorldOverlay();
    this.celestialRing?.destroy();
    this._visualSettings.destroy();
  }
}
