import { createApplicationLaunches } from '../app/layers/rocketLaunches.js';
import { createSourceSlot } from '../sources/sourceSlot.js';
import { createLaunchSource } from '../layers/launches/index.js';
import * as satellites from './satellites.js';

const sourceSlot = createSourceSlot(
  createLaunchSource(),
  ['getLaunches', 'getActiveTle'],
  'Launch source',
);
export const configureLaunchSource = sourceSlot.configure;
const layer = createApplicationLaunches({
  source: sourceSlot.source,
  satellites,
});
export const satelliteParamsForSpaceMissions =
  layer.satelliteParamsForSpaceMissions;
export const satelliteParamsAfterSpaceMissions =
  layer.satelliteParamsAfterSpaceMissions;
export const launchStatusAllowsOrbit = layer.launchStatusAllowsOrbit;
export const missionPathPresentation = layer.missionPathPresentation;
export const shouldRetryAfterActiveTle = layer.shouldRetryAfterActiveTle;
export const launchPadZoneVisible = layer.launchPadZoneVisible;
export const missionAnchorHorizonVisible = layer.missionAnchorHorizonVisible;
export const missionAnchorVisible = layer.missionAnchorVisible;
export const compactLaunchSiteName = layer.compactLaunchSiteName;
export const createRocketMissionMarkerOverlayEntry =
  layer.createRocketMissionMarkerOverlayEntry;
export const createRocketMissionElementOverlayEntry =
  layer.createRocketMissionElementOverlayEntry;
export const selectRocketMissionMarkerOverlayCohort =
  layer.selectRocketMissionMarkerOverlayCohort;
export const missionDataCompleteness = layer.missionDataCompleteness;
export const missionRosterEntries = layer.missionRosterEntries;
export const missionHoverPreviewRange = layer.missionHoverPreviewRange;
export const createMissionRosterPreviewOwnership =
  layer.createMissionRosterPreviewOwnership;
export const bindMissionRosterItemKeyboardPreview =
  layer.bindMissionRosterItemKeyboardPreview;
export const captureMissionRosterFocus = layer.captureMissionRosterFocus;
export const restoreMissionRosterFocus = layer.restoreMissionRosterFocus;
export const resolveMissionRosterPreviewLaunch =
  layer.resolveMissionRosterPreviewLaunch;
export const formatMissionEventTime = layer.formatMissionEventTime;
export const parseMissionDurationSeconds = layer.parseMissionDurationSeconds;
export const missionZoomPitch = layer.missionZoomPitch;
export const missionMarkerColor = layer.missionMarkerColor;
export const normalizeRocketLaunches = layer.normalizeRocketLaunches;
export const _setRocketMissionOverlayHostForTest =
  layer._setRocketMissionOverlayHostForTest;
export const _setSelectedRocketMissionForTest =
  layer._setSelectedRocketMissionForTest;
export {
  ROCKET_MISSION_AMBIENT_OVERLAY_SOURCE_ID,
  ROCKET_MISSION_SELECTED_OVERLAY_SOURCE_ID,
  ROCKET_MISSION_AMBIENT_OVERLAY_COHORT_LIMIT,
  ROCKET_MISSION_AMBIENT_OVERLAY_COLLISION_CAPACITY,
  ROCKET_MISSION_SELECTED_OVERLAY_SOURCE_OPTIONS,
  LAUNCH_PAD_ZONE_RADIUS_M,
} from '../layers/launches/index.js';
export default layer;
