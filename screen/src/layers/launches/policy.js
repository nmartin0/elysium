import * as Cesium from 'cesium';

export const WINDOW_DAYS = 30;

export const ROCKET_MISSION_AMBIENT_OVERLAY_SOURCE_ID = 'rocket-missions';

export const ROCKET_MISSION_SELECTED_OVERLAY_SOURCE_ID =
  'rocket-mission-selected';

export const ROCKET_MISSION_AMBIENT_OVERLAY_COHORT_LIMIT = 48;

export const ROCKET_MISSION_AMBIENT_OVERLAY_COLLISION_CAPACITY = 24;

export const ROCKET_MISSION_SELECTED_OVERLAY_SOURCE_OPTIONS = Object.freeze({
  cohortLimit: 12,
  collisionCapacity: 0,
  moving: true,
  solveIntervalMs: 0,
});

export const ROCKET_MISSION_AMBIENT_OVERLAY_SOURCE_OPTIONS = Object.freeze({
  cohortLimit: ROCKET_MISSION_AMBIENT_OVERLAY_COHORT_LIMIT,
  collisionCapacity: ROCKET_MISSION_AMBIENT_OVERLAY_COLLISION_CAPACITY,
  moving: false,
});

export const MAX_POST_TLE_RETRIES = 1;

export const POST_TLE_RETRY_DELAY_MS = 1500;

export const MISSION_CLOSE_VIEW_RANGE_M = 180000;

export const MISSION_GLOBE_VIEW_RANGE_M = 5000000;

export const MISSION_FOCUS_RANGE_M = 12000;

export const SATELLITE_STANDALONE_DEFAULTS = {
  catalog: 'core',
  showPoints: true,
  showOrbits: true,
};

export const MISSION_ORBIT_PATTERN_GROUPS = 4;

export const MISSION_ORBIT_DASHES_PER_GROUP = 100;

export const LAUNCH_PAD_ZONE_RADIUS_M = 500;

export const LAUNCH_PAD_ZONE_MAX_CAMERA_HEIGHT_M = 120000;

export const LAUNCH_PAD_ZONE_MAX_CAMERA_DISTANCE_M = 180000;

export const TRAJECTORY_STAGE_COLORS = [
  '#ff9f43',
  '#ff66c4',
  '#a78bfa',
  '#7bed9f',
  '#ffd166',
  '#60a5fa',
];
