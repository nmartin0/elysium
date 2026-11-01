/**
 * Fork change (Astrolabe): run in a sandboxed frame.
 *
 * A frame with `sandbox="allow-scripts"` has an opaque origin
 * (`self.origin === 'null'`), so every http(s) URL is cross-origin to it.
 * Cesium decides whether to load an image with `crossOrigin` by comparing
 * the URL's host with `window.location`, which in an opaque origin says
 * "same host", so it loads same-host images without `crossOrigin` and WebGL
 * then refuses the tainted image (SecurityError from texImage2D). Force
 * `crossOrigin` for http(s) image loads. The asset host must answer with
 * `Access-Control-Allow-Origin: *`.
 *
 * Does nothing outside an opaque origin, so the normal build is unchanged.
 * `Cesium.Resource.isCrossOriginUrl` cannot be replaced (it is not
 * configurable); the image loader it feeds can.
 */
export function installOpaqueOriginImageLoading(
  Cesium,
  { origin = globalThis.origin } = {},
) {
  if (origin !== 'null') return false;
  const implementations = Cesium.Resource._Implementations;
  const createImage = implementations.createImage;
  implementations.createImage = function (request, crossOrigin, ...rest) {
    const isNetworkUrl = /^https?:/i.test(String(request?.url ?? ''));
    return createImage.call(
      this,
      request,
      crossOrigin || isNetworkUrl,
      ...rest,
    );
  };
  return true;
}
