import * as Cesium from 'cesium';
import { TRAJECTORY_STAGE_COLORS } from './policy.js';

export function createRendering({
  state: layerState,
  services,
  parts,
  source,
}) {
  const { getSatelliteOrbitTrack, findSatelliteOrbitTrackInTle } =
    services.satellites;

  function setGraphicVisibility(graphic, visible, time) {
    if (!graphic) return;
    const next = Boolean(visible);
    const current = graphic.show?.getValue?.(time);
    if (current !== next) graphic.show = next;
  }

  function updateMissionFrame() {
    if (
      !layerState._enabled ||
      !layerState._viewer ||
      !layerState._dataSource?.show
    ) {
      return;
    }
    parts.panel.updateMissionTelemetry();
    const time = Cesium.JulianDate.now(layerState._declutterTime);
    layerState._declutterOccluder.cameraPosition =
      layerState._viewer.scene.camera.positionWC;
    parts.overlays.refreshSelectedMissionOverlayText();
    for (const entity of layerState._dataSource.entities.values) {
      if (!entity.show) continue;
      if (!entity.position) continue;
      const id = parts.selection.entityLaunchId(entity);
      if (!id) continue;
      const position = entity.position.getValue(time);
      let horizonVisible = Boolean(
        position && layerState._declutterOccluder.isPointVisible(position),
      );
      const launchAnchor = entity.id.startsWith('rocket-launch:');
      if (launchAnchor) {
        horizonVisible = parts.overlays.missionAnchorVisible(
          layerState._viewer.scene.camera.positionWC,
          position,
          id,
          layerState._selectedLaunchId,
        );
        // Keep entity.show reserved for mission-selection isolation. Horizon
        // state is applied to the individual graphics below so a rear-side
        // anchor remains eligible for reevaluation as the camera moves.
      }
      if (entity.point) {
        setGraphicVisibility(entity.point, horizonVisible, time);
      }
      if (launchAnchor && entity.billboard) {
        setGraphicVisibility(
          entity.billboard,
          horizonVisible && id === layerState._hoveredRosterLaunchId,
          time,
        );
      }
    }
  }

  function addLaunchEntity(launch, activeTleText = layerState._activeTleText) {
    const position = Cesium.Cartesian3.fromDegrees(launch.lon, launch.lat);
    const overlayRecord = {
      launch,
      anchorPosition: position,
      elementEntryFactories: [],
      liveEventTime: null,
    };
    layerState._missionOverlayRecords.set(launch.id, overlayRecord);
    const orbitAllowed = parts.policyHelpers.launchStatusAllowsOrbit(
      launch.status,
    );
    const coreTrack =
      orbitAllowed && launch.satelliteQuery
        ? getSatelliteOrbitTrack(launch.satelliteQuery, {
            launchTime: launch.launchTime,
          })
        : null;
    const satelliteTrack =
      coreTrack ||
      (orbitAllowed && activeTleText && launch.satelliteQuery
        ? findSatelliteOrbitTrackInTle(activeTleText, launch.satelliteQuery, {
            launchTime: launch.launchTime,
          })
        : null);
    // The only orbit drawn is one propagated from real orbital elements by the
    // satellites layer. A launch with no matching element set has no orbit.
    const orbitPath =
      orbitAllowed && satelliteTrack?.orbitPath?.length > 1
        ? satelliteTrack.orbitPath
        : null;
    launch.recoveryStages.forEach((stage) => {
      stage.endpoint = parts.model.landingEndpoint(stage);
    });
    if (satelliteTrack) layerState._orbitMatches++;
    layerState._dataSource.entities.add({
      id: `rocket-launch:${launch.id}`,
      position,
      point: {
        pixelSize: 5,
        color: parts.model.missionMarkerColor(launch),
        outlineColor: parts.model.missionMarkerColor(launch),
        outlineWidth: 0,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
      billboard: {
        image: parts.overlays.missionHoverReticleImage(),
        width: 24,
        height: 24,
        show: false,
        horizontalOrigin: Cesium.HorizontalOrigin.CENTER,
        verticalOrigin: Cesium.VerticalOrigin.CENTER,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
      properties: {
        launchId: launch.id,
        launchName: launch.name,
        launchTime: launch.launchTime,
        launchSite: launch.launchSite,
        provider: launch.provider,
        mission: launch.mission,
        status: launch.status,
        source: launch.source,
        orbit: JSON.stringify(launch.orbit || {}),
        satelliteName: satelliteTrack?.name || '',
        noradId: satelliteTrack?.noradId || '',
      },
    });
    const points = launch.trajectory
      .filter(
        (point) =>
          Number.isFinite(Number(point.latitude)) &&
          Number.isFinite(Number(point.longitude)),
      )
      .map((point) => ({
        stage: String(
          point.stage ||
            point.stage_name ||
            point.phase ||
            point.stageName ||
            'trajectory',
        ),
        position: Cesium.Cartesian3.fromDegrees(
          Number(point.longitude),
          Number(point.latitude),
          Number(point.altitude || 0),
        ),
      }));
    if (points.length > 1) {
      const segments = [];
      points.forEach((point) => {
        const previous = segments.at(-1);
        if (!previous || previous.stage !== point.stage)
          segments.push({ stage: point.stage, positions: [] });
        segments.at(-1).positions.push(point.position);
      });
      segments.forEach((segment, index) => {
        if (segment.positions.length < 2) return;
        layerState._dataSource.entities.add({
          id: `rocket-trajectory:${launch.id}:${index}`,
          polyline: {
            positions: segment.positions,
            arcType: Cesium.ArcType.NONE,
            width: 2,
            material: Cesium.Color.fromCssColorString(
              TRAJECTORY_STAGE_COLORS[index % TRAJECTORY_STAGE_COLORS.length],
            ).withAlpha(0.8),
            clampToGround: false,
          },
          properties: {
            launchId: launch.id,
            stage: segment.stage,
            source: launch.source,
          },
        });
      });
    }
    // A recovery endpoint is drawn only where the record gives the landing
    // coordinates. No path to it is drawn.
    launch.recoveryStages.forEach((stage, stageIndex) => {
      if (!stage.endpoint) return;
      layerState._dataSource.entities.add({
        id: `rocket-recovery-end:${launch.id}:${stageIndex}`,
        position: Cesium.Cartesian3.fromDegrees(
          stage.endpoint.lon,
          stage.endpoint.lat,
          12,
        ),
        point: {
          pixelSize: 4,
          color: Cesium.Color.fromCssColorString(
            TRAJECTORY_STAGE_COLORS[
              (stageIndex + 1) % TRAJECTORY_STAGE_COLORS.length
            ],
          ),
          outlineWidth: 0,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
        properties: {
          launchId: launch.id,
          stageId: stage.id,
          phase: 'RECOVERY_ENDPOINT',
          source: launch.source,
        },
      });
    });
    if (satelliteTrack && orbitPath) {
      const orbitCurrent = satelliteTrack.current || {
        longitude: launch.lon,
        latitude: launch.lat,
        altitude: 0,
      };
      let livePosition = Cesium.Cartesian3.fromDegrees(
        orbitCurrent.longitude,
        orbitCurrent.latitude,
        orbitCurrent.altitude,
      );
      const liveTime = new Date();
      const liveTelemetry = { speedMps: null };
      layerState._satelliteTelemetry.set(launch.id, liveTelemetry);
      let liveFrameNumber = -1;
      const updateLiveState = () => {
        const frameNumber =
          layerState._viewer?.scene?.frameState?.frameNumber ?? -1;
        if (frameNumber !== -1 && frameNumber === liveFrameNumber) return;
        liveFrameNumber = frameNumber;
        liveTime.setTime(Date.now());
        const propagated =
          satelliteTrack.positionAt?.(liveTime) || satelliteTrack.current;
        if (propagated) {
          Cesium.Cartesian3.fromDegrees(
            propagated.longitude,
            propagated.latitude,
            propagated.altitude,
            undefined,
            livePosition,
          );
          liveTelemetry.speedMps = Number.isFinite(propagated.speedMps)
            ? propagated.speedMps
            : null;
        }
      };
      layerState._dataSource.entities.add({
        id: `rocket-satellite:${launch.id}`,
        position: new Cesium.CallbackProperty(() => {
          updateLiveState();
          return livePosition;
        }, false),
        point: {
          pixelSize: 6,
          color: Cesium.Color.fromCssColorString('#7bed9f'),
          outlineWidth: 0,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
        properties: {
          launchId: launch.id,
          noradId: satelliteTrack.noradId || '',
          phase: 'CURRENT_SATELLITE_POSITION',
          source: 'Satellites layer',
        },
      });
      overlayRecord.liveEventTime = () => liveTime;
      overlayRecord.elementEntryFactories.push(() => {
        const name = parts.overlays
          .shortMissionLabel(satelliteTrack.name, 22)
          .toUpperCase();
        return parts.overlays.createRocketMissionElementOverlayEntry({
          id: `payload-position:${launch.id}`,
          position: () => livePosition,
          text: `${name}\n${parts.policyHelpers.formatMissionEventTime(liveTime)}`,
          accent: '#7bed9f',
          priority: 900_000,
          gapPx: 12,
        });
      });
      // Live satellite rings use a primitive collection so the core Satellite
      // GMST transform can rotate their baked ECEF geometry without rebuilding
      // it. The ring exists only for a real element set (gmstAtBake).
      const primitiveOrbitAdded = parts.orbitRendering.addMissionOrbitPrimitive(
        launch,
        orbitPath,
        satelliteTrack,
      );
      if (!primitiveOrbitAdded) {
        layerState._dataSource.entities.add({
          id: `rocket-orbit:${launch.id}`,
          polyline: {
            positions: orbitPath,
            // The 3 px canvas gives the periodic dot room to read as round; the
            // shader masks the ten intervening dashes down to a thin center stroke.
            width: 3,
            material:
              new parts.orbitRendering.MissionOrbitPatternMaterialProperty(
                Cesium.Color.fromCssColorString('#22e6e6').withAlpha(0.95),
              ),
            arcType: Cesium.ArcType.NONE,
          },
          properties: {
            launchId: launch.id,
            satelliteName: satelliteTrack.name || '',
            noradId: satelliteTrack.noradId || '',
            source: 'Satellites layer',
          },
        });
      }
      const orbitLabelBakePosition = orbitPath[0];
      let orbitLabelPosition = orbitLabelBakePosition;
      const primitivePath = layerState._missionOrbitPrimitives.get(launch.id);
      if (primitiveOrbitAdded && primitivePath) {
        primitivePath.labelBakePosition = orbitLabelBakePosition;
        primitivePath.labelPosition = Cesium.Matrix4.multiplyByPoint(
          primitivePath.primitive.modelMatrix,
          orbitLabelBakePosition,
          new Cesium.Cartesian3(),
        );
        orbitLabelPosition = () => primitivePath.labelPosition;
      }
      overlayRecord.elementEntryFactories.push(() =>
        parts.overlays.createRocketMissionElementOverlayEntry({
          id: `orbit:${launch.id}`,
          position: orbitLabelPosition,
          text: 'ORBIT',
          accent: '#22e6e6',
          priority: 800_000,
          gapPx: 8,
        }),
      );
    }
  }
  return { setGraphicVisibility, updateMissionFrame, addLaunchEntity };
}
