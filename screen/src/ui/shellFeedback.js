/** Own loading notices, toast timing and visibility cleanup. */
import {
  aggregateLayerLoading,
  createGlobalStatusNotice,
  createLoadingFeedbackState,
  presentGlobalLoadingStatus,
  reduceLoadingFeedback,
} from '../loadingFeedback.js';
import { setSplitFlapText, disposeSplitFlap } from '../splitFlap.js';
import { t, msg } from '../i18n/index.js';
import { localizeLayerName } from './layerPanel.js';

// The server also loads loadingFeedback.js (through the HUD summary), so its
// labels stay English. Translate the known ones; pass anything else (a live
// provider error) through.
const STATUS_LABEL_KEYS = Object.freeze({
  'LOADING LIVE DATA': msg('LOADING LIVE DATA'),
  'LOAD COMPLETE': msg('LOAD COMPLETE'),
  'LOAD CANCELLED': msg('LOAD CANCELLED'),
  'LOAD FAILED': msg('LOAD FAILED'),
  'LIVE DATA OFF': msg('LIVE DATA OFF'),
  'TURNING OFF LIVE DATA': msg('TURNING OFF LIVE DATA'),
  'REFRESHING LIVE DATA': msg('REFRESHING LIVE DATA'),
});

function localizeStatusLabel(label) {
  if (typeof label !== 'string' || !label) return label;
  const key = STATUS_LABEL_KEYS[label.trim()];
  return key ? t(key) : label;
}

// A retry detail is "retrying in Ns" or "retry pending".
const RETRY_DETAIL_RE = /^(?:retrying in (\d+)s|(retry pending))$/;

function localizeStatusDetail(detail) {
  if (typeof detail !== 'string' || !detail) return detail;
  const match = detail.trim().match(RETRY_DETAIL_RE);
  if (match) {
    const [, seconds, pending] = match;
    return pending
      ? t('retry pending')
      : t('retrying in {seconds}s', { seconds });
  }
  return localizeLayerRoster(detail);
}

// The loading detail is the active layers' English names joined by " · ",
// with " +N" when more are loading. Translate each known layer name; anything
// else (a provider such as "OpenStreetMap · Overpass") passes through.
function localizeLayerRoster(detail) {
  const [, names, suffix = ''] = detail.match(/^(.*?)( \+\d+)?$/s) || [];
  if (!names) return detail;
  return (
    names
      .split(' · ')
      .map((name) => localizeLayerName(name))
      .join(' · ') + suffix
  );
}

/** The chip's label and detail in the UI language (exported for tests). */
export function localizeLoadingPresentation(presentation) {
  if (!presentation) return presentation;
  return {
    ...presentation,
    label: localizeStatusLabel(presentation.label),
    detail: localizeStatusDetail(presentation.detail),
  };
}
export class ShellFeedback {
  constructor({ readLayers }) {
    this.readLayers = readLayers;
    this.destroyed = false;
    this._loadingFeedbackState = createLoadingFeedbackState();
    this._loadingFeedbackEvent = null;
    this._globalStatusNotice = null;
    this._loadingFeedbackTicker =
      this._loadingPollTicker =
      this._toastTimer =
        null;
    this._loadingVisibilityHandler = null;
    this._lastLoadingFeedbackUpdateAt = 0;
    this._lastLoadingPollAt = 0;
    this._globalLoadingStatus = document.getElementById(
      'global-loading-status',
    );
    this._globalLoadingLabel = document.getElementById('global-loading-label');
    this._globalLoadingDetail = document.getElementById(
      'global-loading-detail',
    );
    this._toast = document.getElementById('toast');
  }
  observeVisibility() {
    if (this.destroyed || this._loadingVisibilityHandler) return;
    this._loadingVisibilityHandler = () => {
      if (!document.hidden) this._updateGlobalLoadingFeedback();
      else this._stopLoadingFeedbackTicker();
    };
    document.addEventListener(
      'visibilitychange',
      this._loadingVisibilityHandler,
    );
  }
  _updateGlobalLoadingFeedback(now = performance.now()) {
    if (this.destroyed) return;
    if (!this._globalLoadingStatus) return;
    const summary = aggregateLayerLoading(this.readLayers() || []);
    this._loadingFeedbackState = reduceLoadingFeedback(
      this._loadingFeedbackState,
      summary,
      now,
      this._loadingFeedbackEvent,
    );
    this._loadingFeedbackEvent = null;
    const presentation = presentGlobalLoadingStatus(
      this._globalStatusNotice,
      this._loadingFeedbackState,
      summary,
      now,
    );
    if (
      this._globalStatusNotice?.persistent !== true &&
      Number.isFinite(this._globalStatusNotice?.hideAt) &&
      now >= this._globalStatusNotice.hideAt
    ) {
      this._globalStatusNotice = null;
    }
    // Loading phases and universal notices both have time-driven transitions.
    // Compute this after arbitration: a queued finite notice starts its dwell
    // only on its first visible frame, then keeps the ticker alive to expiry.
    const noticeNeedsTicker = Number.isFinite(this._globalStatusNotice?.hideAt);
    if (this._loadingFeedbackState?.phase !== 'idle' || noticeNeedsTicker) {
      this._armLoadingFeedbackTicker();
    }
    const localized = localizeLoadingPresentation(presentation);
    this._globalLoadingStatus.hidden = !presentation;
    if (!presentation) {
      delete this._globalLoadingStatus.dataset.state;
      return;
    }
    this._globalLoadingStatus.dataset.state = presentation.state;
    // Split-flap the LABEL only ("LOADING LIVE DATA" -> "LOAD COMPLETE").
    // setSplitFlapText is a no-op when the text is unchanged, which matters
    // here: this runs on every 60 ms and 500 ms tick. The detail line is the
    // live layer roster inside an ellipsised, width-capped span — flapping a
    // list that churns as layers join would be noise, not delight.
    setSplitFlapText(this._globalLoadingLabel, localized.label);
    this._globalLoadingDetail.textContent = localized.detail;
  }

  _showGlobalStatusNotice(message, options = {}) {
    if (this.destroyed) return;
    const now = performance.now();
    this._globalStatusNotice = createGlobalStatusNotice(message, now, options);
    this._updateGlobalLoadingFeedback(now);
  }

  /**
   * 500 ms safety-net poll of the loading chip: a camera-driven layer can flip
   * its own `stats.loading` without emitting a manager event, and that is the
   * one loading start the event path cannot see.
   */
  _startLoadingPollTicker() {
    if (this.destroyed) return;
    if (this._loadingPollTicker) return;
    this._loadingPollTicker = setInterval(() => {
      if (document.hidden) return;
      const now = performance.now();
      if (now - this._lastLoadingPollAt >= 500) {
        this._lastLoadingPollAt = now;
        this._updateGlobalLoadingFeedback(now);
      }
    }, 100);
  }

  _armLoadingFeedbackTicker() {
    if (this.destroyed) return;
    // Never arm behind a hidden tab: the reducer cannot usefully advance a
    // chip nobody can see, and the old `return` INSIDE the interval left the
    // 60ms timer scheduled for the entire hidden period (a batch completing
    // while hidden could never clear it — the idle check sat behind the
    // hidden guard). visibilitychange resamples and re-arms on return.
    if (this._loadingFeedbackTicker || document.hidden) return;
    this._loadingFeedbackTicker = setInterval(() => {
      if (document.hidden) {
        this._stopLoadingFeedbackTicker();
        return;
      }
      const now = performance.now();
      this._lastLoadingFeedbackUpdateAt = now;
      this._updateGlobalLoadingFeedback(now);
      const noticeNeedsTicker = Number.isFinite(
        this._globalStatusNotice?.hideAt,
      );
      if (this._loadingFeedbackState?.phase === 'idle' && !noticeNeedsTicker) {
        this._stopLoadingFeedbackTicker();
      }
    }, 60);
  }

  _stopLoadingFeedbackTicker() {
    if (!this._loadingFeedbackTicker) return;
    clearInterval(this._loadingFeedbackTicker);
    this._loadingFeedbackTicker = null;
  }

  _showToast(message) {
    if (this.destroyed) return;
    this._toast.textContent = message;
    this._toast.classList.add('visible');
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => {
      this._toast.classList.remove('visible');
    }, 2000);
  }
  destroy() {
    if (this.destroyed) return;
    this.destroyed = true;
    this._stopLoadingFeedbackTicker();
    clearInterval(this._loadingPollTicker);
    clearTimeout(this._toastTimer);
    this._loadingPollTicker = this._toastTimer = null;
    if (this._loadingVisibilityHandler)
      document.removeEventListener(
        'visibilitychange',
        this._loadingVisibilityHandler,
      );
    this._loadingVisibilityHandler = null;
    disposeSplitFlap(this._globalLoadingLabel);
    this._toast?.classList.remove('visible');
    if (this._globalLoadingStatus) this._globalLoadingStatus.hidden = true;
  }
}
