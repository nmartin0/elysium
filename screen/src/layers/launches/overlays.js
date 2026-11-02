import * as Cesium from 'cesium';
import { t } from '../../i18n/index.js';
import {
  ROCKET_MISSION_AMBIENT_OVERLAY_COHORT_LIMIT,
  ROCKET_MISSION_AMBIENT_OVERLAY_SOURCE_ID,
  ROCKET_MISSION_SELECTED_OVERLAY_SOURCE_ID,
  ROCKET_MISSION_SELECTED_OVERLAY_SOURCE_OPTIONS,
  ROCKET_MISSION_AMBIENT_OVERLAY_SOURCE_OPTIONS,
} from './policy.js';

export function createOverlays({ state: layerState, services, parts, source }) {
  /**
   * Resolve whether a surface mission anchor is safely on the camera-facing
   * side of Earth. The small positive limb margin prevents labels anchored just
   * beyond the horizon from leaking through the hidden Cesium globe.
   * @param {Cesium.Cartesian3} cameraPosition Camera world position.
   * @param {Cesium.Cartesian3} markerPosition Mission anchor world position.
   * @param {number} [limbMargin] Additional normalized horizon clearance.
   * @returns {boolean} Whether the marker belongs on the visible hemisphere.
   */

  function missionAnchorHorizonVisible(
    cameraPosition,
    markerPosition,
    limbMargin = 0.012,
  ) {
    if (!cameraPosition || !markerPosition) return false;
    const cameraMagnitude = Cesium.Cartesian3.magnitude(cameraPosition);
    if (
      !Number.isFinite(cameraMagnitude) ||
      cameraMagnitude <= Cesium.Ellipsoid.WGS84.maximumRadius
    ) {
      return false;
    }
    const cameraDirection = Cesium.Cartesian3.normalize(
      cameraPosition,
      new Cesium.Cartesian3(),
    );
    const markerDirection = Cesium.Cartesian3.normalize(
      markerPosition,
      new Cesium.Cartesian3(),
    );
    const limbThreshold =
      Cesium.Ellipsoid.WGS84.maximumRadius / cameraMagnitude;
    return (
      Cesium.Cartesian3.dot(cameraDirection, markerDirection) >
      limbThreshold + limbMargin
    );
  }

  /**
   * Resolve launch-anchor visibility for overview and selected-mission views.
   * @param {Cesium.Cartesian3} cameraPosition Camera world position.
   * @param {Cesium.Cartesian3} markerPosition Mission anchor world position.
   * @param {string} markerId Mission represented by this anchor.
   * @param {string|null} selectedLaunchId Explicitly selected mission.
   * @returns {boolean} Whether the launch anchor should render.
   */

  function missionAnchorVisible(
    cameraPosition,
    markerPosition,
    markerId,
    selectedLaunchId = null,
  ) {
    if (selectedLaunchId && markerId !== selectedLaunchId) return false;
    return missionAnchorHorizonVisible(cameraPosition, markerPosition);
  }

  function shortMissionLabel(name, maxLength = 24) {
    const text = String(name || 'Unnamed mission')
      .replace(/\s+/g, ' ')
      .trim()
      .split(' | ')[0];
    const compact = text.split(' — ')[0].trim();
    return compact.length > maxLength
      ? `${compact.slice(0, maxLength - 1).trimEnd()}…`
      : compact;
  }

  /**
   * Reduce generic launch-complex names to their identifying pad or area suffix.
   * @param {string|null} launchSite Launch Library pad name.
   * @returns {string|null} Compact launch-site identifier.
   */

  function compactLaunchSiteName(launchSite) {
    const text = String(launchSite || '')
      .replace(/\s+/g, ' ')
      .trim();
    if (!text || /^(unknown|unavailable|n\/a)$/i.test(text)) return null;
    const genericPrefix =
      /^(?:orbital\s+launch\s+pad|space\s+launch\s+complex|launch\s+(?:area|complex|pad|site))\s*[-·:]?\s*/i;
    const compact = text.replace(genericPrefix, '').trim();
    return compact || null;
  }

  /**
   * Build the source-owned launch-site marker presentation. Overview markers
   * compete in the bounded ambient-label domain; the selected mission moves to
   * the protected selected lane and gains the former launch-site detail line.
   * @param {object} launch Normalized Launch Library mission.
   * @param {Cesium.Cartesian3|function():Cesium.Cartesian3} position Existing display position.
   * @param {boolean} [selected=false] Whether the mission owns the selected view.
   * @returns {object}
   */

  function createRocketMissionMarkerOverlayEntry(
    launch,
    position,
    selected = false,
  ) {
    const mission = shortMissionLabel(launch?.name, 26).toUpperCase();
    const siteName = compactLaunchSiteName(launch?.launchSite);
    const launchTimeMs = Date.parse(launch?.launchTime);
    const details = selected
      ? [
          siteName
            ? t('LAUNCH SITE · {site}', {
                site: shortMissionLabel(siteName, 20).toUpperCase(),
              })
            : t('LAUNCH SITE'),
        ]
      : [];
    return {
      id: `launch:${launch?.id}`,
      position,
      variant: 'label',
      title: mission,
      details,
      accent: '#22e6e6',
      priority: selected
        ? Number.MAX_SAFE_INTEGER
        : Number.isFinite(launchTimeMs)
          ? Math.floor(launchTimeMs / 1000)
          : 0,
      selected,
      protected: selected,
      paintLane: selected ? 'selected' : 'ambient-label',
      collisionGroup: 'ambient-label',
      interactive: false,
      distanceScale: {
        near: 1000,
        nearValue: 1.08,
        far: 20_000_000,
        farValue: 0.78,
      },
      gapPx: 12,
      verticalOnly: true,
      placement: 'above',
      edgeFade: 'keyhole',
      horizonCull: true,
      terrainOcclusion: false,
    };
  }

  /**
   * Build one protected label belonging to the selected mission's recorded
   * stage endpoint, live payload position, or orbit. Copy is already source-formatted by the
   * caller; newline semantics become explicit host detail rows.
   * @param {object} input
   * @param {string} input.id Stable mission-element identity.
   * @param {Cesium.Cartesian3|function():Cesium.Cartesian3} input.position Existing cached position.
   * @param {string} input.text Former native-label text, including newlines.
   * @param {string} input.accent Source-owned label color.
   * @param {number} [input.priority=0] Protected placement order.
   * @param {number} [input.gapPx=8] Anchor-to-label gap.
   * @returns {object}
   */

  function createRocketMissionElementOverlayEntry({
    id,
    position,
    text,
    accent,
    priority = 0,
    gapPx = 8,
  }) {
    const [title, ...details] = String(text || '').split('\n');
    return {
      id: String(id),
      position,
      variant: 'label',
      title,
      details,
      accent,
      priority,
      selected: true,
      protected: true,
      paintLane: 'selected',
      collisionGroup: 'ambient-label',
      interactive: false,
      gapPx,
      verticalOnly: true,
      placement: 'above',
      edgeFade: 'keyhole',
      horizonCull: true,
      terrainOcclusion: false,
    };
  }

  /** Keep the newest ambient mission markers with stable identity tie-breaking. */

  function selectRocketMissionMarkerOverlayCohort(
    entries,
    limit = ROCKET_MISSION_AMBIENT_OVERLAY_COHORT_LIMIT,
  ) {
    const cap = Math.max(
      0,
      Math.min(
        ROCKET_MISSION_AMBIENT_OVERLAY_COHORT_LIMIT,
        Math.floor(Number(limit) || 0),
      ),
    );
    if (!Array.isArray(entries) || cap === 0) return [];
    return entries
      .slice()
      .sort(
        (a, b) =>
          b.priority - a.priority || String(a.id).localeCompare(String(b.id)),
      )
      .slice(0, cap);
  }

  function missionHoverReticleImage() {
    if (layerState._missionHoverReticleImage)
      return layerState._missionHoverReticleImage;
    const canvas = document.createElement('canvas');
    const size = 48;
    const inset = 6;
    const arm = 12;
    canvas.width = size;
    canvas.height = size;
    const context = canvas.getContext('2d');
    context.strokeStyle = '#22e6e6';
    context.lineWidth = 2;
    context.lineCap = 'square';
    context.shadowColor = 'rgba(34, 230, 230, .72)';
    context.shadowBlur = 5;
    context.beginPath();
    context.moveTo(inset, inset + arm);
    context.lineTo(inset, inset);
    context.lineTo(inset + arm, inset);
    context.moveTo(size - inset - arm, inset);
    context.lineTo(size - inset, inset);
    context.lineTo(size - inset, inset + arm);
    context.moveTo(inset, size - inset - arm);
    context.lineTo(inset, size - inset);
    context.lineTo(inset + arm, size - inset);
    context.moveTo(size - inset - arm, size - inset);
    context.lineTo(size - inset, size - inset);
    context.lineTo(size - inset, size - inset - arm);
    context.stroke();
    layerState._missionHoverReticleImage = canvas;
    return canvas;
  }

  function clearMissionOverlaySources() {
    layerState._selectedMissionOverlayTimeText = null;
    layerState._missionOverlayHost.clearSource(
      ROCKET_MISSION_AMBIENT_OVERLAY_SOURCE_ID,
    );
    layerState._missionOverlayHost.setVisible(
      ROCKET_MISSION_AMBIENT_OVERLAY_SOURCE_ID,
      false,
    );
    layerState._missionOverlayHost.clearSource(
      ROCKET_MISSION_SELECTED_OVERLAY_SOURCE_ID,
    );
    layerState._missionOverlayHost.setVisible(
      ROCKET_MISSION_SELECTED_OVERLAY_SOURCE_ID,
      false,
    );
  }

  function syncMissionOverlayEntries() {
    if (!layerState._enabled || !layerState._dataSource?.show) {
      clearMissionOverlaySources();
      return;
    }
    const selectedRecord = layerState._selectedLaunchId
      ? layerState._missionOverlayRecords.get(layerState._selectedLaunchId)
      : null;
    if (selectedRecord) {
      layerState._missionOverlayHost.clearSource(
        ROCKET_MISSION_AMBIENT_OVERLAY_SOURCE_ID,
      );
      layerState._missionOverlayHost.setVisible(
        ROCKET_MISSION_AMBIENT_OVERLAY_SOURCE_ID,
        false,
      );
      const entries = selectedRecord.elementEntryFactories.map((createEntry) =>
        createEntry(),
      );
      entries.unshift(
        createRocketMissionMarkerOverlayEntry(
          selectedRecord.launch,
          selectedRecord.anchorPosition,
          true,
        ),
      );
      layerState._missionOverlayHost.setEntries(
        ROCKET_MISSION_SELECTED_OVERLAY_SOURCE_ID,
        entries,
        ROCKET_MISSION_SELECTED_OVERLAY_SOURCE_OPTIONS,
      );
      layerState._missionOverlayHost.setVisible(
        ROCKET_MISSION_SELECTED_OVERLAY_SOURCE_ID,
        true,
      );
      layerState._selectedMissionOverlayTimeText = selectedRecord.liveEventTime
        ? parts.policyHelpers.formatMissionEventTime(
            selectedRecord.liveEventTime(),
          )
        : null;
      return;
    }

    layerState._missionOverlayHost.clearSource(
      ROCKET_MISSION_SELECTED_OVERLAY_SOURCE_ID,
    );
    layerState._missionOverlayHost.setVisible(
      ROCKET_MISSION_SELECTED_OVERLAY_SOURCE_ID,
      false,
    );
    layerState._selectedMissionOverlayTimeText = null;
    const entries = selectRocketMissionMarkerOverlayCohort(
      Array.from(layerState._missionOverlayRecords.values(), (record) => {
        const entry = createRocketMissionMarkerOverlayEntry(
          record.launch,
          record.anchorPosition,
        );
        if (record.launch.id === layerState._hoveredRosterLaunchId) {
          entry.pinned = true;
          entry.priority = Number.MAX_SAFE_INTEGER - 1;
        }
        return entry;
      }),
    );
    layerState._missionOverlayHost.setEntries(
      ROCKET_MISSION_AMBIENT_OVERLAY_SOURCE_ID,
      entries,
      ROCKET_MISSION_AMBIENT_OVERLAY_SOURCE_OPTIONS,
    );
    layerState._missionOverlayHost.setVisible(
      ROCKET_MISSION_AMBIENT_OVERLAY_SOURCE_ID,
      true,
    );
  }

  function refreshSelectedMissionOverlayText() {
    const selectedRecord = layerState._selectedLaunchId
      ? layerState._missionOverlayRecords.get(layerState._selectedLaunchId)
      : null;
    if (!selectedRecord?.liveEventTime) return;
    const nextText = parts.policyHelpers.formatMissionEventTime(
      selectedRecord.liveEventTime(),
    );
    if (nextText !== layerState._selectedMissionOverlayTimeText)
      syncMissionOverlayEntries();
  }

  return {
    missionAnchorHorizonVisible,
    missionAnchorVisible,
    shortMissionLabel,
    compactLaunchSiteName,
    createRocketMissionMarkerOverlayEntry,
    createRocketMissionElementOverlayEntry,
    selectRocketMissionMarkerOverlayCohort,
    missionHoverReticleImage,
    clearMissionOverlaySources,
    syncMissionOverlayEntries,
    refreshSelectedMissionOverlayText,
  };
}
