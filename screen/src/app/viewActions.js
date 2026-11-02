/**
 * The actions an embedded view runs (see applyView in embed.js): visual style,
 * map imagery, layer visibility, following an entity, and annotations.
 *
 * Fork: extracted from the removed voice action runner (voice/gevActions.js).
 * Only the seven actions a view needs are kept, each reduced to its plain
 * behaviour; there is no voice session, no spoken result shaping and no
 * cockpit.
 */

import { flyToLandmark } from '../locations.js';

/** Layers whose entities can be followed or selected, and what they are. */
const TRACKABLE_FAMILIES = Object.freeze([
  { layerId: 'flights', kind: 'aircraft' },
  { layerId: 'ais-live-vessels', kind: 'vessel' },
  { layerId: 'satellites', kind: 'satellite' },
]);

// Bounds on one annotate call: a view is data from outside, so a runaway one
// must not drive unbounded geocoding or drawing work.
const MAX_ANNOTATIONS_PER_CALL = 24;
const MAX_ROUTE_POINTS = 12;
const MAX_TARGET_LEN = 200;
const MAX_LABEL_LEN = 120;

const clampStr = (value, max) =>
  typeof value === 'string' ? value.trim().slice(0, max) : value;

function sanitizeAnnotationSpec(spec) {
  if (!spec || typeof spec !== 'object') return spec;
  const out = { ...spec };
  if (typeof out.target === 'string')
    out.target = clampStr(out.target, MAX_TARGET_LEN);
  if (typeof out.toTarget === 'string')
    out.toTarget = clampStr(out.toTarget, MAX_TARGET_LEN);
  if (typeof out.label === 'string')
    out.label = clampStr(out.label, MAX_LABEL_LEN);
  if (Array.isArray(out.points)) {
    out.points = out.points
      .slice(0, MAX_ROUTE_POINTS)
      .map((p) =>
        p && typeof p === 'object' && typeof p.target === 'string'
          ? { ...p, target: clampStr(p.target, MAX_TARGET_LEN) }
          : p,
      );
  }
  return out;
}

async function annotateMap(annotations, args = {}) {
  if (typeof annotations?.annotate !== 'function')
    return {
      ok: false,
      action: 'annotate_map',
      error: 'Annotation engine unavailable',
    };
  const raw = Array.isArray(args.annotations) ? args.annotations : [];
  if (!raw.length)
    return {
      ok: false,
      action: 'annotate_map',
      error: 'No annotations supplied',
    };
  if (raw.length > MAX_ANNOTATIONS_PER_CALL)
    return {
      ok: false,
      action: 'annotate_map',
      error: `Too many annotations in one call (${raw.length}); max ${MAX_ANNOTATIONS_PER_CALL}`,
    };
  const result = await annotations.annotate(raw.map(sanitizeAnnotationSpec), {
    // Drawing never clears; only clear_annotations wipes the board.
    clearPrevious: false,
    persist: args.persist !== false,
    flyTo: Boolean(args.flyTo),
  });
  const drewSome = result.drawn > 0;
  const someFailed = result.failed > 0;
  return {
    ok: drewSome,
    action: 'annotate_map',
    drawn: result.drawn,
    failed: result.failed,
    partial: drewSome && someFailed,
    capped: Boolean(result.capped),
    items: result.results,
    error: someFailed ? 'Could not place one or more annotations' : null,
  };
}

function clearAnnotations(annotations) {
  if (typeof annotations?.clear !== 'function')
    return {
      ok: false,
      action: 'clear_annotations',
      error: 'Annotation engine unavailable',
    };
  annotations.clear();
  return { ok: true, action: 'clear_annotations' };
}

function runManagedNavigation(styleManager, noun, action, navigate) {
  if (typeof styleManager?.runImmediateNavigation !== 'function')
    return { ok: false, action, error: 'Camera navigation policy unavailable' };
  const result = styleManager.runImmediateNavigation(noun, navigate);
  if (result !== false) return result;
  return {
    ok: false,
    action,
    error: 'Camera navigation is unavailable in the current view',
  };
}

/** Find an entity by query in the enabled entity layers and follow/select it. */
function trackEntity(viewer, dataManager, styleManager, args = {}) {
  const query = String(args.query || '').trim();
  if (!query) throw new Error('track_entity needs a query');
  const requested = args.layerId ? String(args.layerId) : null;
  const skippedDisabled = [];
  for (const family of TRACKABLE_FAMILIES) {
    if (requested && family.layerId !== requested) continue;
    if (!dataManager.isEnabled(family.layerId)) {
      skippedDisabled.push(family.layerId);
      continue;
    }
    const module = dataManager.layers.get(family.layerId)?.module;
    if (typeof module?.findByQuery !== 'function') continue;
    const found = module.findByQuery(query);
    if (!found) continue;
    if (
      family.kind === 'vessel' &&
      (!Number.isFinite(found.latitude) || !Number.isFinite(found.longitude))
    )
      return {
        ok: false,
        action: 'track_entity',
        layerId: family.layerId,
        kind: family.kind,
        error: 'The matched vessel has no usable position',
      };
    return runManagedNavigation(
      styleManager,
      family.kind,
      'track_entity',
      () => {
        let trackedOk = false;
        if (family.kind === 'vessel') {
          trackedOk = !!module.selectById?.(found.mmsi);
          flyToLandmark(viewer, found.latitude, found.longitude, {
            range: 6000,
            pitch: -45,
            heading: 0,
            buildingHeight: 0,
            duration: 2.0,
          });
        } else if (family.kind === 'satellite') {
          trackedOk = !!module.trackById?.(found.noradId, { origin: 'tool' });
        } else {
          trackedOk = !!module.trackById?.(found.icao24, { origin: 'tool' });
        }
        return {
          ok: trackedOk,
          action: 'track_entity',
          layerId: family.layerId,
          kind: family.kind,
          error: trackedOk ? null : 'Match found but tracking failed',
        };
      },
    );
  }
  const disabledNote = skippedDisabled.length
    ? ` (disabled layers skipped: ${skippedDisabled.join(', ')})`
    : '';
  return {
    ok: false,
    action: 'track_entity',
    query,
    error: `Nothing matched "${query}"${disabledNote}`,
  };
}

/** Release tracking and selection on every entity layer. */
function stopAllTracking(viewer, dataManager) {
  const released = [];
  const failed = new Set();
  const tracking = {
    flights: 'selectedFlightsTrackingId',
    satellites: 'selectedSatTrackingId',
  };
  for (const family of TRACKABLE_FAMILIES) {
    const module = dataManager.layers.get(family.layerId)?.module;
    if (!module) continue;
    try {
      if (family.kind === 'vessel') {
        if (module.getSelectedInfo?.()) {
          if (
            typeof module.clearSelection !== 'function' ||
            module.clearSelection() === false
          )
            failed.add(family.layerId);
          else released.push(family.layerId);
        }
      } else if (module.getTrackedInfo?.()) {
        if (
          typeof module.stopTracking !== 'function' ||
          module.stopTracking({ origin: 'tool' }) === false
        )
          failed.add(family.layerId);
        else released.push(family.layerId);
      }
    } catch {
      failed.add(family.layerId);
    }
  }
  for (const [layerId, key] of Object.entries(tracking)) {
    try {
      if (
        dataManager.setLayerParams(
          layerId,
          { [key]: null },
          { origin: 'tool' },
        ) === false
      )
        failed.add(layerId);
    } catch {
      failed.add(layerId);
    }
  }
  if (viewer) viewer.trackedEntity = undefined;
  if (failed.size) {
    const failedLayerIds = [...failed];
    return {
      ok: false,
      action: 'stop_tracking',
      released,
      failedLayerIds,
      error: `Tracking could not be cleared for: ${failedLayerIds.join(', ')}`,
    };
  }
  return { ok: true, action: 'stop_tracking', released };
}

async function setLayerVisibility(dataManager, args, signal) {
  const layerId = String(args.layerId || '').trim();
  if (!layerId || !dataManager.layers.has(layerId))
    throw new Error(`Unknown data layer: ${layerId || 'missing'}`);
  const enabled = Boolean(args.enabled);
  const options = { origin: 'tool', ...(signal ? { signal } : {}) };
  let changed;
  try {
    if (typeof dataManager._setEnabledWithIntent === 'function') {
      const intent = dataManager._setEnabledWithIntent(
        layerId,
        enabled,
        options,
      );
      changed = await intent.promise;
      if (Number.isInteger(intent.intentEpoch))
        await dataManager._waitForVisibilityIntent?.(
          layerId,
          intent.intentEpoch,
        );
    } else {
      changed = await dataManager.setEnabled(layerId, enabled, options);
    }
  } catch (error) {
    return {
      ok: false,
      action: 'set_layer_visibility',
      layerId,
      error:
        error?.message ||
        `Could not ${enabled ? 'enable' : 'disable'} the requested layer`,
    };
  }
  const settled = dataManager.isEnabled(layerId) === enabled;
  if (changed === false || !settled)
    return {
      ok: false,
      action: 'set_layer_visibility',
      layerId,
      error: `Could not ${enabled ? 'enable' : 'disable'} the requested layer`,
    };
  return { ok: true, action: 'set_layer_visibility', layerId };
}

/**
 * The runner `applyView` calls: `run(name, args)` resolves to a result with
 * `ok`. Unknown names throw, as the removed runner did.
 */
export function createViewActions({
  viewer,
  dataManager,
  styleManager,
  annotations,
  signal,
}) {
  return async function run(name, args = {}) {
    switch (name) {
      case 'set_visual_style': {
        const style = String(args.style || '').trim();
        if (!style) throw new Error('Unknown visual style: missing');
        styleManager.setStyle(style, { userInitiated: true });
        return { ok: true, action: 'set_visual_style', style };
      }
      case 'set_map_stack': {
        const stackId = String(args.stack || '').trim();
        if (!stackId) throw new Error('Unknown map stack: missing');
        const result = await styleManager.setMapStack(stackId);
        return { action: 'set_map_stack', requested: stackId, ...result };
      }
      case 'set_layer_visibility':
        return setLayerVisibility(dataManager, args, signal);
      case 'track_entity':
        return trackEntity(viewer, dataManager, styleManager, args);
      case 'stop_tracking':
        return stopAllTracking(viewer, dataManager);
      case 'annotate_map':
        return annotateMap(annotations, args);
      case 'clear_annotations':
        return clearAnnotations(annotations);
      default:
        throw new Error(`Unknown view action: ${name}`);
    }
  };
}
