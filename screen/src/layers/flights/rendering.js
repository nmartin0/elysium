import * as Cesium from 'cesium';
import { cyberSonarBaseAlpha } from '../../cyberSonar.js';
import { CLASS_SCALE_2D } from '../../data/aircraftClass.js';
import { isEmergency } from '../../data/aircraftEmergency.js';
import { aircraftIcon, TRACKED_ICON_PX } from '../../data/aircraftIcons.js';
import {
  cameraPoseSignature,
  horizonOccluder,
  screenProjectedRotation,
} from '../../data/iconOrientation.js';
import { limitCourseStep, courseSlewCapDps } from '../../data/motionModel.js';
import {
  MIL_TINT,
  EMERGENCY_TINT,
  GROUND_SCALE,
  FLEET_DR_INTERVAL_MS,
  RENDER_DELAY_SEC,
  COURSE_SLEW_DT_MAX_SEC,
  ROTATION_REFRESH_MS,
  COURSE_MAX_DPS,
} from './policy.js';

export function createRendering({ flightState, services, parts }) {
  const { isMilitaryIcao } = services.militaryRegistry;
  const {
    focusNowMs,
    getFocusTarget,
    nearFarScalarValueAtDistance,
    advanceProjectedSpriteFocus,
  } = services.focus;
  const { applyAircraftBillboardTreatment } = services.recession;

  /** True while this contact's latest poll broadcast an emergency code. */

  function _isEmergency(icao24, info = flightState.records.data.get(icao24)) {
    return isEmergency(info?.emergency);
  }

  /** Fleet (untracked) billboard tint: red while broadcasting an emergency,
   *  amber for known-military, white otherwise.
   *  Ground traffic gets NO special tint (owner verdict 2026-07-03 field test). */

  function _fleetBillboardColor(
    icao24,
    info = flightState.records.data.get(icao24),
  ) {
    if (_isEmergency(icao24, info)) return EMERGENCY_TINT;
    return isMilitaryIcao(icao24) ? MIL_TINT : Cesium.Color.WHITE;
  }

  /** Fleet billboard scale: per-class scale, ×GROUND_SCALE while grounded. */

  function _fleetBillboardScale(icao24, klass) {
    return (
      (CLASS_SCALE_2D[klass] || 1) *
      (flightState.records.data.get(icao24)?.onGround ? GROUND_SCALE : 1)
    );
  }

  /** Depth-test policy for aircraft billboards. Round 5 (owner directive
   *  2026-07-06: "I just want the planes and their lines to ALWAYS be
   *  visible... evenly applied"): EVERY contact renders depth-test-free at
   *  every distance — grounded, low, and airborne alike. The photoreal mesh
   *  writes depth and residual baro/floor error will always leave some sprite
   *  geometry at or below it; a uniform rule beats the grounded-only /
   *  low-AGL-only conditions that kept leaving classes of contacts buried
   *  (2026-07-03 Van Nuys grounded case; 2026-07-06 Austin QNH-below-field
   *  case). Far-side planes are still removed by the fleet tick's horizon
   *  occluder, which never depended on depth. Kept as a function so the
   *  callers' restyle sites stay diff-stable. */

  function _groundDepthDistance() {
    return Number.POSITIVE_INFINITY;
  }

  function _normalBillboardScaleByDistance() {
    // Preserve the established close-range 3× scale. Any smaller owner-visible
    // default belongs in a separate evidence-backed proposal.
    return new Cesium.NearFarScalar(1000, 3.0, 8000000, 0.5);
  }

  /** Sprite kind for one contact's billboard: its aircraft class. */

  const _iconKind = (icao24, klass) => klass;

  /** Apply the visual contract to one owned fleet billboard. */

  function _applyFleetBillboardPresentation(icao24, bb) {
    if (!bb) return;
    const limbScale = flightState._billboardLimbScale.get(bb) ?? 1;
    const meta = flightState.records.data.get(icao24);
    bb.image = aircraftIcon(
      _iconKind(icao24, meta?.klass),
      bb._gevIconLarge ? TRACKED_ICON_PX : undefined,
    );
    bb.width = icao24 === flightState._trackedIcao ? 24 : 20;
    bb.height = icao24 === flightState._trackedIcao ? 24 : 20;
    bb.scale = _fleetBillboardScale(icao24, meta?.klass) * limbScale;
    bb.scaleByDistance = _normalBillboardScaleByDistance();
    bb.color = _fleetBillboardColor(icao24).withAlpha(cyberSonarBaseAlpha(bb));
  }

  /**
   * Per-preRender fleet pass at ~12Hz: dead-reckons every untracked billboard,
   * horizon-culls billboards beyond the limb (no far-side depth with the globe
   * hidden), and refreshes screen-projected icon rotations whenever the camera
   * pose changed (plus a 1s drift catch-up while idle). Driven by
   * scene.preRender — NOT camera.changed, whose granularity is globally
   * degraded by other layers mutating camera.percentageChanged.
   * @returns {void}
   */

  function _fleetTick() {
    if (
      !flightState._viewer ||
      !flightState._billboardCollection ||
      !flightState._billboardCollection.show
    )
      return;
    const scene = flightState._viewer.scene;
    const camera = flightState._viewer.camera;
    const nowMs = focusNowMs(Date.now());

    // (The tracked trail head is now the per-frame _trailHeadEntity segment — no 1 Hz
    // primitive rebuild needed here anymore.)

    if (nowMs - flightState._lastFleetTickMs < FLEET_DR_INTERVAL_MS) return;
    const tickDtSec = flightState._lastFleetTickMs
      ? Math.min(
          COURSE_SLEW_DT_MAX_SEC,
          (nowMs - flightState._lastFleetTickMs) / 1000,
        )
      : 0.08;
    flightState._lastFleetTickMs = nowMs;
    // Every contact in this pass shares the same delayed display instant.
    const renderTime = Cesium.JulianDate.addSeconds(
      Cesium.JulianDate.now(flightState._scratchFleetRenderTime),
      -RENDER_DELAY_SEC,
      flightState._scratchFleetRenderTime,
    );

    const poseSig = cameraPoseSignature(camera);
    const doRotations =
      poseSig !== flightState._lastCamPoseSig ||
      nowMs - flightState._lastRotPassMs >= ROTATION_REFRESH_MS;
    if (doRotations) {
      flightState._lastCamPoseSig = poseSig;
      flightState._lastRotPassMs = nowMs;
    }

    const occluder = horizonOccluder(camera);
    const focusTarget = getFocusTarget();

    for (const [icao24, bb] of flightState._billboards) {
      if (icao24 === flightState._trackedIcao) continue; // tracked entity owns its own motion

      const info = flightState.records.data.get(icao24);

      const dr = parts.motion._deadReckon(
        icao24,
        flightState._scratchFleetPos,
        renderTime,
      );
      // The dead-reckoned point drifts away from the fix whose cell supplied the
      // height, so a grounded contact's sprite ends up under the mesh it taxied
      // (or coasted) over. Re-floor at the DISPLAYED coordinate (read-only).
      const display = parts.motion._floorGroundedDisplayPosition(
        icao24,
        info,
        dr,
        nowMs,
      );
      // Gate the write — assigning Billboard.position dirties the whole
      // collection's vertex buffer, so skip sub-meter moves.
      if (
        display &&
        Cesium.Cartesian3.distanceSquared(display, bb.position) > 1.0
      ) {
        bb.position = display;
      }

      // Round 6: occlusion-test a LIFTED point for contacts rendering below
      // (or within a wingspan of) the ellipsoid — EllipsoidalOccluder judges a
      // sub-ellipsoid point near the limb "beyond the horizon" and the fleet
      // pass would hide a plane that is really just low over high-N terrain
      // waiting for its floor to warm (ATL grounded contacts at geoid −31 m).
      const beyondHorizon = !occluder.isPointVisible(
        flightState._cullPositions.get(icao24) || bb.position,
      );
      // A billboard flipping INTO view (horizon reveal while the camera idles)
      // gets its rotation refreshed THIS tick even without a pose change —
      // otherwise it reappears wearing its stale (often creation-north) nose for
      // up to ROTATION_REFRESH_MS.
      const revealed = !beyondHorizon && !bb.show;
      if (bb.show === beyondHorizon) bb.show = !beyondHorizon;
      if (beyondHorizon) continue;

      // One order-independent write site composes freshness × focus × limb haze
      // for alpha, and base class/ground scale × limb taper for scale. Cesium's
      // locked NearFarScalar remains a separate multiplicative stage. This
      // narrowly amends always-visible rendering without count culling or zero
      // alpha; nearer focus behavior remains tunable rather than universal.
      const cameraDistanceM = Cesium.Cartesian3.distance(
        camera.positionWC,
        bb.position,
      );
      const distanceScale = nearFarScalarValueAtDistance(
        bb.scaleByDistance,
        cameraDistanceM,
      );
      const focus = advanceProjectedSpriteFocus(
        bb,
        bb.position,
        scene,
        camera,
        nowMs,
        focusTarget,
        undefined,
        (bb.width || 20) * (bb.scale || 1) * distanceScale * 0.5,
        (bb.height || 20) * (bb.scale || 1) * distanceScale * 0.5,
      );
      const baseColor = _fleetBillboardColor(icao24, info);
      const treatment = applyAircraftBillboardTreatment({
        billboard: bb,
        baseScale: _fleetBillboardScale(icao24, info?.klass),
        baseAlpha: flightState.records.missingPolls.get(icao24) ? 0.45 : 1,
        baseColor,
        focusFactor: focus.factor,
        cameraDistanceM,
        cameraHeightM: camera.positionCartographic?.height,
      });
      flightState._billboardLimbScale.set(bb, treatment.factors.scale);
      // Two-tier glyph raster (owner playtest 2026-08-16): the billboard atlas
      // has no mipmaps, so no single texture stays crisp across the ~25–150
      // device-px range scaleByDistance produces. Swap between the 64 px fleet
      // raster and the 192 px close raster on the billboard's ACTUAL on-screen
      // size — post-treatment bb.scale, so focus/limb recession counts — with
      // hysteresis so zoom oscillation never thrashes the atlas.
      const glyphDevPx =
        (bb.width || 20) *
        (bb.scale || 1) *
        distanceScale *
        (globalThis.devicePixelRatio || 1);
      const wantLarge = bb._gevIconLarge ? glyphDevPx > 56 : glyphDevPx > 76;
      if (wantLarge !== !!bb._gevIconLarge) {
        bb._gevIconLarge = wantLarge;
        bb.image = aircraftIcon(
          _iconKind(icao24, info?.klass),
          wantLarge ? TRACKED_ICON_PX : undefined,
        );
      }

      // Smoothed display course: the path direction _deadReckon just reported
      // for THIS aircraft (nothing else calls _deadReckon in between), rate-
      // limited so segment-boundary course steps glide instead of snapping.
      // The slew cap eases toward COURSE_MIN_DPS at low speed, and a hovering
      // aircraft (hold flag) keeps its previous nose direction outright.
      const rawCourse =
        flightState._drCourseDeg != null
          ? flightState._drCourseDeg
          : (info && info.true_track) || 0;
      const prevCourse = flightState._displayCourse.get(icao24);
      const course =
        flightState._drCourseHold && prevCourse != null
          ? prevCourse
          : limitCourseStep(
              prevCourse,
              rawCourse,
              courseSlewCapDps(
                flightState._drSpeedMps != null
                  ? flightState._drSpeedMps
                  : ((info && info.velocity) ?? NaN),
                COURSE_MAX_DPS,
              ),
              tickDtSec,
            );
      flightState._displayCourse.set(icao24, course);

      if (doRotations || revealed) {
        const rot = screenProjectedRotation(
          scene,
          bb.position,
          course,
          bb.rotation,
        );
        if (rot !== null && Math.abs(rot - bb.rotation) > 0.002) {
          bb.rotation = rot;
        }
      }
    }
  }
  return {
    _fleetBillboardColor,
    _fleetBillboardScale,
    _groundDepthDistance,
    _normalBillboardScaleByDistance,
    _iconKind,
    _applyFleetBillboardPresentation,
    _fleetTick,
  };
}
