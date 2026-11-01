/**
 * Whether the page is shown embedded. Kept free of imports so modules that
 * only need to ask (startup chrome, request helpers, diagnostics) do not
 * pull Cesium in through app/embed.js.
 */

/**
 * `?embed=1` when another page frames the app, or inline when a panel page
 * loads the app into itself and sets `globalThis.GEV_EMBED_INLINE` first.
 */
export function isEmbedded(location = globalThis.location) {
  return (
    isEmbeddedInline() ||
    new URLSearchParams(location?.search || '').get('embed') === '1'
  );
}

/** Whether a panel page loaded the app into itself. */
export function isEmbeddedInline() {
  return globalThis.GEV_EMBED_INLINE === true;
}
